"""
diff_viewer.py — Pretty-print a side-by-side v1 → v2 diff for any account.

Shows exactly what changed, what was added, what's still unknown,
and what conflicts were resolved during the onboarding merge.

Usage:
    python diff_viewer.py --account_id acct_001
    python diff_viewer.py --all               # diff all accounts
    python diff_viewer.py --account_id acct_001 --export   # save as diff_report.md
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

ACCOUNTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"

# ─── Terminal colors ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

CHANGE_ICONS = {
    "added":            f"{GREEN}+ ADDED{RESET}",
    "conflict_resolved":f"{YELLOW}~ UPDATED{RESET}",
    "confirmed":        f"{CYAN}✓ CONFIRMED{RESET}",
    "unchanged":        f"{DIM}  SAME{RESET}",
}

FIELD_LABELS = {
    "company_name":               "Company Name",
    "business_hours":             "Business Hours",
    "timezone":                   "Timezone",
    "office_address":             "Office Address",
    "services_supported":         "Services Supported",
    "emergency_definition":       "Emergency Definition",
    "emergency_routing_rules":    "Emergency Routing Rules",
    "non_emergency_routing_rules":"Non-Emergency Routing",
    "call_transfer_rules":        "Call Transfer Rules",
    "integration_constraints":    "Integration Constraints",
    "after_hours_flow_summary":   "After Hours Flow",
    "office_hours_flow_summary":  "Office Hours Flow",
}

ALL_FIELDS = list(FIELD_LABELS.keys())


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _val(memo: dict, field: str):
    """Get value from memo (handles flat company_name and nested fields)."""
    if field == "company_name":
        return memo.get("company_name")
    entry = memo.get(field, {})
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _status(memo: dict, field: str) -> str:
    if field == "company_name":
        v = memo.get("company_name")
        return "confirmed" if v else "unknown"
    entry = memo.get(field, {})
    if isinstance(entry, dict):
        return entry.get("status", "unknown")
    return "confirmed" if entry else "unknown"


def _fmt_val(val, max_len: int = 70) -> str:
    """Format a value for display."""
    if val is None or val == [] or val == {} or val == "":
        return f"{RED}null{RESET}"
    s = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _fmt_val_plain(val, max_len: int = 70) -> str:
    """Format a value without ANSI codes (for markdown export)."""
    if val is None or val == [] or val == {} or val == "":
        return "null"
    s = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


# ─── Core diff logic ──────────────────────────────────────────────────────────

def compute_diff(v1_memo: dict, v2_memo: dict, changes_json: dict | None) -> list[dict]:
    """
    Produce a list of diff rows, one per field.
    Each row: { field, label, v1_val, v2_val, v1_status, v2_status, change_type }
    """
    # Build a fast lookup for changes.json entries
    changes_map = {}
    if changes_json:
        for c in changes_json.get("changes", []):
            changes_map[c["field"]] = c
        for c in changes_json.get("conflicts_resolved", []):
            changes_map[c["field"]] = c

    rows = []
    for field in ALL_FIELDS:
        v1_val    = _val(v1_memo, field)
        v2_val    = _val(v2_memo, field)
        v1_status = _status(v1_memo, field)
        v2_status = _status(v2_memo, field)

        # Determine change type
        if field in changes_map:
            change_type = changes_map[field].get("change_type", "added")
        elif v1_val is None and v2_val is None:
            change_type = "unknown"
        elif v1_val == v2_val and v1_status != v2_status:
            change_type = "confirmed"
        elif v1_val == v2_val:
            change_type = "unchanged"
        elif v1_val is None and v2_val is not None:
            change_type = "added"
        else:
            change_type = "conflict_resolved"

        rows.append({
            "field":       field,
            "label":       FIELD_LABELS.get(field, field),
            "v1_val":      v1_val,
            "v2_val":      v2_val,
            "v1_status":   v1_status,
            "v2_status":   v2_status,
            "change_type": change_type,
        })

    return rows


# ─── Terminal renderer ────────────────────────────────────────────────────────

def render_terminal(account_id: str, v1_memo: dict, v2_memo: dict, rows: list[dict]) -> None:
    company = v2_memo.get("company_name") or v1_memo.get("company_name") or account_id
    v1_gen  = v1_memo.get("generated_at", "?")
    v2_gen  = v2_memo.get("generated_at", "?")

    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  📋 DIFF: {company} ({account_id}){RESET}")
    print(f"{DIM}  v1 generated: {v1_gen}{RESET}")
    print(f"{DIM}  v2 generated: {v2_gen}{RESET}")
    print(f"{BOLD}{'═'*70}{RESET}\n")

    # Group by change type
    added      = [r for r in rows if r["change_type"] == "added"]
    updated    = [r for r in rows if r["change_type"] == "conflict_resolved"]
    confirmed  = [r for r in rows if r["change_type"] == "confirmed"]
    unchanged  = [r for r in rows if r["change_type"] == "unchanged"]
    still_null = [r for r in rows if r["change_type"] == "unknown"]

    sections = [
        (f"{GREEN}+ FIELDS ADDED FROM ONBOARDING ({len(added)}){RESET}",  added),
        (f"{YELLOW}~ CONFLICTS RESOLVED ({len(updated)}){RESET}",          updated),
        (f"{CYAN}✓ STATUS UPGRADED TO CONFIRMED ({len(confirmed)}){RESET}", confirmed),
        (f"{DIM}  UNCHANGED ({len(unchanged)}){RESET}",                    unchanged),
        (f"{RED}✗ STILL UNKNOWN ({len(still_null)}){RESET}",               still_null),
    ]

    for section_title, section_rows in sections:
        if not section_rows:
            continue
        print(f"  {section_title}")
        print(f"  {'─'*66}")
        for r in section_rows:
            label = r["label"]
            if r["change_type"] in ("added", "conflict_resolved"):
                print(f"    {BOLD}{label}{RESET}")
                print(f"      v1: {_fmt_val(r['v1_val'])}  [{r['v1_status']}]")
                print(f"      v2: {_fmt_val(r['v2_val'])}  [{r['v2_status']}]")
            elif r["change_type"] == "unknown":
                print(f"    {RED}{label}{RESET}  → still null after onboarding")
            elif r["change_type"] == "confirmed":
                print(f"    {label}  {DIM}(same value, status: unknown → confirmed){RESET}")
            else:
                print(f"    {DIM}{label}  [{r['v2_status']}]{RESET}")
        print()

    # Summary line
    print(f"  {BOLD}Summary:{RESET} +{len(added)} added  ~{len(updated)} updated  ✓{len(confirmed)} confirmed  ✗{len(still_null)} still unknown\n")


# ─── Markdown export renderer ─────────────────────────────────────────────────

def render_markdown(account_id: str, v1_memo: dict, v2_memo: dict, rows: list[dict]) -> str:
    company = v2_memo.get("company_name") or v1_memo.get("company_name") or account_id
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# v1 → v2 Diff — {company} (`{account_id}`)",
        f"\n_Generated: {now}_\n",
        "| Field | v1 Value | v1 Status | v2 Value | v2 Status | Change |",
        "|-------|----------|-----------|----------|-----------|--------|",
    ]

    icon_map = {
        "added":             "✅ added",
        "conflict_resolved": "⚠️ updated",
        "confirmed":         "🔵 confirmed",
        "unchanged":         "— same",
        "unknown":           "❌ unknown",
    }

    for r in rows:
        v1_display = _fmt_val_plain(r["v1_val"])
        v2_display = _fmt_val_plain(r["v2_val"])
        change = icon_map.get(r["change_type"], r["change_type"])
        lines.append(
            f"| **{r['label']}** | `{v1_display}` | {r['v1_status']} "
            f"| `{v2_display}` | {r['v2_status']} | {change} |"
        )

    # Stats
    added   = sum(1 for r in rows if r["change_type"] == "added")
    updated = sum(1 for r in rows if r["change_type"] == "conflict_resolved")
    confirm = sum(1 for r in rows if r["change_type"] == "confirmed")
    unknown = sum(1 for r in rows if r["change_type"] == "unknown")

    lines += [
        "",
        "## Summary",
        f"- ✅ **{added}** fields added from onboarding",
        f"- ⚠️ **{updated}** conflicts resolved (onboarding value preferred)",
        f"- 🔵 **{confirm}** fields status upgraded to confirmed",
        f"- ❌ **{unknown}** fields still unknown after onboarding",
    ]

    return "\n".join(lines)


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_diff(account_id: str, export: bool = False) -> None:
    base = ACCOUNTS_DIR / account_id
    v1_path = base / "v1" / "v1_memo.json"
    v2_path = base / "v2" / "v2_memo.json"
    ch_path = base / "v2" / "changes.json"

    if not v1_path.exists():
        print(f"[diff_viewer] ⚠️  {account_id}: v1_memo.json not found — skipping")
        return
    if not v2_path.exists():
        print(f"[diff_viewer] ⚠️  {account_id}: v2_memo.json not found — skipping")
        return

    v1_memo     = _load(v1_path)
    v2_memo     = _load(v2_path)
    changes_json = _load(ch_path) if ch_path.exists() else None

    rows = compute_diff(v1_memo, v2_memo, changes_json)
    render_terminal(account_id, v1_memo, v2_memo, rows)

    if export:
        md = render_markdown(account_id, v1_memo, v2_memo, rows)
        out_path = base / "v2" / "diff_report.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"[diff_viewer] Saved → {out_path}")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pretty-print v1 → v2 diff for Clara accounts.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--account_id", help="Single account ID (e.g. acct_001)")
    grp.add_argument("--all", action="store_true", help="Diff all accounts")
    ap.add_argument(
        "--export",
        action="store_true",
        help="Also save diff as outputs/accounts/<id>/v2/diff_report.md",
    )
    args = ap.parse_args()

    if args.all:
        dirs = sorted(d for d in ACCOUNTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))
        if not dirs:
            print("[diff_viewer] No accounts found. Run the pipeline first.")
        for d in dirs:
            run_diff(d.name, export=args.export)
    else:
        run_diff(args.account_id, export=args.export)
