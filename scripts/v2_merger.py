"""
v2_merger.py — Apply onboarding data on top of v1 spec to produce v2.

Usage:
    python v2_merger.py --account_id acct_001 \
                        --onboarding data/cases/acct_001_onboarding.txt \
                        --source onboarding_transcript

Reads:  outputs/accounts/acct_001/v1/v1_memo.json
        outputs/accounts/acct_001/v1/parsed_facts.json  (raw v1 parsed data)
Writes: outputs/accounts/acct_001/v2/v2_memo.json
        outputs/accounts/acct_001/v2/v2_agent_spec.json
        outputs/accounts/acct_001/v2/v2_prompt.txt
        outputs/accounts/acct_001/v2/changes.json
        changelog/<account_id>_changelog.md
"""

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running from scripts/ directly
sys.path.insert(0, str(Path(__file__).parent))
from prompt_generator import generate_prompt


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

MERGEABLE_FIELDS = [
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


def _get_field_value(spec: dict, field: str):
    """Safely retrieve a field's value, handling both flat and nested schema fields."""
    entry = spec.get(field)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry  # flat field like company_name


def _set_field(spec: dict, field: str, new_value, source: str):
    """Overwrite a field's value and metadata in the spec."""
    if field == "company_name":
        spec[field] = new_value
    elif field in spec and isinstance(spec[field], dict):
        spec[field]["value"] = new_value
        spec[field]["status"] = "confirmed"
        spec[field]["source"] = source
    else:
        spec[field] = {"value": new_value, "status": "confirmed", "source": source}


def _values_differ(a, b) -> bool:
    """Deep-equality check that handles None vs empty structures."""
    if a is None and (b is None or b == [] or b == {}):
        return False
    if b is None and (a is None or a == [] or a == {}):
        return False
    return a != b


def merge_specs(v1_memo: dict, onboarding_data: dict, source: str) -> tuple[dict, list, list, list]:
    """
    Merge onboarding_data into v1_memo.
    Returns: (v2_memo, changes_list, conflicts_resolved, still_unknown)
    """
    v2 = copy.deepcopy(v1_memo)
    v2["version"] = "v2"
    v2["generated_at"] = datetime.utcnow().isoformat() + "Z"
    v2["generated_from"] = source

    changes = []
    conflicts = []

    onboarding_fields = {
        k: v for k, v in onboarding_data.items() if k in MERGEABLE_FIELDS
    }

    for field in MERGEABLE_FIELDS:
        onboarding_entry = onboarding_fields.get(field)
        if onboarding_entry is None:
            continue  # onboarding didn't mention this field — leave v1 value

        # Get the new value from onboarding parsed facts
        if isinstance(onboarding_entry, dict):
            ob_value = onboarding_entry.get("value")
            ob_status = onboarding_entry.get("status", "confirmed")
        else:
            ob_value = onboarding_entry
            ob_status = "confirmed"

        # Skip if onboarding also returned null
        if ob_value is None or ob_value == [] or ob_value == {}:
            continue

        v1_value = _get_field_value(v1_memo, field)

        if v1_value is None or v1_value == [] or v1_value == {}:
            # Case 1: field was unknown in v1 → fill it in
            _set_field(v2, field, ob_value, source)
            changes.append(
                {
                    "field": field,
                    "v1_value": v1_value,
                    "v2_value": ob_value,
                    "change_type": "added",
                    "source": source,
                }
            )
        elif _values_differ(v1_value, ob_value):
            # Case 2: conflict — onboarding always wins
            _set_field(v2, field, ob_value, source)
            conflicts.append(
                {
                    "field": field,
                    "v1_value": v1_value,
                    "v2_value": ob_value,
                    "change_type": "conflict_resolved",
                    "source": source,
                    "resolution": "onboarding_value_preferred",
                }
            )
            changes.append(conflicts[-1])
        else:
            # Case 3: same value — upgrade status to confirmed
            if field in v2 and isinstance(v2[field], dict):
                v2[field]["status"] = "confirmed"
                v2[field]["source"] = source

    # Identify still-unknown fields
    still_unknown = []
    for field in MERGEABLE_FIELDS:
        val = _get_field_value(v2, field)
        if val is None or val == [] or val == {}:
            still_unknown.append(field)

    # Merge questions from onboarding
    ob_questions = onboarding_data.get("questions_or_unknowns", [])
    existing_qs = set(v2.get("questions_or_unknowns", []))
    for q in ob_questions:
        if q not in existing_qs:
            v2["questions_or_unknowns"].append(q)

    # Append to change_log inside memo
    now = datetime.utcnow().isoformat() + "Z"
    v2.setdefault("change_log", []).append(
        {
            "timestamp": now,
            "source": source,
            "changes_count": len(changes),
            "conflicts_count": len(conflicts),
        }
    )

    return v2, changes, conflicts, still_unknown


def build_agent_spec(memo: dict) -> dict:
    """Mirror of v1_generator.build_agent_spec — kept here to avoid circular imports."""
    def _val(field):
        entry = memo.get(field, {})
        if isinstance(entry, dict):
            return entry.get("value")
        return entry

    return {
        "account_id": memo["account_id"],
        "version": memo["version"],
        "company_name": memo.get("company_name"),
        "business_hours": {
            "value": _val("business_hours"),
            "status": memo.get("business_hours", {}).get("status", "unknown"),
        },
        "timezone": _val("timezone"),
        "office_address": _val("office_address"),
        "services_supported": _val("services_supported") or [],
        "emergency_definition": _val("emergency_definition") or [],
        "emergency_routing_rules": _val("emergency_routing_rules") or {},
        "non_emergency_routing_rules": _val("non_emergency_routing_rules") or {},
        "call_transfer_rules": _val("call_transfer_rules") or {},
        "integration_constraints": _val("integration_constraints") or [],
        "after_hours_flow_summary": _val("after_hours_flow_summary"),
        "office_hours_flow_summary": _val("office_hours_flow_summary"),
        "questions_or_unknowns": memo.get("questions_or_unknowns", []),
        "notes": memo.get("notes", ""),
    }


def write_changes_json(
    account_id: str,
    v1_memo: dict,
    changes: list,
    conflicts: list,
    still_unknown: list,
    out_dir: Path,
) -> Path:
    payload = {
        "account_id": account_id,
        "v1_generated": v1_memo.get("generated_at"),
        "v2_generated": datetime.utcnow().isoformat() + "Z",
        "changes": [c for c in changes if c.get("change_type") == "added"],
        "conflicts_resolved": conflicts,
        "still_unknown": still_unknown,
    }
    p = out_dir / "changes.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[v2_merger] Saved changes.json → {p}")
    return p


def write_changelog_md(account_id: str, changes: list, conflicts: list, still_unknown: list) -> Path:
    cl_dir = Path(__file__).parent.parent / "changelog"
    cl_dir.mkdir(parents=True, exist_ok=True)
    cl_path = cl_dir / f"{account_id}_changelog.md"

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Changelog — {account_id}",
        f"\n_Last updated: {now}_\n",
        "## v1 → v2 Changes",
    ]

    added = [c for c in changes if c.get("change_type") == "added"]
    resolved = conflicts

    if added:
        lines.append("\n### Fields Added from Onboarding")
        for c in added:
            lines.append(f"- **{c['field']}**: `null` → `{c['v2_value']}` _(source: {c['source']})_")

    if resolved:
        lines.append("\n### Conflicts Resolved (onboarding value preferred)")
        for c in resolved:
            lines.append(
                f"- **{c['field']}**: `{c['v1_value']}` → `{c['v2_value']}` _(source: {c['source']})_"
            )

    if still_unknown:
        lines.append("\n### Still Unknown After Onboarding")
        for f in still_unknown:
            lines.append(f"- `{f}`")

    cl_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[v2_merger] Saved changelog → {cl_path}")
    return cl_path


def run_v2_merger(account_id: str, onboarding_transcript: Path, source: str) -> Path:
    base_v1 = Path(__file__).parent.parent / "outputs" / "accounts" / account_id / "v1"
    base_v2 = Path(__file__).parent.parent / "outputs" / "accounts" / account_id / "v2"
    base_v2.mkdir(parents=True, exist_ok=True)

    # Load v1 memo
    v1_memo_path = base_v1 / "v1_memo.json"
    if not v1_memo_path.exists():
        raise FileNotFoundError(f"v1_memo.json not found. Run v1_generator.py first.")
    with open(v1_memo_path, "r", encoding="utf-8") as f:
        v1_memo = json.load(f)

    # Parse onboarding transcript via parser.py (import directly)
    sys.path.insert(0, str(Path(__file__).parent))
    from parser import run_parser, save_output

    print(f"[v2_merger] Parsing onboarding source: {onboarding_transcript}")
    onboarding_parsed = run_parser(onboarding_transcript, account_id, source)
    # Also save raw parsed onboarding facts
    save_output(onboarding_parsed, account_id, "v2")

    onboarding_data = onboarding_parsed.get("data", {})

    # Merge
    print(f"[v2_merger] Merging v1 + onboarding for {account_id} …")
    v2_memo, changes, conflicts, still_unknown = merge_specs(v1_memo, onboarding_data, source)

    # Build agent spec
    agent_spec = build_agent_spec(v2_memo)

    # Write outputs
    memo_path = base_v2 / "v2_memo.json"
    with open(memo_path, "w", encoding="utf-8") as f:
        json.dump(v2_memo, f, indent=2)
    print(f"[v2_merger] Saved v2_memo.json → {memo_path}")

    spec_path = base_v2 / "v2_agent_spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(agent_spec, f, indent=2)
    print(f"[v2_merger] Saved v2_agent_spec.json → {spec_path}")

    prompt_text = generate_prompt(agent_spec)
    prompt_path = base_v2 / "v2_prompt.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    print(f"[v2_merger] Saved v2_prompt.txt → {prompt_path}")

    write_changes_json(account_id, v1_memo, changes, conflicts, still_unknown, base_v2)
    write_changelog_md(account_id, changes, conflicts, still_unknown)

    print(
        f"[v2_merger] Complete — {len(changes)} change(s), {len(conflicts)} conflict(s) resolved, "
        f"{len(still_unknown)} field(s) still unknown."
    )
    return base_v2


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Merge onboarding data into v1 spec to generate v2.")
    ap.add_argument("--account_id", required=True, help="Account identifier (e.g. acct_001)")
    ap.add_argument("--onboarding", required=True, help="Path to the onboarding transcript/form .txt file")
    ap.add_argument(
        "--source",
        default="onboarding_transcript",
        choices=["onboarding_transcript", "onboarding_form"],
        help="Source type of the onboarding data",
    )
    args = ap.parse_args()

    run_v2_merger(args.account_id, Path(args.onboarding), args.source)
    print("[v2_merger] Done.")
