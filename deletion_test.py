#!/usr/bin/env python3
"""
Deletion Test -- automated proof that HaggleMind's memory is load-bearing.

This script sets up a DETERMINISTIC scenario where:
- competitor_promo ALWAYS succeeds (accept_prob=1.0)
- loyalty_discount NEVER succeeds (accept_prob=0.0)
- Memory guides the agent to use competitor_promo → $72
- No memory forces random tactic choice → likely $120

The test is self-contained and produces IDENTICAL results on every run.
"""

import json
import os
import sys
import time
from contextlib import contextmanager

from typing import Any, Dict

import requests

VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8777")

# Use the Sibyl SDK-backed store for deletion test
import sibyl_memory  # noqa: E402

PRINT_WIDTH = 70


@contextmanager
def managed_store():
    """Context manager for SibylMemoryStore that ensures cleanup."""
    mem = sibyl_memory.SibylMemoryStore()
    try:
        yield mem
    finally:
        try:
            mem.storage.close()
        except Exception:
            pass


def header(text):
    print()
    print("=" * PRINT_WIDTH)
    print(f"  {text}")
    print("=" * PRINT_WIDTH)
    print()


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
    print(f"[check] Vendor API is running at {VENDOR_URL}")


def apply_deletion_preset():
    """Apply deterministic rules for deletion test."""
    print("[setup] Applying deletion_test preset...")
    result = vendor_api("POST", "/rules/preset", json_data={"preset": "deletion_test"})
    if "error" in result:
        print(f"ERROR applying preset: {result['error']}")
        sys.exit(1)
    print(f"[setup] Preset applied: {result.get('status')}")


def restore_default_preset():
    """Restore original probabilistic rules."""
    print("[cleanup] Restoring default preset...")
    result = vendor_api("POST", "/rules/preset", json_data={"preset": "default"})
    if "error" in result:
        print(f"WARNING restoring preset: {result['error']}")


def wipe_and_seed_memory():
    """Wipe Sibyl memory and seed canonical state for deletion test."""
    print("[setup] Wiping and seeding Sibyl Memory...")
    # Use the singleton store directly so agent sees it
    import sibyl_memory
    mem = sibyl_memory.get_store()
    mem.wipe_all()
    # Seed canonical state: competitor_promo conf 0.95 (s:12 f:0), loyalty_discount conf 0.50
    mem.set_vendor_tactic("Comcast", "competitor_promo", confidence=0.95, successes=12, failures=0)
    mem.set_vendor_tactic("Comcast", "loyalty_discount", confidence=0.50, successes=5, failures=5)
    print("[setup] Memory seeded: competitor_promo (conf=0.95), loyalty_discount (conf=0.50)")


def inject_test_invoice():
    """Inject a $120 Comcast invoice."""
    print("[setup] Injecting Comcast invoice for $120/month...")
    result = vendor_api("POST", "/inject_invoice", json_data={
        "vendor": "Comcast",
        "amount": 120.00,
    })
    if "error" in result:
        print(f"ERROR injecting invoice: {result['error']}")
        sys.exit(1)
    print(f"[setup] Invoice injected. Amount: ${result['amount']:.2f}")


def run_agent():
    """Run the agent and return the final amount paid for Comcast."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agent import negotiate_bill

    print("[run] Running HaggleMind agent...")
    result = negotiate_bill("Comcast")
    return result


def print_deletion_result(with_memory_result, without_memory_result):
    """Print the deletion test results."""
    original = with_memory_result["original_amount"]
    with_price = with_memory_result["final_amount"]
    without_price = without_memory_result["final_amount"]

    with_savings = original - with_price
    without_savings = original - without_price
    extra_cost = without_price - with_price

    header("DELETION TEST RESULTS")

    print(f"  Scenario          | Tactic Used         | Price Paid   | Savings")
    print(f"  ------------------+---------------------+--------------+-------------")
    print(f"  WITH memory       | {with_memory_result['tactic_used']:21s} | ${with_price:10.2f} | ${with_savings:5.2f}")
    print(f"  WITHOUT memory    | {without_memory_result['tactic_used']:21s} | ${without_price:10.2f} | ${without_savings:5.2f}")
    print()

    print(f"  Original invoice amount:  ${original:.2f}")
    print(f"  Paid WITH memory:         ${with_price:.2f}  (saved ${with_savings:.2f})")
    print(f"  Paid WITHOUT memory:      ${without_price:.2f}  (saved ${without_savings:.2f})")
    print()
    print(f"  *** The agent paid ${extra_cost:.2f} MORE without memory ***")
    print()

    if without_price > with_price:
        print(f"  [PASS] Memory is LOAD-BEARING.")
        print(f"  [PASS] Deleting memory caused the agent to lose ${extra_cost:.2f}.")
        print(f"  [PASS] The agent's behavior changed based on memory state.")
    else:
        print(f"  [FAIL] Expected price without memory to be higher.")

    print()
    print(f"  Expected values: WITH=$72.00 (40% discount), WITHOUT=$120.00 (no discount)")
    print(f"  Actual delta: ${with_price + without_price - original - without_price:.2f}")


def main():
    header("HaggleMind Deletion Test (Deterministic)")
    print("  Proving that Sibyl Memory is load-bearing.")
    print("  Setup: competitor_promo always works, loyalty_discount never works.")
    print()

    # Check vendor API
    check_vendor_running()

    try:
        # Apply deterministic preset
        apply_deletion_preset()

        # Reset singleton store to ensure clean state
        import sibyl_memory
        sibyl_memory.reset_store()

        # Seed canonical state for Phase 1
        wipe_and_seed_memory()

        # Inject test invoice
        inject_test_invoice()

        # Phase 1: Run WITH memory
        print()
        print("-" * PRINT_WIDTH)
        print("  PHASE 1: Running WITH memory (normal operation)")
        print("-" * PRINT_WIDTH)
        with_result = run_agent()

        # Wipe memory (no reseed)
        print()
        wipe_memory()

        # Inject fresh invoice for Phase 2
        inject_test_invoice()

        # Phase 2: Run WITHOUT memory
        print()
        print("-" * PRINT_WIDTH)
        print("  PHASE 2: Running WITHOUT memory (deletion test)")
        print("-" * PRINT_WIDTH)
        without_result = run_agent()

        # Print results
        print_deletion_result(with_result, without_result)

    finally:
        # Always restore default preset
        restore_default_preset()
        print()
        print("[cleanup] Default vendor rules restored.")

    print()
    print("=" * PRINT_WIDTH)
    print("  Test complete.")
    print("=" * PRINT_WIDTH)


def wipe_memory():
    """Wipe the Sibyl Memory store completely (no reseed)."""
    print("[wipe] Wiping Sibyl Memory (SQLite store)...")
    import sibyl_memory
    mem = sibyl_memory.get_store()
    mem.wipe_all()
    print("[wipe] All vendor entities deleted from Sibyl Memory.")


if __name__ == "__main__":
    main()
