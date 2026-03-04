"""
run_all.py — Batch runner: executes full Pipeline A + B for all 5 accounts.

Usage:
    cd scripts
    python run_all.py

Environment Variables Required:
    GEMINI_API_KEY  — Your Google Gemini API key

Optional:
    ACCOUNTS        — Comma-separated list of account IDs to process (default: all 5)
                      e.g. ACCOUNTS=acct_001,acct_002 python run_all.py
"""

import os
import sys
import time
from pathlib import Path

# Ensure scripts/ is in path for imports
sys.path.insert(0, str(Path(__file__).parent))

from parser import run_parser, save_output
from v1_generator import run_v1_generator
from v2_merger import run_v2_merger
from reporter import run_reporter

# ──────────────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"

ALL_ACCOUNTS = ["acct_001", "acct_002", "acct_003", "acct_004", "acct_005"]

RESULTS = []  # summary table


def _check_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print(
            "\n[ERROR] GEMINI_API_KEY environment variable not set.\n"
            "Set it with:\n"
            "  Windows PowerShell: $env:GEMINI_API_KEY='your-key'\n"
            "  Linux/macOS:        export GEMINI_API_KEY=your-key\n"
        )
        sys.exit(1)
    return key


def process_account(account_id: str) -> dict:
    """Run the full Pipeline A → B for a single account."""
    result = {
        "account_id": account_id,
        "v1_status": "⏳",
        "v2_status": "⏳",
        "report_status": "⏳",
        "error": None,
    }

    demo_path = CASES_DIR / f"{account_id}_demo.txt"
    onboarding_path = CASES_DIR / f"{account_id}_onboarding.txt"

    print(f"\n{'='*60}")
    print(f"  PROCESSING: {account_id}")
    print(f"{'='*60}")

    # ── Pipeline A: Demo → v1 ─────────────────────────────────────────────────
    try:
        print(f"\n[{account_id}] Pipeline A — Parsing demo transcript …")
        if not demo_path.exists():
            raise FileNotFoundError(f"Demo transcript not found: {demo_path}")

        parsed = run_parser(demo_path, account_id, "demo_transcript")
        save_output(parsed, account_id, "v1")

        print(f"[{account_id}] Running v1 generator …")
        run_v1_generator(account_id)
        result["v1_status"] = "✅"
        print(f"[{account_id}] ✅ v1 complete")
    except Exception as exc:
        result["v1_status"] = "❌"
        result["error"] = str(exc)
        print(f"[{account_id}] ❌ v1 FAILED: {exc}", file=sys.stderr)
        return result  # can't run v2 without v1

    # Rate limit buffer
    time.sleep(2)

    # ── Pipeline B: Onboarding → v2 ──────────────────────────────────────────
    try:
        print(f"\n[{account_id}] Pipeline B — Processing onboarding transcript …")
        if not onboarding_path.exists():
            raise FileNotFoundError(f"Onboarding transcript not found: {onboarding_path}")

        run_v2_merger(account_id, onboarding_path, "onboarding_transcript")
        result["v2_status"] = "✅"
        print(f"[{account_id}] ✅ v2 complete")
    except Exception as exc:
        result["v2_status"] = "❌"
        result["error"] = str(exc)
        print(f"[{account_id}] ❌ v2 FAILED: {exc}", file=sys.stderr)
        return result

    # Rate limit buffer
    time.sleep(1)

    # ── Reporter ──────────────────────────────────────────────────────────────
    try:
        print(f"\n[{account_id}] Generating unknowns report …")
        run_reporter(account_id)
        result["report_status"] = "✅"
        print(f"[{account_id}] ✅ Report complete")
    except Exception as exc:
        result["report_status"] = "❌"
        result["error"] = str(exc)
        print(f"[{account_id}] ❌ Report FAILED: {exc}", file=sys.stderr)

    return result


def print_summary(results: list[dict]):
    print(f"\n{'='*60}")
    print("  PIPELINE RUN SUMMARY")
    print(f"{'='*60}")
    print(f"{'Account':<12} {'v1':^6} {'v2':^6} {'Report':^8} {'Error'}")
    print("-" * 60)
    for r in results:
        error_str = (r.get("error") or "")[:35]
        print(
            f"{r['account_id']:<12} {r['v1_status']:^6} {r['v2_status']:^6} "
            f"{r['report_status']:^8} {error_str}"
        )
    print("=" * 60)

    ok = sum(1 for r in results if r["v1_status"] == "✅" and r["v2_status"] == "✅")
    print(f"\n{ok}/{len(results)} accounts processed successfully.")

    print("\nOutput files written to:")
    for r in results:
        if r["v1_status"] == "✅":
            base = REPO_ROOT / "outputs" / "accounts" / r["account_id"]
            print(f"  {base}/v1/   — v1_memo.json, v1_agent_spec.json, v1_prompt.txt")
        if r["v2_status"] == "✅":
            base = REPO_ROOT / "outputs" / "accounts" / r["account_id"]
            print(f"  {base}/v2/   — v2_memo.json, v2_agent_spec.json, v2_prompt.txt, changes.json")
        if r["report_status"] == "✅":
            base = REPO_ROOT / "outputs" / "accounts" / r["account_id"]
            print(f"  {base}/v2/   — unknowns_report.md")


if __name__ == "__main__":
    _check_api_key()

    accounts_env = os.environ.get("ACCOUNTS")
    if accounts_env:
        accounts_to_run = [a.strip() for a in accounts_env.split(",") if a.strip()]
    else:
        accounts_to_run = ALL_ACCOUNTS

    print(f"\n🚀 Clara Answers Pipeline — Batch Run")
    print(f"   Accounts: {', '.join(accounts_to_run)}")
    print(f"   Model: gemini-1.5-flash\n")

    results = []
    for acc_id in accounts_to_run:
        r = process_account(acc_id)
        results.append(r)
        time.sleep(3)  # be kind to the free tier rate limits

    print_summary(results)
    print("\n✅ Batch run complete.")
