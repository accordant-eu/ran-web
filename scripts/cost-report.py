#!/usr/bin/env python3
"""
cost-report.py — Rán usage and cost summary by invite code.

Usage:
    python3 scripts/cost-report.py [ops_log_file]

Reads ops_log.jsonl and prints a summary of sessions, tokens, and cost per code.
All data is metadata only — no document content.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

OPS_LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/ops_log.jsonl")

if not OPS_LOG.exists():
    print(f"No ops log found at {OPS_LOG}")
    sys.exit(1)

entries = [json.loads(l) for l in OPS_LOG.read_text().splitlines() if l.strip()]

totals = defaultdict(lambda: {
    "sessions": 0, "completed": 0,
    "input_tokens": 0, "output_tokens": 0,
    "cost_usd": 0.0, "returns": 0,
})

for e in entries:
    code = e.get("code_used", "unknown")
    totals[code]["sessions"]      += 1
    totals[code]["completed"]     += int(e.get("completed", False))
    totals[code]["input_tokens"]  += e.get("input_tokens") or 0
    totals[code]["output_tokens"] += e.get("output_tokens") or 0
    totals[code]["cost_usd"]      += e.get("cost_usd") or 0.0
    totals[code]["returns"]       += e.get("returns_uploaded", 0)

grand = {"sessions": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}

print(f"\n{'Code':<16} {'Sessions':>8} {'Done':>6} {'Returns':>8} {'In tok':>8} {'Out tok':>8} {'Cost USD':>10}")
print("─" * 76)

for code, t in sorted(totals.items()):
    print(
        f"{code:<16} {t['sessions']:>8} {t['completed']:>6} {t['returns']:>8} "
        f"{t['input_tokens']:>8} {t['output_tokens']:>8} {t['cost_usd']:>10.4f}"
    )
    grand["sessions"]      += t["sessions"]
    grand["cost_usd"]      += t["cost_usd"]
    grand["input_tokens"]  += t["input_tokens"]
    grand["output_tokens"] += t["output_tokens"]

print("─" * 76)
print(
    f"{'TOTAL':<16} {grand['sessions']:>8} {'':>6} {'':>8} "
    f"{grand['input_tokens']:>8} {grand['output_tokens']:>8} {grand['cost_usd']:>10.4f}"
)
print(f"\n{len(entries)} sessions total · ${grand['cost_usd']:.4f} total cost\n")
