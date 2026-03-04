"""
v1_generator.py — Build the v1 account spec from parsed transcript facts.

Usage:
    python v1_generator.py --account_id acct_001

Reads:  outputs/accounts/acct_001/v1/parsed_facts.json
Writes: outputs/accounts/acct_001/v1/v1_memo.json
        outputs/accounts/acct_001/v1/v1_agent_spec.json
        outputs/accounts/acct_001/v1/v1_prompt.txt
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from prompt_generator import generate_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unknown_questions(spec: dict) -> list[str]:
    """Auto-generate questions for every field that is still null/empty."""
    question_map = {
        "business_hours": "What are the exact business hours for each day of the week?",
        "timezone": "What timezone does the office operate in?",
        "office_address": "What is the physical office address?",
        "services_supported": "What services does the company support via phone?",
        "emergency_definition": "How does the company define an emergency call?",
        "emergency_routing_rules.primary": "Who is the primary on-call contact for emergencies (name + phone)?",
        "emergency_routing_rules.fallback": "What is the fallback action if the primary emergency contact is unreachable?",
        "call_transfer_rules.timeout_seconds": "How long (in seconds) should Clara wait before declaring a transfer failed?",
        "call_transfer_rules.retries": "How many transfer retry attempts should Clara make?",
        "call_transfer_rules.fail_action": "What should Clara do if all transfer attempts fail?",
        "non_emergency_routing_rules": "How should non-emergency after-hours calls be routed?",
        "integration_constraints": "Are there any CRM, ticketing, or integration constraints to be aware of?",
    }

    questions = list(spec.get("questions_or_unknowns", []))

    for key, question in question_map.items():
        if "." in key:
            field, sub = key.split(".", 1)
            val = spec.get(field, {}).get("value") or {}
            if isinstance(val, dict) and val.get(sub) is None:
                if question not in questions:
                    questions.append(question)
        else:
            field_data = spec.get(key, {})
            if isinstance(field_data, dict):
                val = field_data.get("value")
                status = field_data.get("status", "unknown")
                if (val is None or val == [] or val == {}) and status == "unknown":
                    if question not in questions:
                        questions.append(question)

    return questions


def build_v1_spec(parsed: dict) -> dict:
    """Maps parsed facts into the full account memo schema."""
    data = parsed.get("data", {})
    account_id = parsed.get("account_id", "unknown")
    source = parsed.get("source", "demo_transcript")
    generated_at = datetime.utcnow().isoformat() + "Z"

    spec = {
        "account_id": account_id,
        "version": "v1",
        "generated_from": source,
        "generated_at": generated_at,
        "company_name": data.get("company_name"),
        "business_hours": data.get("business_hours", {"value": None, "status": "unknown", "source": None}),
        "timezone": data.get("timezone", {"value": None, "status": "unknown", "source": None}),
        "office_address": data.get("office_address", {"value": None, "status": "unknown", "source": None}),
        "services_supported": data.get("services_supported", {"value": [], "status": "unknown", "source": None}),
        "emergency_definition": data.get("emergency_definition", {"value": [], "status": "unknown", "source": None}),
        "emergency_routing_rules": data.get(
            "emergency_routing_rules",
            {
                "value": {
                    "primary": None,
                    "order": [],
                    "fallback": None,
                    "collect_before_transfer": ["name", "phone", "address"],
                },
                "status": "unknown",
                "source": None,
            },
        ),
        "non_emergency_routing_rules": data.get(
            "non_emergency_routing_rules", {"value": {}, "status": "unknown", "source": None}
        ),
        "call_transfer_rules": data.get(
            "call_transfer_rules",
            {
                "value": {"timeout_seconds": None, "retries": None, "fail_action": None},
                "status": "unknown",
                "source": None,
            },
        ),
        "integration_constraints": data.get(
            "integration_constraints", {"value": [], "status": "unknown", "source": None}
        ),
        "after_hours_flow_summary": data.get(
            "after_hours_flow_summary", {"value": None, "status": "unknown", "source": None}
        ),
        "office_hours_flow_summary": data.get(
            "office_hours_flow_summary", {"value": None, "status": "unknown", "source": None}
        ),
        "notes": data.get("notes", ""),
        "change_log": [],
    }

    # Auto-build questions list
    spec["questions_or_unknowns"] = _unknown_questions(spec)

    return spec


def build_agent_spec(memo: dict) -> dict:
    """Flatten memo into a simpler key→value dict for the Retell agent."""
    bh = memo.get("business_hours", {}).get("value")
    tz = memo.get("timezone", {}).get("value")
    addr = memo.get("office_address", {}).get("value")
    services = memo.get("services_supported", {}).get("value", [])
    emer_def = memo.get("emergency_definition", {}).get("value", [])
    emer_rules = memo.get("emergency_routing_rules", {}).get("value", {})
    non_emer = memo.get("non_emergency_routing_rules", {}).get("value", {})
    transfer = memo.get("call_transfer_rules", {}).get("value", {})
    constraints = memo.get("integration_constraints", {}).get("value", [])
    after_hours = memo.get("after_hours_flow_summary", {}).get("value")
    office_hours = memo.get("office_hours_flow_summary", {}).get("value")

    return {
        "account_id": memo["account_id"],
        "version": memo["version"],
        "company_name": memo.get("company_name"),
        "business_hours": {"value": bh, "status": memo.get("business_hours", {}).get("status", "unknown")},
        "timezone": tz,
        "office_address": addr,
        "services_supported": services,
        "emergency_definition": emer_def,
        "emergency_routing_rules": emer_rules,
        "non_emergency_routing_rules": non_emer,
        "call_transfer_rules": transfer,
        "integration_constraints": constraints,
        "after_hours_flow_summary": after_hours,
        "office_hours_flow_summary": office_hours,
        "questions_or_unknowns": memo.get("questions_or_unknowns", []),
        "notes": memo.get("notes", ""),
    }


def run_v1_generator(account_id: str) -> Path:
    base = Path(__file__).parent.parent / "outputs" / "accounts" / account_id / "v1"

    parsed_path = base / "parsed_facts.json"
    if not parsed_path.exists():
        raise FileNotFoundError(f"parsed_facts.json not found at {parsed_path}. Run parser.py first.")

    with open(parsed_path, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    print(f"[v1_generator] Building v1 spec for {account_id} …")
    memo = build_v1_spec(parsed)
    agent_spec = build_agent_spec(memo)

    # Write memo
    memo_path = base / "v1_memo.json"
    with open(memo_path, "w", encoding="utf-8") as f:
        json.dump(memo, f, indent=2)
    print(f"[v1_generator] Saved v1_memo.json → {memo_path}")

    # Write agent spec
    spec_path = base / "v1_agent_spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(agent_spec, f, indent=2)
    print(f"[v1_generator] Saved v1_agent_spec.json → {spec_path}")

    # Generate prompt
    prompt_text = generate_prompt(agent_spec)
    prompt_path = base / "v1_prompt.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    print(f"[v1_generator] Saved v1_prompt.txt → {prompt_path}")

    return base


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate v1 account spec from parsed transcript facts.")
    ap.add_argument("--account_id", required=True, help="Account identifier (e.g. acct_001)")
    args = ap.parse_args()

    run_v1_generator(args.account_id)
    print("[v1_generator] Done.")
