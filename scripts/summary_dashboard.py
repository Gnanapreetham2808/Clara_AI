"""
summary_dashboard.py — Auto-generate a single Markdown dashboard
summarising all accounts, their readiness, field coverage, and change stats.

Output: outputs/SUMMARY_DASHBOARD.md

Usage:
    python summary_dashboard.py
    python summary_dashboard.py --open    # open in browser after generating
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

ACCOUNTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
OUTPUT_PATH  = Path(__file__).parent.parent / "outputs" / "SUMMARY_DASHBOARD.md"

FIELDS = [
    "company_name",
    "business_hours",
    "timezone",
    "office_address",
    "services_supported",
    "emergency_definition",
    "emergency_routing_rules",
    "non_emergency_routing_rules",
    "call_transfer_rules",
    "integration_constraints",
    "after_hours_flow_summary",
    "office_hours_flow_summary",
]

FIELD_LABELS = {
    "company_name":               "Company Name",
    "business_hours":             "Business Hours",
    "timezone":                   "Timezone",
    "office_address":             "Office Address",
    "services_supported":         "Services",
    "emergency_definition":       "Emergency Def",
    "emergency_routing_rules":    "Emergency Routing",
    "non_emergency_routing_rules":"Non-Emer Routing",
    "call_transfer_rules":        "Transfer Rules",
    "integration_constraints":    "Integrations",
    "after_hours_flow_summary":   "After-Hours Flow",
    "office_hours_flow_summary":  "Office-Hours Flow",
}


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_val(memo: dict, field: str):
    if field == "company_name":
        return memo.get("company_name")
    entry = memo.get(field, {})
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _get_status(memo: dict, field: str) -> str:
    if field == "company_name":
        return "confirmed" if memo.get("company_name") else "unknown"
    entry = memo.get(field, {})
    if isinstance(entry, dict):
        return entry.get("status", "unknown")
    return "confirmed" if entry else "unknown"


def _is_empty(val) -> bool:
    return val is None or val == [] or val == {} or val == ""


def _coverage(memo: dict) -> tuple[int, int]:
    """Returns (confirmed_count, total_fields)."""
    confirmed = 0
    for field in FIELDS:
        status = _get_status(memo, field)
        val = _get_val(memo, field)
        if not _is_empty(val) and status in ("confirmed", "assumed"):
            confirmed += 1
    return confirmed, len(FIELDS)


def _readiness_icon(pct: int) -> str:
    if pct >= 90:
        return "🟢"
    elif pct >= 60:
        return "🟡"
    else:
        return "🔴"


def _field_status_icon(memo: dict, field: str) -> str:
    val = _get_val(memo, field)
    status = _get_status(memo, field)
    if _is_empty(val):
        return "❌"
    if status == "confirmed":
        return "✅"
    if status == "assumed":
        return "⚠️"
    return "❓"


def collect_account_data(account_id: str) -> dict | None:
    base = ACCOUNTS_DIR / account_id

    v1_memo   = _load(base / "v1" / "v1_memo.json")
    v2_memo   = _load(base / "v2" / "v2_memo.json")
    changes   = _load(base / "v2" / "changes.json")
    v1_spec   = _load(base / "v1" / "v1_agent_spec.json")
    v2_spec   = _load(base / "v2" / "v2_agent_spec.json")

    if not v1_memo and not v2_memo:
        return None  # account has no outputs yet

    company = None
    if v2_memo:
        company = v2_memo.get("company_name")
    if not company and v1_memo:
        company = v1_memo.get("company_name")
    if not company:
        company = account_id

    # Coverage
    v1_confirmed, total = _coverage(v1_memo) if v1_memo else (0, len(FIELDS))
    v2_confirmed, _     = _coverage(v2_memo) if v2_memo else (0, len(FIELDS))

    v1_pct = round((v1_confirmed / total) * 100) if total else 0
    v2_pct = round((v2_confirmed / total) * 100) if total else 0

    # Change stats
    added_count    = len(changes.get("changes", []))            if changes else 0
    conflict_count = len(changes.get("conflicts_resolved", [])) if changes else 0
    unknown_count  = len(changes.get("still_unknown", []))      if changes else 0

    # Unknown questions count
    open_qs = len(v2_memo.get("questions_or_unknowns", [])) if v2_memo else (
              len(v1_memo.get("questions_or_unknowns", [])) if v1_memo else 0)

    # Pipeline status
    has_v1 = v1_memo is not None
    has_v2 = v2_memo is not None

    return {
        "account_id":    account_id,
        "company":       company,
        "has_v1":        has_v1,
        "has_v2":        has_v2,
        "v1_pct":        v1_pct,
        "v2_pct":        v2_pct,
        "v2_confirmed":  v2_confirmed,
        "total_fields":  total,
        "added":         added_count,
        "conflicts":     conflict_count,
        "still_unknown": unknown_count,
        "open_qs":       open_qs,
        "v1_memo":       v1_memo,
        "v2_memo":       v2_memo,
    }


def build_dashboard(accounts_data: list[dict]) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    total_accounts = len(accounts_data)
    ready     = sum(1 for a in accounts_data if a["v2_pct"] >= 90)
    partial   = sum(1 for a in accounts_data if 60 <= a["v2_pct"] < 90)
    not_ready = sum(1 for a in accounts_data if a["v2_pct"] < 60)

    lines = [
        "# 📊 Clara Onboarding Pipeline — Summary Dashboard",
        f"\n_Auto-generated: {now}_\n",
        "---\n",

        "## 🚦 Overall Status\n",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Accounts | {total_accounts} |",
        f"| 🟢 Ready (≥90% coverage) | {ready} |",
        f"| 🟡 Partial (60–89%) | {partial} |",
        f"| 🔴 Not Ready (<60%) | {not_ready} |",
        f"| Fully processed (v1+v2) | {sum(1 for a in accounts_data if a['has_v1'] and a['has_v2'])} |",
        "",

        "---\n",
        "## 📋 Account Coverage Summary\n",
        "| Account | Company | v1 % | v2 % | Readiness | +Added | ~Updated | ✗ Unknown | ❓ Open Qs |",
        "|---------|---------|------|------|-----------|--------|----------|-----------|-----------|",
    ]

    for a in accounts_data:
        icon = _readiness_icon(a["v2_pct"])
        v1_badge = f"{a['v1_pct']}%" if a["has_v1"] else "—"
        v2_badge = f"{a['v2_pct']}%" if a["has_v2"] else "—"
        lines.append(
            f"| `{a['account_id']}` | {a['company']} | {v1_badge} | {v2_badge} "
            f"| {icon} | {a['added']} | {a['conflicts']} | {a['still_unknown']} | {a['open_qs']} |"
        )

    # ── Field-by-field coverage grid ─────────────────────────────────────────
    lines += [
        "",
        "---\n",
        "## 🔬 Field Coverage Grid (v2)\n",
        "> ✅ confirmed &nbsp; ⚠️ assumed &nbsp; ❌ missing\n",
    ]

    # Build header
    account_ids = [a["account_id"] for a in accounts_data]
    header = "| Field | " + " | ".join(account_ids) + " |"
    sep    = "|-------|" + "|".join(["-------"] * len(account_ids)) + "|"
    lines += [header, sep]

    for field in FIELDS:
        label = FIELD_LABELS.get(field, field)
        icons = []
        for a in accounts_data:
            memo = a.get("v2_memo") or a.get("v1_memo")
            if memo:
                icons.append(_field_status_icon(memo, field))
            else:
                icons.append("—")
        lines.append(f"| **{label}** | " + " | ".join(icons) + " |")

    # ── Per-account snapshots ─────────────────────────────────────────────────
    lines += [
        "",
        "---\n",
        "## 📁 Per-Account Snapshots\n",
    ]

    for a in accounts_data:
        icon = _readiness_icon(a["v2_pct"])
        lines += [
            f"### {icon} `{a['account_id']}` — {a['company']}",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Pipeline Status | {'✅ v1 + v2 complete' if a['has_v1'] and a['has_v2'] else '⏳ v1 only' if a['has_v1'] else '❌ not started'} |",
            f"| v1 Field Coverage | {a['v1_pct']}% ({a['v1_pct'] * a['total_fields'] // 100}/{a['total_fields']} fields) |" if a["has_v1"] else "| v1 Coverage | — |",
            f"| v2 Field Coverage | {a['v2_pct']}% ({a['v2_confirmed']}/{a['total_fields']} fields) |" if a["has_v2"] else "| v2 Coverage | — |",
            f"| Fields Added from Onboarding | {a['added']} |",
            f"| Conflicts Resolved | {a['conflicts']} |",
            f"| Still Unknown | {a['still_unknown']} |",
            f"| Open Questions | {a['open_qs']} |",
            "",
        ]

        if a.get("v2_memo"):
            unknowns = a["v2_memo"].get("questions_or_unknowns", [])
            if unknowns:
                lines.append("**Open Questions:**")
                for q in unknowns[:5]:  # show up to 5
                    lines.append(f"- {q}")
                if len(unknowns) > 5:
                    lines.append(f"- _…and {len(unknowns) - 5} more_")
                lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        "---\n",
        "_This dashboard is auto-generated by `scripts/summary_dashboard.py`._  ",
        "_Re-run after any pipeline update to refresh._",
    ]

    return "\n".join(lines)


def run_dashboard() -> Path:
    dirs = sorted(
        d for d in ACCOUNTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

    if not dirs:
        print("[dashboard] No account output folders found. Run the pipeline first.")
        return None

    accounts_data = []
    for d in dirs:
        data = collect_account_data(d.name)
        if data:
            accounts_data.append(data)
        else:
            print(f"[dashboard] Skipping {d.name} — no outputs yet")

    if not accounts_data:
        print("[dashboard] No accounts with output data found.")
        return None

    print(f"[dashboard] Building dashboard for {len(accounts_data)} account(s)…")
    md = build_dashboard(accounts_data)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"[dashboard] ✅ Dashboard saved → {OUTPUT_PATH}")
    return OUTPUT_PATH


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Generate a Markdown summary dashboard for all Clara accounts."
    )
    ap.add_argument(
        "--open",
        action="store_true",
        help="Open the dashboard in your default browser after generating (requires grip or a Markdown viewer)",
    )
    args = ap.parse_args()

    path = run_dashboard()

    if args.open and path:
        import subprocess, sys
        if sys.platform == "win32":
            subprocess.run(["start", str(path)], shell=True)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
