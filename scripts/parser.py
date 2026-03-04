"""
parser.py — Extract structured facts from a call transcript using Gemini API.

Usage:
    python parser.py --transcript data/cases/acct_001_demo.txt --account_id acct_001 --source demo_transcript
"""

import argparse
import json
import os
import sys
import re
import time
from datetime import datetime
from pathlib import Path
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-1.5-flash"
SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "account_memo_schema.json"


EXTRACTION_PROMPT = """You are extracting structured data from a business call transcript.

STRICT RULES:
- Extract ONLY facts that are explicitly stated in the transcript.
- If something is not mentioned, return null for that field.
- NEVER infer, assume, or guess values.
- If a value is vague (e.g. "we usually open around 8"), mark status as "assumed", not "confirmed".
- Return ONLY valid JSON — no commentary, no markdown fences.

Extract the following fields and return JSON exactly matching this structure:

{{
  "company_name": "<string or null>",
  "business_hours": {{
    "value": {{
      "monday":    {{"open": "HH:MM", "close": "HH:MM"}},
      "tuesday":   {{"open": "HH:MM", "close": "HH:MM"}},
      "wednesday": {{"open": "HH:MM", "close": "HH:MM"}},
      "thursday":  {{"open": "HH:MM", "close": "HH:MM"}},
      "friday":    {{"open": "HH:MM", "close": "HH:MM"}},
      "saturday":  {{"open": "HH:MM", "close": "HH:MM"}},
      "sunday":    {{"open": "HH:MM", "close": "HH:MM"}}
    }},
    "status": "confirmed | assumed | unknown",
    "source": "{source}"
  }},
  "timezone": {{"value": "<string or null>", "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "office_address": {{"value": "<string or null>", "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "services_supported": {{"value": ["<list of strings>"], "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "emergency_definition": {{"value": ["<list of strings>"], "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "emergency_routing_rules": {{
    "value": {{
      "primary": "<phone or name or null>",
      "order": ["<list>"],
      "fallback": "<string or null>",
      "collect_before_transfer": ["name", "phone", "address"]
    }},
    "status": "confirmed | assumed | unknown",
    "source": "{source} or null"
  }},
  "non_emergency_routing_rules": {{"value": {{}}, "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "call_transfer_rules": {{
    "value": {{
      "timeout_seconds": <integer or null>,
      "retries": <integer or null>,
      "fail_action": "<string or null>"
    }},
    "status": "confirmed | assumed | unknown",
    "source": "{source} or null"
  }},
  "integration_constraints": {{"value": ["<list of strings>"], "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "after_hours_flow_summary": {{"value": "<string or null>", "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "office_hours_flow_summary": {{"value": "<string or null>", "status": "confirmed | assumed | unknown", "source": "{source} or null"}},
  "questions_or_unknowns": ["<list of open questions as plain strings>"],
  "notes": "<any additional context not covered above>"
}}

TRANSCRIPT:
---
{transcript}
---
"""


def load_transcript(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def call_gemini(prompt: str, retries: int = 3, delay: int = 5) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    for attempt in range(1, retries + 1):
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as exc:
            print(f"[WARN] Attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(delay)
    print("[ERROR] All Gemini API attempts failed.", file=sys.stderr)
    sys.exit(1)


def clean_json_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    raw = raw.strip()
    # Remove ```json ... ``` fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def build_empty_field(source: str) -> dict:
    return {"value": None, "status": "unknown", "source": None}


def merge_with_defaults(extracted: dict, source: str) -> dict:
    """Ensure all schema fields are present even if Gemini missed them."""
    defaults = {
        "company_name": None,
        "business_hours": build_empty_field(source),
        "timezone": build_empty_field(source),
        "office_address": build_empty_field(source),
        "services_supported": {"value": [], "status": "unknown", "source": None},
        "emergency_definition": {"value": [], "status": "unknown", "source": None},
        "emergency_routing_rules": {
            "value": {
                "primary": None,
                "order": [],
                "fallback": None,
                "collect_before_transfer": ["name", "phone", "address"],
            },
            "status": "unknown",
            "source": None,
        },
        "non_emergency_routing_rules": {"value": {}, "status": "unknown", "source": None},
        "call_transfer_rules": {
            "value": {"timeout_seconds": None, "retries": None, "fail_action": None},
            "status": "unknown",
            "source": None,
        },
        "integration_constraints": {"value": [], "status": "unknown", "source": None},
        "after_hours_flow_summary": build_empty_field(source),
        "office_hours_flow_summary": build_empty_field(source),
        "questions_or_unknowns": [],
        "notes": "",
    }
    for key, default_val in defaults.items():
        if key not in extracted:
            extracted[key] = default_val
    return extracted


def run_parser(transcript_path: Path, account_id: str, source: str) -> dict:
    print(f"[parser] Loading transcript: {transcript_path}")
    transcript_text = load_transcript(transcript_path)

    prompt = EXTRACTION_PROMPT.format(transcript=transcript_text, source=source)

    print(f"[parser] Calling Gemini ({GEMINI_MODEL}) …")
    raw_response = call_gemini(prompt)

    print("[parser] Parsing JSON response …")
    extracted = clean_json_response(raw_response)
    extracted = merge_with_defaults(extracted, source)

    # Attach metadata
    result = {
        "account_id": account_id,
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "data": extracted,
    }
    return result


def save_output(result: dict, account_id: str, version: str = "v1") -> Path:
    out_dir = Path(__file__).parent.parent / "outputs" / "accounts" / account_id / version
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "parsed_facts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"[parser] Saved parsed facts → {out_path}")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Extract facts from a call transcript using Gemini.")
    ap.add_argument("--transcript", required=True, help="Path to the transcript .txt file")
    ap.add_argument("--account_id", required=True, help="Account identifier (e.g. acct_001)")
    ap.add_argument(
        "--source",
        default="demo_transcript",
        choices=["demo_transcript", "onboarding_transcript", "onboarding_form"],
        help="Source type of the transcript",
    )
    ap.add_argument("--version", default="v1", choices=["v1", "v2"], help="Output version folder")
    args = ap.parse_args()

    result = run_parser(Path(args.transcript), args.account_id, args.source)
    save_output(result, args.account_id, args.version)
    print("[parser] Done.")
