---
name: harden-vps
description: "Aggressive VPS lockdown: install Tailscale, close SSH/webhook from public internet, tighten sshd. Vesna-only. Use when: lock down server, close all ports, expose only via VPN, harden SSH, audit firewall."
user-invocable: true
agent: vesna
---

# Harden VPS — close everything, expose only via Telegram (long-poll) + Tailscale

This skill takes a server hardened to the **safe-by-default** baseline (which `installer/lib/15-hardening.sh` already did at install time) and closes the remaining public ports. After running:

- **Port 22 (SSH):** closed from public internet, reachable only over Tailscale.
- **Port 8080 (webhook):** already on `127.0.0.1` after install; this skill verifies and (optionally) re-binds to the Tailscale interface for cross-device webhook posting.
- **OpenViking 1933:** loopback only (already).
- **Telegram bots:** unaffected — they use outbound long-polling, no inbound port needed.
- **sshd:** tightened to key-only, no-root, no-password.

After this lockdown, the only paths into the VPS are:
1. Telegram messages → bots → `claude` CLI (the intended channel).
2. Tailscale-tunneled SSH from operator's devices.
3. Cloud-provider out-of-band console (last-resort recovery).

## Pre-flight (Vesna asks the operator before running anything destructive)

Confirm with the operator IN ORDER. If any answer is "no", stop and explain.

1. "Are you logged in via SSH key (not password) right now?" — `awk '$1=="PasswordAuthentication"{print $2}' /etc/ssh/sshd_config` and check that `ssh -i <key>` works for them. If unknown, abort — disabling password auth on someone using passwords locks them out.
2. "Do you have an Anthropic Max account or other identity provider for Tailscale?" Tailscale free tier needs SSO — Google / Microsoft / GitHub / Apple. If none, suggest WireGuard self-host instead and stop.
3. "Are you OK with port 22 being unreachable except from Tailscale-connected devices?" If they're not on Tailscale yet, the next step IS to install Tailscale on their laptop too — make sure they're ready.

If all three are "yes", proceed.

## Step 1 — install Tailscale on the VPS

```bash
curl -fsSL https://tailscale.com/install.sh | sh
# Bring the interface up. --ssh enables Tailscale-managed SSH (replaces openssh
# entirely if you want; we keep openssh as belt-and-braces).
# --advertise-tags lets ACLs target this VPS specifically.
tailscale up --ssh --advertise-tags=tag:vps --accept-dns=false
```

Tailscale prints an auth URL. Send it to the operator in the Technical topic and wait for them to confirm they've authenticated.

After auth, run `tailscale ip -4` and report the resulting `100.x.y.z` address — that's the VPS's tailnet address.

## Step 2 — operator verifies Tailscale-SSH works BEFORE locking down

```bash
# On operator's laptop (instruct them to do this before next step):
tailscale up
ssh root@<TAILNET_IP>     # this should work
ssh root@<PUBLIC_IP>      # this still works pre-lockdown
```

ASK the operator: "Did Tailscale-SSH succeed? (yes/no)". If no, debug — do not proceed.

## Step 3 — tighten sshd_config (irreversible-ish, do AFTER step 2 verification)

```bash
sed -i -E 's|^[#[:space:]]*PermitRootLogin.*|PermitRootLogin prohibit-password|' /etc/ssh/sshd_config
sed -i -E 's|^[#[:space:]]*PasswordAuthentication.*|PasswordAuthentication no|' /etc/ssh/sshd_config
sed -i -E 's|^[#[:space:]]*PubkeyAuthentication.*|PubkeyAuthentication yes|' /etc/ssh/sshd_config
sed -i -E 's|^[#[:space:]]*ChallengeResponseAuthentication.*|ChallengeResponseAuthentication no|' /etc/ssh/sshd_config
sed -i -E 's|^[#[:space:]]*UsePAM.*|UsePAM yes|' /etc/ssh/sshd_config
# Validate before reload — sshd refuses bad config.
sshd -t && systemctl reload sshd
```

Report the diff vs `/etc/ssh/sshd_config.tcp-pre-hardening.bak` so the operator sees exactly what changed.

## Step 4 — close port 22 from public internet, allow from Tailscale only

```bash
# Remove the public allow-22 rule (added by 15-hardening.sh).
ufw delete allow 22/tcp
# Allow SSH only from Tailscale interface.
ufw allow in on tailscale0 to any port 22 proto tcp comment 'ssh from tailnet only'
# Confirm.
ufw status verbose
```

Report `ufw status` to operator.

## Step 5 — verify lockdown from external probe

```bash
# From public internet (use a remote check, since the VPS itself can't easily
# test its own public-side firewall):
nc -zv -w 5 <PUBLIC_IP> 22 || echo "GOOD: port 22 publicly closed"
nc -zv -w 5 <PUBLIC_IP> 8080 || echo "GOOD: port 8080 publicly closed"
nc -zv -w 5 <TAILNET_IP> 22 && echo "GOOD: port 22 reachable on tailnet"
```

If `<PUBLIC_IP>:22` is still reachable after step 4, ufw didn't pick up the change — re-run `ufw reload`.

## Optional — webhook over Tailscale instead of localhost

If the operator wants to POST to `/hooks/agent` from another machine (cron on a different host, monitoring, etc.):

```bash
# Edit /home/agent/gateway/config.json:
#   webhook.listen_host: "100.x.y.z"   ← VPS's tailnet IP from step 1
sudo systemctl restart agent-user-gateway
ufw allow in on tailscale0 to any port 8080 proto tcp comment 'webhook from tailnet'
```

Now external services on the operator's tailnet can `curl 100.x.y.z:8080`. Public internet still gets nothing.

## Rollback (if anything goes wrong mid-lockdown)

The cloud-provider out-of-band console is your friend — most providers (DigitalOcean, Hetzner, etc.) give a web-based VNC/serial console that bypasses SSH entirely. Use it to:

```bash
# Restore sshd config
mv /etc/ssh/sshd_config.tcp-pre-hardening.bak /etc/ssh/sshd_config && systemctl reload sshd
# Reopen port 22
ufw allow 22/tcp
ufw reload
# Disable Tailscale if it's the problem
tailscale down
```

## Anti-patterns

- ❌ Skipping step 2 verification. If Tailscale-SSH wasn't tested first, locking down port 22 strands the operator.
- ❌ Running this skill without operator confirmation. It's destructive at the network layer; ask before each major step.
- ❌ Forgetting to advertise the VPS tag. Without `--advertise-tags=tag:vps`, Tailscale ACLs can't target this host — operator can't write rules like "only my-laptop can ssh tag:vps".
- ❌ Disabling Tailscale-managed SSH (`--ssh` flag) and then closing port 22. You'd lose SSH entirely.
- ❌ Trusting the cloud firewall alone. Provider firewalls are async — host-level ufw is the actual enforcement.

## Audit (run this anytime after lockdown to confirm state)

Vesna can call this on demand:

```bash
echo "=== sshd ==="
grep -E '^(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|MaxAuthTries|LoginGraceTime|ClientAliveInterval)' /etc/ssh/sshd_config
echo ""
echo "=== ufw ==="
ufw status verbose
echo ""
echo "=== tailscale ==="
tailscale status 2>/dev/null || echo "(not installed)"
echo ""
echo "=== open ports (host view) ==="
ss -tlnp 2>/dev/null | head
echo ""
echo "=== fail2ban ==="
fail2ban-client status sshd 2>/dev/null
echo ""
echo "=== unattended-upgrades last run ==="
ls -la /var/log/unattended-upgrades/ 2>/dev/null | head
```
