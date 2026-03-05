"""
validate.py — QA check before importing a Clara agent spec into Retell.

Checks:
  1. No [UNKNOWN] markers remain in the prompt
  2. All critical fields are non-null in the agent spec
  3. Business hours are properly structured
  4. Emergency routing has a primary contact
  5. Call transfer rules have a timeout defined
  6. Outputs a clear PASS / FAIL report

Usage:
    python validate.py --account_id acct_001 --version v2
    python validate.py --all --version v2          # validate all accounts
    python validate.py --account_id acct_001 --version v1  # check v1 too
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

ACCOUNTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"

UNKNOWN_MARKER = "[UNKNOWN — needs confirmation]"

# ─────────────────────────────────────────────────────────────────────────────
# Field criticality levels
# CRITICAL  → agent CANNOT work without this — hard FAIL
# WARNING   → agent works but is degraded — soft FAIL
# INFO      → nice to have — just logged
# ─────────────────────────────────────────────────────────────────────────────
FIELD_RULES = {
    "company_name":              {"level": "CRITICAL", "label": "Company Name"},
    "business_hours":            {"level": "CRITICAL", "label": "Business Hours"},
    "timezone":                  {"level": "WARNING",  "label": "Timezone"},
    "office_address":            {"level": "INFO",     "label": "Office Address"},
    "services_supported":        {"level": "WARNING",  "label": "Services Supported"},
    "emergency_definition":      {"level": "CRITICAL", "label": "Emergency Definition"},
    "emergency_routing_rules":   {"level": "CRITICAL", "label": "Emergency Routing Rules"},
    "non_emergency_routing_rules":{"level": "WARNING", "label": "Non-Emergency Routing"},
    "call_transfer_rules":       {"level": "WARNING",  "label": "Call Transfer Rules"},
    "integration_constraints":   {"level": "INFO",     "label": "Integration Constraints"},
    "after_hours_flow_summary":  {"level": "INFO",     "label": "After Hours Flow Summary"},
    "office_hours_flow_summary": {"level": "INFO",     "label": "Office Hours Flow Summary"},
}

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_empty(value) -> bool:
    return value is None or value == [] or value == {} or value == ""


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _get_val(spec: dict, field: str):
    """Get value from agent spec (handles both flat and nested)."""
    entry = spec.get(field)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


# ─────────────────────────────────────────────────────────────────────────────
# Check 1 — No [UNKNOWN] markers in prompt
# ─────────────────────────────────────────────────────────────────────────────

def check_unknown_markers(prompt_text: str) -> list[dict]:
    issues = []
    lines = prompt_text.splitlines()
    for i, line in enumerate(lines, 1):
        if UNKNOWN_MARKER in line:
            issues.append({
                "check": "unknown_marker",
                "level": "CRITICAL",
                "line": i,
                "content": line.strip(),
                "message": f"Line {i}: Prompt contains [UNKNOWN] marker → must be replaced before deploying",
            })
    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Check 2 — Critical / Warning / Info field presence
# ─────────────────────────────────────────────────────────────────────────────

def check_field_presence(spec: dict) -> list[dict]:
    issues = []
    for field, rule in FIELD_RULES.items():
        val = _get_val(spec, field)
        if _is_empty(val):
            issues.append({
                "check": "field_presence",
                "level": rule["level"],
                "field": field,
                "message": f"{rule['label']} is missing — status: {rule['level']}",
            })
    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Check 3 — Business hours structure
# ─────────────────────────────────────────────────────────────────────────────

def check_business_hours(spec: dict) -> list[dict]:
    issues = []
    bh_entry = spec.get("business_hours", {})
    bh_val = bh_entry.get("value") if isinstance(bh_entry, dict) else bh_entry

    if _is_empty(bh_val):
        return issues  # already caught by field_presence check

    if not isinstance(bh_val, dict):
        issues.append({
            "check": "business_hours_format",
            "level": "CRITICAL",
            "message": "business_hours.value must be a dict of day → {open, close}",
        })
        return issues

    # Check at least Monday–Friday have hours
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    covered = 0
    for day in weekdays:
        day_info = bh_val.get(day, {})
        if day_info and day_info.get("open") and day_info.get("close"):
            covered += 1

    if covered == 0:
        issues.append({
            "check": "business_hours_weekdays",
            "level": "CRITICAL",
            "message": "No weekday (Mon–Fri) hours found in business_hours",
        })
    elif covered < 5:
        issues.append({
            "check": "business_hours_weekdays",
            "level": "WARNING",
            "message": f"Only {covered}/5 weekdays have defined hours — verify intentional",
        })

    # Check time format HH:MM
    time_pattern = re.compile(r"^\d{2}:\d{2}$")
    for day in DAYS:
        day_info = bh_val.get(day, {})
        if not day_info:
            continue
        for key in ["open", "close"]:
            t = day_info.get(key)
            if t and not time_pattern.match(str(t)):
                issues.append({
                    "check": "business_hours_format",
                    "level": "WARNING",
                    "message": f"business_hours.{day}.{key} = '{t}' — expected HH:MM format",
                })

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Check 4 — Emergency routing primary contact
# ─────────────────────────────────────────────────────────────────────────────

def check_emergency_routing(spec: dict) -> list[dict]:
    issues = []
    emer = _get_val(spec, "emergency_routing_rules")

    if _is_empty(emer):
        return issues  # caught by field_presence

    if not isinstance(emer, dict):
        issues.append({
            "check": "emergency_routing",
            "level": "CRITICAL",
            "message": "emergency_routing_rules.value must be a dict",
        })
        return issues

    if _is_empty(emer.get("primary")):
        issues.append({
            "check": "emergency_routing_primary",
            "level": "CRITICAL",
            "message": "emergency_routing_rules.primary is null — who does Clara call first for emergencies?",
        })

    if _is_empty(emer.get("fallback")):
        issues.append({
            "check": "emergency_routing_fallback",
            "level": "WARNING",
            "message": "emergency_routing_rules.fallback is null — no fallback if primary is unreachable",
        })

    collect = emer.get("collect_before_transfer", [])
    if "name" not in collect or "phone" not in collect:
        issues.append({
            "check": "emergency_collect",
            "level": "WARNING",
            "message": f"collect_before_transfer = {collect} — recommended to include at least 'name' and 'phone'",
        })

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Check 5 — Call transfer rules
# ─────────────────────────────────────────────────────────────────────────────

def check_transfer_rules(spec: dict) -> list[dict]:
    issues = []
    tr = _get_val(spec, "call_transfer_rules")

    if _is_empty(tr):
        return issues

    if not isinstance(tr, dict):
        return issues

    if tr.get("timeout_seconds") is None:
        issues.append({
            "check": "transfer_timeout",
            "level": "WARNING",
            "message": "call_transfer_rules.timeout_seconds is null — Clara won't know when to give up on a transfer",
        })

    if tr.get("fail_action") is None:
        issues.append({
            "check": "transfer_fail_action",
            "level": "WARNING",
            "message": "call_transfer_rules.fail_action is null — Clara won't know what to say when transfer fails",
        })

    # Sanity check: timeout should be between 10 and 120 seconds
    timeout = tr.get("timeout_seconds")
    if timeout is not None:
        try:
            t = int(timeout)
            if t < 10:
                issues.append({
                    "check": "transfer_timeout_sanity",
                    "level": "WARNING",
                    "message": f"timeout_seconds = {t}s — very short, caller may hang up before connecting",
                })
            elif t > 120:
                issues.append({
                    "check": "transfer_timeout_sanity",
                    "level": "INFO",
                    "message": f"timeout_seconds = {t}s — unusually long, verify this is intentional",
                })
        except (ValueError, TypeError):
            issues.append({
                "check": "transfer_timeout_type",
                "level": "WARNING",
                "message": f"call_transfer_rules.timeout_seconds = '{timeout}' — must be an integer",
            })

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# Aggregator + Report
# ─────────────────────────────────────────────────────────────────────────────

def validate_account(account_id: str, version: str) -> dict:
    """Run all checks for one account. Returns a result dict."""
    base = ACCOUNTS_DIR / account_id / version
    spec_path = base / f"{version}_agent_spec.json"
    prompt_path = base / f"{version}_prompt.txt"

    result = {
        "account_id": account_id,
        "version": version,
        "validated_at": datetime.utcnow().isoformat() + "Z",
        "spec_path": str(spec_path),
        "prompt_path": str(prompt_path),
        "issues": [],
        "verdict": None,
    }

    # File existence checks
    if not spec_path.exists():
        result["issues"].append({
            "check": "file_missing",
            "level": "CRITICAL",
            "message": f"{version}_agent_spec.json not found at {spec_path}. Run the pipeline first.",
        })
        result["verdict"] = "FAIL"
        return result

    if not prompt_path.exists():
        result["issues"].append({
            "check": "file_missing",
            "level": "CRITICAL",
            "message": f"{version}_prompt.txt not found. Run the pipeline first.",
        })

    spec = _load_json(spec_path)
    prompt_text = _load_text(prompt_path) if prompt_path.exists() else ""

    all_issues = []
    all_issues += check_unknown_markers(prompt_text)
    all_issues += check_field_presence(spec)
    all_issues += check_business_hours(spec)
    all_issues += check_emergency_routing(spec)
    all_issues += check_transfer_rules(spec)

    result["issues"] = all_issues

    # Verdict
    has_critical = any(i["level"] == "CRITICAL" for i in all_issues)
    has_warning  = any(i["level"] == "WARNING"  for i in all_issues)

    if has_critical:
        result["verdict"] = "FAIL"
    elif has_warning:
        result["verdict"] = "WARN"
    else:
        result["verdict"] = "PASS"

    return result


def print_report(result: dict) -> None:
    verdict = result["verdict"]
    icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(verdict, "?")
    account = result["account_id"]
    version = result["version"]

    print(f"\n{'─'*60}")
    print(f"  {icon}  {account} / {version}  →  {verdict}")
    print(f"{'─'*60}")

    issues = result["issues"]
    if not issues:
        print("  No issues found. Clear to import into Retell.")
        return

    for level in ["CRITICAL", "WARNING", "INFO"]:
        lvl_issues = [i for i in issues if i["level"] == level]
        if not lvl_issues:
            continue
        label = {"CRITICAL": "🔴 CRITICAL", "WARNING": "🟡 WARNING", "INFO": "🔵 INFO"}[level]
        print(f"\n  {label} ({len(lvl_issues)})")
        for iss in lvl_issues:
            print(f"    • {iss['message']}")


def print_summary(results: list[dict]) -> None:
    print(f"\n{'═'*60}")
    print("  VALIDATION SUMMARY")
    print(f"{'═'*60}")
    print(f"  {'Account':<14} {'Version':<6} {'Result':<8} {'Issues'}")
    print(f"  {'─'*54}")
    for r in results:
        icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(r["verdict"], "?")
        crits  = sum(1 for i in r["issues"] if i["level"] == "CRITICAL")
        warns  = sum(1 for i in r["issues"] if i["level"] == "WARNING")
        infos  = sum(1 for i in r["issues"] if i["level"] == "INFO")
        detail = f"{crits} critical, {warns} warn, {infos} info" if r["issues"] else "clean"
        print(f"  {r['account_id']:<14} {r['version']:<6} {icon} {r['verdict']:<6} {detail}")
    print(f"{'═'*60}")

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    warned = sum(1 for r in results if r["verdict"] == "WARN")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    print(f"\n  PASS: {passed}  |  WARN: {warned}  |  FAIL: {failed}  |  Total: {len(results)}")

    if failed > 0:
        print("\n  ❌ One or more accounts FAILED — do NOT import into Retell until fixed.")
    elif warned > 0:
        print("\n  ⚠️  Some accounts have warnings — review before going live.")
    else:
        print("\n  ✅ All accounts passed — safe to import into Retell.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Validate Clara agent spec + prompt before Retell import."
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--account_id", help="Single account ID (e.g. acct_001)")
    grp.add_argument("--all", action="store_true", help="Validate all accounts")
    ap.add_argument(
        "--version",
        default="v2",
        choices=["v1", "v2"],
        help="Which version to validate (default: v2)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any WARNING found (not just CRITICAL)",
    )
    args = ap.parse_args()

    results = []

    if args.all:
        account_dirs = sorted(
            [d for d in ACCOUNTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
        )
        if not account_dirs:
            print("[validate] No accounts found in outputs/accounts/. Run the pipeline first.")
            sys.exit(1)
        for d in account_dirs:
            r = validate_account(d.name, args.version)
            print_report(r)
            results.append(r)
    else:
        r = validate_account(args.account_id, args.version)
        print_report(r)
        results.append(r)

    print_summary(results)

    # Exit codes:
    # 0 = all PASS
    # 1 = at least one FAIL (or WARN if --strict)
    has_fail = any(r["verdict"] == "FAIL" for r in results)
    has_warn = any(r["verdict"] == "WARN" for r in results)

    if has_fail or (args.strict and has_warn):
        sys.exit(1)
    sys.exit(0)
