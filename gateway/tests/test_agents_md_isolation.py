"""Lock in the cross-agent reachability documentation.

Live VPS surfaced confusion: Tyrion's smoke test tried to POST
`agent=vesna` to 127.0.0.1:8080 expecting Vesna to be reachable. She isn't
— Vesna lives on a separate root-owned gateway by design. AGENTS.md used
to imply otherwise; these tests pin the corrected story so future edits
don't accidentally re-introduce the false promise.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = REPO_ROOT / "workspace-template" / "core" / "AGENTS.md"


def _text() -> str:
    return AGENTS_MD.read_text(encoding="utf-8")


def test_agents_md_documents_two_separate_gateways() -> None:
    text = _text()
    # Both systemd unit names must be called out so an operator reading the
    # doc can correlate it to systemctl output without guessing.
    assert "agent-vesna.service" in text
    assert "agent-user-gateway.service" in text


def test_agents_md_says_vesna_not_reachable_from_client_webhook() -> None:
    """Single most important sentence in the doc."""
    text = _text()
    # Look for the explicit statement (substring match — wording can evolve
    # but the assertion it makes must remain).
    assert (
        "Vesna is NOT reachable via webhook" in text
        or "Vesna is not reachable" in text.lower()
    ), "AGENTS.md must explicitly state Vesna can't be webhook'd from client agents"


def test_agents_md_explains_via_operator_path() -> None:
    """The replacement path must be documented so client agents know what
    to do instead of silently giving up."""
    text = _text()
    assert "through the operator" in text or "through the operator" in text.lower()
    assert "Technical topic" in text


def test_agents_md_explains_security_rationale() -> None:
    """If we ever consider re-enabling cross-gateway webhook routing, the
    rationale for keeping it off has to be visible in the doc."""
    text = _text()
    assert "prompt injection" in text.lower() or "security feature" in text.lower()
    assert "human-in-the-loop" in text.lower() or "without human" in text.lower()


def test_agents_md_lists_current_agents() -> None:
    text = _text()
    for agent in ("Vesna", "Leto", "Tyrion"):
        assert agent in text, f"{agent} missing from AGENTS.md catalog"


def test_agents_md_keeps_client_to_client_curl_example() -> None:
    """Leto↔Tyrion webhook IS supported and the curl example is the
    operator's reference. Don't accidentally delete it when refactoring."""
    text = _text()
    assert "127.0.0.1:8080/hooks/agent" in text
    assert "webhook-token.txt" in text
    # The curl invocation must still be code-fenced bash.
    assert "```bash" in text


def test_agents_md_404_unknown_agent_documented() -> None:
    """Tyrion's smoke test got `404 unknown agent: vesna` — doc explains
    that's the CORRECT response, not a bug."""
    text = _text()
    assert "404" in text
    assert "unknown agent" in text
    assert "correct behaviour" in text.lower() or "correct behavior" in text.lower()
