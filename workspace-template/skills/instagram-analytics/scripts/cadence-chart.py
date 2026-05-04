#!/usr/bin/env python3
"""
cadence-chart.py — ASCII cadence charts from a bulk dump.

Reads bulk JSON, prints to stdout:
  1. Posts per month (last 12 months) — bar chart
  2. Posts per day-of-week — bar chart
  3. Posts per hour-of-day (Kyiv UTC+3 by default) — bar chart

Usage:
    python cadence-chart.py path/to/handle-bulk-<unix>.json [--tz-offset 3]
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone


def render_bar(label, count, max_count, width=40):
    if max_count == 0:
        return f"{label:<10} | {count:>3} | "
    bar_len = int(width * count / max_count)
    bar = "█" * bar_len
    return f"{label:<10} | {count:>3} | {bar}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", help="path to bulk dump JSON")
    ap.add_argument("--tz-offset", type=int, default=3, help="hour offset from UTC (default 3 = Kyiv)")
    ap.add_argument("--last-months", type=int, default=12)
    args = ap.parse_args()

    with open(args.dump) as f:
        data = json.load(f)

    reels = data.get("reels", data)
    if not reels:
        print("ERROR: no reels in dump", file=sys.stderr)
        sys.exit(2)

    tz = timezone(timedelta(hours=args.tz_offset))

    times = []
    for r in reels:
        ts = r.get("taken_at")
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz)
            times.append(dt)
        except (ValueError, TypeError):
            continue

    if not times:
        print("ERROR: no taken_at timestamps", file=sys.stderr)
        sys.exit(2)

    print(f"# Cadence chart — N={len(times)} reels, tz=UTC+{args.tz_offset}")
    print(f"# Period: {min(times).date()} → {max(times).date()}")
    print()

    # Months
    print("## Posts per month (last 12)")
    print()
    month_counts = Counter()
    now = max(times)
    cutoff = now.replace(day=1) - timedelta(days=args.last_months * 31)
    for t in times:
        if t >= cutoff:
            month_counts[t.strftime("%Y-%m")] += 1
    months_sorted = sorted(month_counts.keys())
    max_m = max(month_counts.values()) if month_counts else 0
    for m in months_sorted:
        print(render_bar(m, month_counts[m], max_m))
    print()

    # Day of week
    print("## Posts per day-of-week")
    print()
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_counts = Counter()
    for t in times:
        dow_counts[t.weekday()] += 1
    max_d = max(dow_counts.values()) if dow_counts else 0
    for i, name in enumerate(dow_names):
        print(render_bar(name, dow_counts.get(i, 0), max_d))
    print()

    # Hour of day
    print(f"## Posts per hour-of-day (UTC+{args.tz_offset})")
    print()
    hour_counts = Counter()
    for t in times:
        hour_counts[t.hour] += 1
    max_h = max(hour_counts.values()) if hour_counts else 0
    for h in range(24):
        print(render_bar(f"{h:02d}:00", hour_counts.get(h, 0), max_h))


if __name__ == "__main__":
    main()
