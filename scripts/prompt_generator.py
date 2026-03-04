"""
prompt_generator.py — Generate a full Retell Clara agent prompt from a v1/v2 spec.

Usage (standalone):
    python prompt_generator.py --spec outputs/accounts/acct_001/v1/v1_agent_spec.json \
                                --out outputs/accounts/acct_001/v1/v1_prompt.txt

Can also be imported and called as a library by v1_generator.py and v2_merger.py.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Optional


UNKNOWN = "[UNKNOWN — needs confirmation]"


def _fmt(value: Any, fallback: str = UNKNOWN) -> str:
    """Return a human-readable string for a field value, or UNKNOWN placeholder."""
    if value is None or value == "" or value == [] or value == {}:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else fallback
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def _fmt_hours(hours_value: Optional[dict]) -> str:
    """Format business_hours dict into a readable string."""
    if not hours_value:
        return UNKNOWN
    days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    lines = []
    for day in days_order:
        info = hours_value.get(day)
        if info and info.get("open") and info.get("close"):
            lines.append(f"  {day.capitalize()}: {info['open']} – {info['close']}")
        else:
            lines.append(f"  {day.capitalize()}: closed / {UNKNOWN}")
    return "\n".join(lines) if lines else UNKNOWN


def generate_prompt(spec: dict) -> str:
    """
    Takes an agent_spec dict and produces a full Clara agent prompt string.
    All null/missing fields are replaced with [UNKNOWN — needs confirmation].
    """
    company = _fmt(spec.get("company_name"))
    tz = _fmt(spec.get("timezone", {}).get("value"))
    address = _fmt(spec.get("office_address", {}).get("value"))
    services = _fmt(spec.get("services_supported", {}).get("value"))

    bh_raw = spec.get("business_hours", {}).get("value")
    hours_str = _fmt_hours(bh_raw)

    emer_def = _fmt(spec.get("emergency_definition", {}).get("value"))
    emer_rules = spec.get("emergency_routing_rules", {}).get("value") or {}
    emer_primary = _fmt(emer_rules.get("primary"))
    emer_order = _fmt(emer_rules.get("order"))
    emer_fallback = _fmt(emer_rules.get("fallback"))
    collect = _fmt(emer_rules.get("collect_before_transfer", ["name", "phone", "address"]))

    transfer_rules = spec.get("call_transfer_rules", {}).get("value") or {}
    timeout = _fmt(transfer_rules.get("timeout_seconds"))
    retries = _fmt(transfer_rules.get("retries"))
    fail_action = _fmt(transfer_rules.get("fail_action"))

    non_emer = spec.get("non_emergency_routing_rules", {}).get("value") or {}
    non_emer_str = _fmt(non_emer) if non_emer else UNKNOWN

    after_hours = _fmt(spec.get("after_hours_flow_summary", {}).get("value"))
    office_hours = _fmt(spec.get("office_hours_flow_summary", {}).get("value"))

    unknowns = spec.get("questions_or_unknowns", [])
    unknowns_block = ""
    if unknowns:
        unknowns_block = "\n\n## OPEN QUESTIONS (do not improvise — ask caller or escalate)\n"
        for q in unknowns:
            unknowns_block += f"- {q}\n"

    prompt = f"""# Clara Agent Prompt — {company}
# Generated automatically — review all [{UNKNOWN.strip("[]")}] markers before deploying.

## IDENTITY
You are Clara, the intelligent virtual assistant for **{company}**.
You handle inbound calls professionally, routing them correctly based on time of day and caller need.

- Company Address: {address}
- Timezone: {tz}
- Services Offered: {services}

---

## BUSINESS HOURS
{hours_str}

---

## FLOW A — OFFICE HOURS (caller reaches you during business hours)

1. **Greet warmly:**
   "Thank you for calling {company}, this is Clara. How can I help you today?"

2. Ask the purpose of their call.

3. Collect:
   - Caller's full name
   - Best callback number

4. Transfer the call to: **{emer_primary}**
   - Transfer order: {emer_order}

5. If the transfer fails after **{timeout} seconds** ({retries} retries):
   - "I'm sorry, I wasn't able to connect you right now. I want to assure you that someone from our team will call you back within {UNKNOWN}."
   - Offer to take a message.
   - Action on failure: {fail_action}

6. Before ending: "Is there anything else I can help you with?"

7. Close: "Thank you for calling {company}. Have a great day!"

---

## FLOW B — AFTER HOURS (caller reaches you outside business hours)

1. **Greet:**
   "Thank you for calling {company}. You've reached us after hours. This is Clara."

2. Ask the purpose of their call.

3. Ask: **"Is this situation an emergency?"**

   **Emergency triggers include:**
   {emer_def}

---

### B-1: IF EMERGENCY

1. **Immediately collect** (before any transfer attempt):
   {collect}

2. **Attempt transfer to:** {emer_primary}
   - Escalation order: {emer_order}
   - Fallback: {emer_fallback}

3. If transfer succeeds: hand off gracefully.

4. If transfer **fails**:
   "I was unable to reach our on-call team directly. Your information has been recorded
   and someone will contact you immediately. Do not hesitate to call back if your
   situation becomes more urgent."

---

### B-2: IF NON-EMERGENCY

1. Collect:
   - Caller's name
   - Best callback number
   - Brief description of the issue

2. Routing for non-emergency: {non_emer_str}

3. Confirm: "Thank you. Someone from our team will follow up with you during our next
   business hours:\\n{hours_str}"

---

## AFTER EVERY CALL

- "Is there anything else I can help you with?"
- If no: Close warmly and thank them for calling {company}.

---

## ADDITIONAL CONTEXT
- Office Hours Flow: {office_hours}
- After Hours Flow: {after_hours}
{unknowns_block}
"""
    return prompt.strip()


def load_spec(spec_path: Path) -> dict:
    with open(spec_path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate a Clara agent prompt from a spec JSON.")
    ap.add_argument("--spec", required=True, help="Path to v1_agent_spec.json or v2_agent_spec.json")
    ap.add_argument("--out", required=True, help="Output path for the .txt prompt file")
    args = ap.parse_args()

    spec = load_spec(Path(args.spec))
    prompt_text = generate_prompt(spec)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt_text, encoding="utf-8")
    print(f"[prompt_generator] Prompt written → {out_path}")
