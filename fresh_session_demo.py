#!/usr/bin/env python3
"""
HaggleMind Fresh-Session Demo

This script demonstrates the load-bearing nature of Sibyl Memory
across TWO SEPARATE PROCESS INVOCATIONS:

  PHASE 1 (Process 1): Inject an invoice, run the agent.
    → Agent reads Sibyl Memory, picks high-confidence tactic, negotiates,
      gets a discount, pays, and WRITES the result back to Sibyl.

  PHASE 2 (Process 2): Fresh invocation — wipe + re-read.
    → Clears the in-memory singleton, re-opens the Sibyl store,
      reads the tactics written by Phase 1, and negotiates again.
      The agent remembers what it learned.

This is the "fresh-session recall beat" the judges require:
a continuous, unedited demo where a fresh session recalls state
written earlier.

Usage:
  python fresh_session_demo.py          # Full two-phase demo
  python fresh_session_demo.py --phase 1   # Just phase 1
  python fresh_session_demo.py --phase 2   # Just phase 2 (needs phase 1 data)
"""

import argparse
import json
import os
import sys
import time

import requests

# Ensure we can import from the project dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8777")
PRINT_WIDTH = 70

# Import the Sibyl-backed agent and memory store
import sibyl_memory
from agent import negotiate_bill, check_invoice


def header(text):
    print()
    print("=" * PRINT_WIDTH)
    print(f"  {text}")
    print("=" * PRINT_WIDTH)


def vendor_api(method, path, params=None, json_data=None):
    url = f"{VENDOR_URL}{path}"
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=5)
        else:
            r = requests.post(url, json=json_data, timeout=10)
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}"}
    except requests.RequestException as e:
        return {"error": str(e)}


def check_vendor_running():
    health = vendor_api("GET", "/health")
    if "error" in health:
        print(f"ERROR: Vendor API not running at {VENDOR_URL}")
        print("Start it: python vendor_server.py")
        sys.exit(1)
    print(f"[check] Vendor API: {VENDOR_URL} OK")


def inject_invoice(vendor: str, amount: float):
    """Inject an invoice into the vendor API."""
    result = vendor_api("POST", "/inject_invoice", json_data={
        "vendor": vendor,
        "amount": amount,
    })
    if "error" in result:
        print(f"Error injecting invoice: {result['error']}")
        sys.exit(1)
    print(f"[inject] Invoice injected: {vendor} — ${amount:.2f}/month")
    return result


def reset_sibyl_memory():
    """Wipe and re-initialize the Sibyl Memory store."""
    print("[setup] Resetting Sibyl Memory store...")
    # Close any existing store
    sibyl_memory.reset_store()

    # Create fresh store and inject default memory
    mem = sibyl_memory.SibylMemoryStore()
    mem.set_vendor_tactic("Comcast", "competitor_promo", confidence=0.90, successes=3, failures=0)
    mem.set_vendor_tactic("Comcast", "loyalty_discount", confidence=0.60, successes=1, failures=1)
    mem.set_vendor_tactic("Comcast", "budget_hardship", confidence=0.35, successes=0, failures=2)
    mem.storage.close()
    print("[setup] Sibyl Memory initialized with default vendor tactics.")
    print("[setup] (competitor_promo at 0.90 confidence for Comcast)")


def show_sibyl_state(label: str):
    """Show what's in Sibyl Memory right now."""
    print(f"\n  --- Sibyl Memory ({label}) ---")
    mem = sibyl_memory.SibylMemoryStore()
    entities = mem.client.list_entities("vendor", status="active", limit=200)
    if not entities:
        print("    (empty)")
    else:
        vendors = {}
        for ent in entities:
            name = ent.get("name", "")
            if "::" in name:
                v, tactic = name.split("::", 1)
                if v not in vendors:
                    vendors[v] = []
                vendors[v].append((tactic, ent.get("body", {})))

        for vendor in sorted(vendors):
            print(f"    {vendor}:")
            for tactic, body in sorted(vendors[vendor], key=lambda x: -x[1].get("confidence", 0)):
                print(f"      {tactic:25s} conf={body.get('confidence', 0):.2f}  s:{body.get('successes', 0)} f:{body.get('failures', 0)}")

    mem.storage.close()


def phase1():
    """PHASE 1: First process invocation — agent negotiates with memory."""
    header("PHASE 1: First Session — Agent Negotiates with Sibyl Memory")

    print()
    print("  In this phase, the agent:")
    print("  1. Reads Sibyl Memory (which tactic worked for Comcast before?)")
    print("  2. Picks the highest-confidence tactic")
    print("  3. Negotiates with the vendor")
    print("  4. Pays the discounted amount")
    print("  5. WRITES the result back to Sibyl Memory")
    print()

    # Reset everything to a clean state
    reset_sibyl_memory()

    # Check vendor is running
    check_vendor_running()

    # Inject a Comcast invoice
    inject_invoice("Comcast", 120.00)

    # Show memory state BEFORE the negotiation
    show_sibyl_state("BEFORE negotiation")

    print()
    header("Running agent (Phase 1)...")

    # Reset the singleton so agent gets fresh store
    sibyl_memory.reset_store()
    result = negotiate_bill("Comcast")

    # Show memory state AFTER the negotiation (agent wrote back)
    show_sibyl_state("AFTER negotiation")

    print()
    if result["accepted"]:
        print(f"  [Phase 1] SUCCESS: Agent negotiated {result['tactic_used']} -> ${result['final_amount']:.2f}")
        print(f"  [Phase 1] Savings: ${result['savings']:.2f} ({result['savings']/result['original_amount']*100:.1f}%)")
        print(f"  [Phase 1] Memory updated: confidence {result['confidence_before']:.2f} -> {result['confidence_after']:.2f}")
    else:
        print(f"  [Phase 1] FAILED: No discount. Paid full ${result['final_amount']:.2f}")
        print(f"  [Phase 1] Memory updated: confidence {result['confidence_before']:.2f} -> {result['confidence_after']:.2f}")

    # Store the phase 1 result for phase 2 to reference
    with open("_phase1_result.json", "w") as f:
        json.dump(result, f, indent=2)

    print()
    print("  >>> Phase 1 complete. Sibyl Memory now holds the negotiation result.")
    print("  >>> Launching Phase 2 (FRESH PROCESS) in 3 seconds...")
    time.sleep(3)

    # Launch phase 2 as a SEPARATE process
    import subprocess
    print()
    header("PHASE 2: Fresh Session — Recalling Memory from Phase 1")
    print()
    print("  This is a FRESH python process. It does NOT share memory with Phase 1.")
    print("  It re-opens the Sibyl store and reads what Phase 1 wrote.")
    print()

    result = subprocess.run(
        [sys.executable, __file__, "--phase", "2"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    if result.returncode != 0:
        print(f"\n[warn] Phase 2 exited with code {result.returncode}")


def phase2():
    """PHASE 2: Fresh process — re-opens Sibyl store and recalls Phase 1 data."""
    header("PHASE 2: Fresh Session Recall")

    print()
    print("  SUPPRESSING in-memory singleton, re-opening Sibyl SQLite store...")
    print()

    # Force a fresh store — simulates a new process invocation
    sibyl_memory.reset_store()

    # Show what Sibyl Memory contains (written by Phase 1)
    show_sibyl_state("FRESH SESSION — loaded from Sibyl store")

    print()
    header("Fresh Session: Negotiating with Comcast (injected for this phase)")

    # Inject a fresh invoice for this phase
    check_vendor_running()
    inject_invoice("Comcast", 120.00)

    print()
    print("  Agent re-opens Sibyl Memory, sees the tactics from Phase 1,")
    print("  picks the best one, and negotiates again...")
    print()

    # Run the agent — it should recall Phase 1's memory
    result = negotiate_bill("Comcast")

    print()
    if result["accepted"]:
        print(f"  [Phase 2] SUCCESS: Fresh session recalled memory!")
        print(f"  [Phase 2] Tactic: {result['tactic_used']} (confidence: {result['confidence_after']:.2f})")
        print(f"  [Phase 2] Paid: ${result['final_amount']:.2f} (saved ${result['savings']:.2f})")
    else:
        print(f"  [Phase 2] Result: {result['tactic_used']} -> ${result['final_amount']:.2f}")

    # Cross-phase comparison
    try:
        with open("_phase1_result.json", "r") as f:
            p1 = json.load(f)

        print()
        header("CROSS-PHASE COMPARISON")
        print()
        header_row = f"  {'Phase':<10} {'Tactic':<22} {'Paid':<10} {'Savings':<10}"
        sep_row = f"  {'-'*10} {'-'*22} {'-'*10} {'-'*10}"
        print(header_row)
        print(sep_row)
        print(f"  {'Phase 1':<10} {p1['tactic_used']:<22} ${p1['final_amount']:<9.2f} ${p1['savings']:<9.2f}")
        print(f"  {'Phase 2':<10} {result['tactic_used']:<22} ${result['final_amount']:<9.2f} ${result['savings']:<9.2f}")
        print()
        print(f"  Both phases used Sibyl Memory (via sibyl-memory-client SDK).")
        print(f"  Phase 2 re-opened the same SQLite store and recalled Phase 1's data.")
        print(f"  This is the FRESH-SESSION RECALL beat for the demo video.")
    except FileNotFoundError:
        print("[note] No Phase 1 result file found (run phase 1 first).")


def main():
    parser = argparse.ArgumentParser(description="HaggleMind Fresh-Session Demo")
    parser.add_argument("--phase", choices=["1", "2"], help="Run only a specific phase")
    args = parser.parse_args()

    if args.phase == "1":
        phase1()
    elif args.phase == "2":
        phase2()
    else:
        # Full demo: Phase 1 then Phase 2 (separate process)
        phase1()


if __name__ == "__main__":
    main()
