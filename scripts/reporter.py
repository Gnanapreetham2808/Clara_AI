"""
reporter.py — Generate a Markdown unknowns/summary report from a v2 spec.

Usage:
    python reporter.py --account_id acct_001
    python reporter.py --all                  # process all accounts

Output: outputs/accounts/<id>/v2/unknowns_report.md
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


ACCOUNTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"

# Human-friendly labels for each schema field
FIELD_LABELS = {
    "company_name": "Company Name",
    "business_hours": "Business Hours",
    "timezone": "Timezone",
    "office_address": "Office Address",
    "services_supported": "Services Supported",
    "emergency_definition": "Emergency Definition",
    "emergency_routing_rules": "Emergency Routing Rules",
    "non_emergency_routing_rules": "Non-Emergency Routing Rules",
    "call_transfer_rules": "Call Transfer Rules",
    "integration_constraints": "Integration Constraints",
    "after_hours_flow_summary": "After Hours Flow Summary",
    "office_hours_flow_summary": "Office Hours Flow Summary",
}

TRACKABLE_FIELDS = list(FIELD_LABELS.keys())


def _get_field_status(spec: dict, field: str) -> tuple:
    """Returns (value, status) for a field."""
    if field == "company_name":
        val = spec.get("company_name")
        return (val, "confirmed" if val else "unknown")

    entry = spec.get(field, {})
    if not isinstance(entry, dict):
        return (entry, "confirmed" if entry else "unknown")

    val = entry.get("value")
    status = entry.get("status", "unknown")
    return (val, status)


def _is_empty(value) -> bool:
    return value is None or value == [] or value == {} or value == ""


def generate_report(account_id: str, v2_memo: dict, changes_json: dict | None) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    company = v2_memo.get("company_name") or "Unknown Company"

    lines = [
        f"# Clara Onboarding Report — {company} (`{account_id}`)",
        f"\n_Generated: {now}_\n",
        "---\n",
    ]

    # ── Section 1: Field Status Overview ─────────────────────────────────────
    lines.append("## Field Status Overview\n")
    lines.append("| Field | Status | Value (truncated) |")
    lines.append("|-------|--------|-------------------|")

    confirmed_count = 0
    assumed_count = 0
    unknown_count = 0

    for field in TRACKABLE_FIELDS:
        val, status = _get_field_status(v2_memo, field)
        label = FIELD_LABELS.get(field, field)
        display_val = str(val)[:60] + "…" if val and len(str(val)) > 60 else str(val)

        if status == "confirmed":
            confirmed_count += 1
            icon = "✅"
        elif status == "assumed":
            assumed_count += 1
            icon = "⚠️"
        else:
            unknown_count += 1
            icon = "❌"

        lines.append(f"| {label} | {icon} {status} | `{display_val}` |")

    lines.append("")
    lines.append(
        f"**Summary:** {confirmed_count} confirmed, {assumed_count} assumed, {unknown_count} unknown\n"
    )

    # ── Section 2: Still Unknown ──────────────────────────────────────────────
    still_unknown = []
    for field in TRACKABLE_FIELDS:
        val, status = _get_field_status(v2_memo, field)
        if _is_empty(val) or status == "unknown":
            still_unknown.append(field)

    if still_unknown:
        lines.append("---\n")
        lines.append("## ❌ Fields Still Unknown After Onboarding\n")
        lines.append("These fields need follow-up before the agent can be fully configured:\n")
        for f in still_unknown:
            lines.append(f"- **{FIELD_LABELS.get(f, f)}** (`{f}`)")
        lines.append("")

    # ── Section 3: Open Questions ─────────────────────────────────────────────
    open_qs = v2_memo.get("questions_or_unknowns", [])
    if open_qs:
        lines.append("---\n")
        lines.append("## ❓ Open Questions\n")
        for i, q in enumerate(open_qs, 1):
            lines.append(f"{i}. {q}")
        lines.append("")

    # ── Section 4: v1 → v2 Changes Summary ───────────────────────────────────
    if changes_json:
        changes = changes_json.get("changes", [])
        conflicts = changes_json.get("conflicts_resolved", [])

        lines.append("---\n")
        lines.append("## 🔄 v1 → v2 Changes\n")

        if changes:
            lines.append("### Fields Added from Onboarding")
            for c in changes:
                lines.append(
                    f"- **{FIELD_LABELS.get(c['field'], c['field'])}**: "
                    f"`null` → `{str(c['v2_value'])[:80]}`"
                )
            lines.append("")

        if conflicts:
            lines.append("### Conflicts Resolved (onboarding value preferred)")
            for c in conflicts:
                lines.append(
                    f"- **{FIELD_LABELS.get(c['field'], c['field'])}**: "
                    f"`{str(c['v1_value'])[:40]}` → `{str(c['v2_value'])[:40]}`"
                )
            lines.append("")

        if not changes and not conflicts:
            lines.append("_No changes were made from v1 to v2._\n")

    # ── Section 5: Agent Readiness ────────────────────────────────────────────
    lines.append("---\n")
    lines.append("## 🚦 Agent Readiness\n")
    coverage_pct = round((confirmed_count / len(TRACKABLE_FIELDS)) * 100)

    if coverage_pct >= 90:
        readiness = "🟢 **READY** — Agent can be deployed."
    elif coverage_pct >= 60:
        readiness = "🟡 **PARTIAL** — Agent can run but has gaps. Review unknowns before going live."
    else:
        readiness = "🔴 **NOT READY** — Too many unknowns. Additional onboarding session required."

    lines.append(f"**Coverage:** {coverage_pct}% ({confirmed_count}/{len(TRACKABLE_FIELDS)} fields confirmed)\n")
    lines.append(readiness)
    lines.append("")

    return "\n".join(lines)


def run_reporter(account_id: str) -> Path:
    v2_dir = ACCOUNTS_DIR / account_id / "v2"

    memo_path = v2_dir / "v2_memo.json"
    if not memo_path.exists():
        raise FileNotFoundError(f"v2_memo.json not found at {memo_path}. Run v2_merger.py first.")

    with open(memo_path, "r", encoding="utf-8") as f:
        v2_memo = json.load(f)

    changes_path = v2_dir / "changes.json"
    changes_json = None
    if changes_path.exists():
        with open(changes_path, "r", encoding="utf-8") as f:
            changes_json = json.load(f)

    report_md = generate_report(account_id, v2_memo, changes_json)
    report_path = v2_dir / "unknowns_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"[reporter] Report saved → {report_path}")
    return report_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate unknowns / readiness report for an account.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--account_id", help="Single account identifier (e.g. acct_001)")
    grp.add_argument("--all", action="store_true", help="Process all accounts in outputs/accounts/")
    args = ap.parse_args()

    if args.all:
        account_dirs = [d for d in ACCOUNTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
        for d in account_dirs:
            try:
                run_reporter(d.name)
            except FileNotFoundError as e:
                print(f"[reporter] Skipping {d.name}: {e}")
    else:
        run_reporter(args.account_id)

    print("[reporter] Done.")
