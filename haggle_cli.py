#!/usr/bin/env python3
"""
HaggleMind Time-Machine Simulator CLI

Aggressively test the background agent without waiting 30 days.

Commands:
  inject_invoice   --vendor "Comcast" --amount 120   Inject a bill into the vendor API
  run             Run the agent against all pending invoices
  fast_forward    --days 30                           Advance time (for multi-month sim)
  chaos           --vendor "Comcast"                  Randomly change vendor hidden rules
  wipe_memory     Wipe the Sibyl Memory store (deletion test)
  status          Show memory state and pending invoices
  reset           Reset everything (vendor rules + memory + invoices)

Examples:
  python haggle_cli.py inject_invoice --vendor "Comcast" --amount 120
  python haggle_cli.py run
  python haggle_cli.py fast_forward --days 30
  python haggle_cli.py chaos --vendor "Comcast"
  python haggle_cli.py wipe_memory
  python haggle_cli.py status
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8777")
TIME_LOG_FILE = "time_log.json"

# Sibyl Memory is the load-bearing store — SQLite via sibyl-memory-client SDK
import sibyl_memory  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def vendor_api(method: str, path: str, params=None, json_data=None) -> dict:
    """Make a request to the vendor API."""
    url = f"{VENDOR_URL}{path}"
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=5)
        else:
            r = requests.post(url, json=json_data, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            return {"error": f"HTTP {r.status_code}", "body": r.text}
    except requests.RequestException as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_inject_invoice(args):
    """Inject an invoice for a vendor."""
    vendor = args.vendor
    amount = args.amount
    result = vendor_api("POST", "/inject_invoice", json_data={
        "vendor": vendor,
        "amount": amount,
    })
    if "error" in result:
        print(f"Error injecting invoice: {result['error']}")
        sys.exit(1)
    print(f"[cli] Injected invoice for {vendor}: ${amount:.2f}/month")
    print(f"[cli] Timestamp: {result.get('timestamp', 'N/A')}")


def cmd_run(args):
    """Run the agent against all pending invoices."""
    mem = sibyl_memory.SibylMemoryStore()
    db_path = mem.db_path
    mem.storage.close()
    print(f"[cli] Running HaggleMind agent...")
    print(f"[cli] Vendor API: {VENDOR_URL}")
    print(f"[cli] Memory store: {db_path} (sibyl-memory-client SDK, SQLite)")
    print()

    # Import and run the agent
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agent import negotiate_all_vendors
    results = negotiate_all_vendors()

    print()
    print(f"[cli] {'='*60}")
    print(f"[cli] RUN COMPLETE — Summary")
    print(f"[cli] {'='*60}")

    total_original = sum(r.get("original_amount", 0) for r in results if r.get("original_amount"))
    total_final = sum(r.get("final_amount", 0) for r in results if r.get("final_amount"))
    total_savings = total_original - total_final

    print(f"  Invoices processed: {len([r for r in results if r['status'] != 'no_invoice'])}")
    if total_original > 0:
        print(f"  Total original:      ${total_original:.2f}")
        print(f"  Total after negotiate: ${total_final:.2f}")
        print(f"  Total saved:         ${total_savings:.2f} ({total_savings/total_original*100:.1f}%)")
    else:
        print(f"  No invoices to process.")

    for r in results:
        if r["status"] != "no_invoice":
            saved = r["original_amount"] - r["final_amount"]
            print(f"  {r['vendor']:15s}  {r['tactic_used']:20s}  ${r['original_amount']:.2f} -> ${r['final_amount']:.2f}  {'SAVED ${:.2f}'.format(saved) if saved > 0 else 'NO SAVE'}")

    # Log the run
    log_run(results)


def log_run(results):
    """Log this run to time_log.json for time-travel simulation."""
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    logs = []
    if os.path.exists(TIME_LOG_FILE):
        with open(TIME_LOG_FILE, "r") as f:
            logs = json.load(f)
    logs.append(log_entry)
    with open(TIME_LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)


def cmd_fast_forward(args):
    """Fast-forward time by N days."""
    days = args.days
    print(f"[cli] Fast-forwarding {days} day(s)...")

    # Update the time log with a time jump marker
    logs = []
    if os.path.exists(TIME_LOG_FILE):
        with open(TIME_LOG_FILE, "r") as f:
            logs = json.load(f)

    jump_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "time_jump",
        "days": days,
        "new_date": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
    }
    logs.append(jump_entry)
    with open(TIME_LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

    print(f"[cli] Time advanced {days} day(s).")
    print(f"[cli] New simulated date: {(datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}")
    print(f"[cli] Note: This is a simulation time-log marker. The agent uses the Sibyl SQLite")
    print(f"[cli] store (sibyl-memory-client SDK) which persists across sessions regardless")
    print(f"[cli] of wall-clock time.")


def cmd_chaos(args):
    """Apply chaos: randomly change vendor hidden rules."""
    vendor = args.vendor
    print(f"[cli] Applying chaos to {vendor}...")
    print(f"[cli] This will randomly mutate the vendor's hidden negotiation rules.")
    print(f"[cli] A tactic that previously worked may suddenly stop working.")
    print()

    result = vendor_api("POST", "/chaos", json_data={"vendor": vendor})
    if "error" in result:
        print(f"Error applying chaos: {result['error']}")
        sys.exit(1)

    print(f"[cli] Chaos applied!")
    print(f"  Vendor:    {result.get('vendor')}")
    print(f"  Tactic:    {result.get('tactic')}")
    print(f"  Old prob:  {result.get('old_accept_prob')}")
    print(f"  New prob:  {result.get('new_accept_prob')}")
    print(f"  Label:     {result.get('label')}")
    print()
    print(f"[cli] *** The agent's memory still thinks this tactic works. ***")
    print(f"[cli] *** Next negotiation will likely FAIL — watch the agent rewrite its confidence down. ***")


def cmd_wipe_memory(args):
    """Wipe the Sibyl Memory store — drops all vendor entities from SQLite."""
    print("[cli] Wiping Sibyl Memory store (SQLite)...")

    mem = sibyl_memory.SibylMemoryStore()
    db_path = mem.db_path

    # Snapshot before wipe
    entities_before = mem.client.list_entities("vendor", status="active", limit=200)
    print(f"[cli] Entities before wipe: {len(entities_before)}")

    # Drop ALL vendor entities from the WARM tier
    for ent in entities_before:
        mem.client.delete_entity("vendor", ent["name"])

    # Also clear any journal entries
    events = mem.client.read_events(limit=200)
    print(f"[cli] Journal events before wipe: {len(events)}")

    # Wipe everything by resetting tenant
    mem.set_tenant("00000000-0000-0000-0000-000000000000")  # zero tenant = empty

    mem.storage.close()

    print(f"[cli] Memory wiped! All vendor entities deleted from {db_path}")
    print()
    print("[cli] *** DELETION TEST: Run 'python haggle_cli.py run' to see the agent fail without memory. ***")
    print("[cli] *** The agent will use default tactics and pay full price. ***")


def cmd_status(args):
    """Show memory state and pending invoices."""
    print(f"[cli] {'='*60}")
    print(f"[cli] STATUS")
    print(f"[cli] {'='*60}")
    print(f"  Vendor API:  {VENDOR_URL}")

    # Show Sibyl Memory store info
    mem = sibyl_memory.SibylMemoryStore()
    db_path = mem.db_path
    mem.storage.close()
    print(f"  Memory store: {db_path} (sibyl-memory-client SDK, SQLite)")
    print()

    # Memory status — read from Sibyl SQLite
    print(f"  --- Sibyl Memory (SDK-backed) ---")
    mem2 = sibyl_memory.SibylMemoryStore()
    entities = mem2.client.list_entities("vendor", status="active", limit=200)
    if not entities:
        print(f"    (empty — no vendor entities in Sibyl Memory)")
    else:
        vendors: dict[str, dict[str, Any]] = {}
        for ent in entities:
            name = ent.get("name", "")
            if "::" not in name:
                continue
            v, tactic = name.split("::", 1)
            body = ent.get("body", {})
            if v not in vendors:
                vendors[v] = {}
            vendors[v][tactic] = {
                "confidence": body.get("confidence", 0),
                "successes": body.get("successes", 0),
                "failures": body.get("failures", 0),
            }

        for vendor in sorted(vendors):
            print(f"    {vendor}:")
            for tactic in sorted(vendors[vendor], key=lambda t: -vendors[vendor][t]["confidence"]):
                d = vendors[vendor][tactic]
                print(f"      {tactic:25s} conf={d['confidence']:.2f}  s:{d['successes']} f:{d['failures']}")

    # Journal count
    events = mem2.client.read_events(limit=200)
    print(f"    Negotiation events logged: {len(events)}")
    mem2.storage.close()

    print()

    # Invoice status
    print(f"  --- Pending Invoices ---")
    vendors_list = ["Comcast", "Netflix", "Spotify", "DisneyPlus"]
    for vendor in vendors_list:
        inv = vendor_api("GET", "/invoice", params={"vendor": vendor})
        if "error" not in inv:
            if inv.get("has_invoice"):
                status = "PAID" if inv["paid"] else "PENDING"
                neg = f" (negotiated: ${inv['negotiated_amount']:.2f})" if inv.get("negotiated_amount") else ""
                print(f"    {vendor:15s} ${inv['amount']:.2f}/mo  [{status}]{neg}")
            else:
                print(f"    {vendor:15s} No invoice")
        else:
            print(f"    {vendor:15s} Error: {inv.get('error', 'Unknown')}")

    print()

    # Time log summary
    if os.path.exists(TIME_LOG_FILE):
        with open(TIME_LOG_FILE, "r") as f:
            logs = json.load(f)
        print(f"  --- Time Log ({len(logs)} entries) ---")
        for entry in logs[-5:]:
            if entry.get("type") == "time_jump":
                print(f"    [JUMP] +{entry['days']} days -> {entry['new_date']}")
            else:
                ts = entry.get("timestamp", "")[:19]
                processed = len([r for r in entry.get("results", []) if r.get("status") != "no_invoice"])
                print(f"    [RUN]  {ts}  ({processed} invoices processed)")


def cmd_reset(args):
    """Reset everything."""
    print("[cli] Resetting everything...")

    # Reset vendor rules
    vendor_api("POST", "/reset_rules")
    print("[cli] Vendor rules reset to defaults.")

    # Reset invoices
    for vendor in ["Comcast", "Netflix", "Spotify", "DisneyPlus"]:
        vendor_api("POST", "/inject_invoice", json_data={"vendor": vendor, "amount": 0})
    print("[cli] All invoices cleared.")

    # Reset Sibyl Memory — wipe the SQLite store
    print("[cli] Wiping Sibyl Memory store...")
    mem = sibyl_memory.SibylMemoryStore()
    entities = mem.client.list_entities("vendor", status="active", limit=200)
    for ent in entities:
        mem.client.delete_entity("vendor", ent["name"])
    mem.storage.close()
    print(f"[cli] Sibyl Memory store wiped ({mem.db_path}).")

    # Reset time log
    if os.path.exists(TIME_LOG_FILE):
        os.remove(TIME_LOG_FILE)
    print("[cli] Time log cleared.")

    # Re-inject default memory via Sibyl SDK
    print("[cli] Re-injecting default vendor tactics via Sibyl SDK...")
    mem2 = sibyl_memory.SibylMemoryStore()
    mem2.set_vendor_tactic("Comcast", "competitor_promo", confidence=0.90, successes=3, failures=0)
    mem2.set_vendor_tactic("Comcast", "loyalty_discount", confidence=0.60, successes=1, failures=1)
    mem2.set_vendor_tactic("Comcast", "budget_hardship", confidence=0.35, successes=0, failures=2)
    mem2.set_vendor_tactic("Netflix", "competitor_promo", confidence=0.75, successes=2, failures=0)
    mem2.set_vendor_tactic("Netflix", "loyalty_discount", confidence=0.50, successes=1, failures=1)
    mem2.storage.close()
    print("[cli] Default memory re-injected into Sibyl Memory (SQLite).")

    print("[cli] Reset complete.")


# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HaggleMind Time-Machine Simulator — test the agent without waiting 30 days",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s inject_invoice --vendor "Comcast" --amount 120
  %(prog)s run
  %(prog)s fast_forward --days 30
  %(prog)s chaos --vendor "Comcast"
  %(prog)s wipe_memory
  %(prog)s status
  %(prog)s reset
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # inject_invoice
    p_inject = subparsers.add_parser("inject_invoice", help="Inject a bill into the vendor API")
    p_inject.add_argument("--vendor", required=True, help="Vendor name (e.g. Comcast, Netflix)")
    p_inject.add_argument("--amount", type=float, required=True, help="Monthly amount in dollars")

    # run
    subparsers.add_parser("run", help="Run the agent against all pending invoices")

    # fast_forward
    p_ff = subparsers.add_parser("fast_forward", help="Advance simulated time")
    p_ff.add_argument("--days", type=int, default=30, help="Number of days to advance (default: 30)")

    # chaos
    p_chaos = subparsers.add_parser("chaos", help="Randomly change vendor hidden rules")
    p_chaos.add_argument("--vendor", required=True, help="Vendor to chaos (e.g. Comcast)")

    # wipe_memory
    subparsers.add_parser("wipe_memory", help="Wipe the Sibyl Memory store (triggers deletion test)")

    # status
    subparsers.add_parser("status", help="Show memory state and pending invoices")

    # reset
    subparsers.add_parser("reset", help="Reset everything (vendor rules, memory, invoices, time log)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Ensure vendor server is running
    health = vendor_api("GET", "/health")
    if "error" in health:
        print(f"Error: Cannot connect to vendor API at {VENDOR_URL}")
        print(f"Start the vendor server first: python vendor_server.py")
        sys.exit(1)

    if args.command == "inject_invoice":
        cmd_inject_invoice(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "fast_forward":
        cmd_fast_forward(args)
    elif args.command == "chaos":
        cmd_chaos(args)
    elif args.command == "wipe_memory":
        cmd_wipe_memory(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "reset":
        cmd_reset(args)


if __name__ == "__main__":
    main()
