"""
HaggleMind Agent — reads Sibyl Memory via the real Sibyl SDK, negotiates bills, pays via REAL x402 on Base Sepolia.

Every memory operation goes through sibyl_memory.py → sibyl-memory-client SDK (SQLite + FTS5).
Every payment goes through x402_payment.py → x402 Python SDK + web3.py (real Base Sepolia tx).

No direct JSON file access. No simulated payments (unless X402_ENABLED=false).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8777")
X402_ENABLED = os.environ.get("X402_ENABLED", "false").lower() == "true"

# Known tactics
KNOWN_TACTICS = ["competitor_promo", "loyalty_discount", "budget_hardship"]

# Default tactic when memory is empty
DEFAULT_TACTIC = "loyalty_discount"

# Confidence adjustment parameters
CONFIDENCE_SUCCESS_BOOST = 0.10
CONFIDENCE_FAILURE_PENALTY = 0.15
CONFIDENCE_MAX = 0.95
CONFIDENCE_MIN = 0.05
CONFIDENCE_DROP_THRESHOLD = 0.20

# ---------------------------------------------------------------------------
# Sibyl Memory SDK (LOAD-BEARING — all reads/writes via real SDK)
# ---------------------------------------------------------------------------
import sibyl_memory  # noqa: E402  # our wrapper around sibyl-memory-client SDK


# ---------------------------------------------------------------------------
# Vendor API
# ---------------------------------------------------------------------------

def check_invoice(vendor: str) -> Optional[dict]:
    try:
        r = requests.get(f"{VENDOR_URL}/invoice", params={"vendor": vendor}, timeout=5)
        if r.status_code == 200 and r.json().get("has_invoice"):
            return r.json()
        return None
    except requests.RequestException as e:
        print(f"[agent] Error checking invoice: {e}")
        return None


def negotiate_with_vendor(vendor: str, tactic: str, amount: float) -> dict:
    try:
        r = requests.post(
            f"{VENDOR_URL}/negotiate",
            json={
                "vendor": vendor,
                "tactic": tactic,
                "amount": amount,
                "note": f"HaggleMind negotiating with {tactic}",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        return {"accepted": False, "final_amount": amount, "error": f"HTTP {r.status_code}", "vendor_response": "API error"}
    except requests.RequestException as e:
        return {"accepted": False, "final_amount": amount, "error": str(e), "vendor_response": "Connection failed"}


def pay_vendor(vendor: str, amount: float) -> dict:
    """Pay via x402 (real or simulated)."""
    from x402_payment import execute_x402_payment
    return execute_x402_payment(vendor, amount)


# ---------------------------------------------------------------------------
# Negotiation Cycle
# ---------------------------------------------------------------------------

def negotiate_bill(vendor: str) -> dict:
    print(f"\n{'='*60}")
    print(f"[agent] HaggleMind negotiating with {vendor}")
    print(f"{'='*60}")

    # Step 1: Check invoice
    invoice = check_invoice(vendor)
    if not invoice:
        return {"vendor": vendor, "status": "no_invoice", "message": f"No invoice for {vendor}"}

    original_amount = invoice["amount"]
    print(f"[agent] Invoice: ${original_amount:.2f}/month from {vendor}")

    # Step 2: Pick tactic from Sibyl Memory (LOAD-BEARING recall)
    mem = sibyl_memory.get_store()
    tactic = mem.pick_tactic(vendor)
    vendor_mem = mem.get_vendor_tactics(vendor)

    confidence = 0.0
    current = mem.get_tactic(vendor, tactic)
    if current:
        confidence = current["confidence"]

    print(f"[agent] Sibyl Memory for {vendor}:")
    if vendor_mem:
        for t, d in sorted(vendor_mem.items(), key=lambda x: -x[1].get("confidence", 0)):
            marker = " <-- USING THIS" if t == tactic else ""
            print(f"  {t:25s} conf={d.get('confidence', 0):.2f}  s:{d.get('successes', 0)} f:{d.get('failures', 0)}{marker}")
    else:
        print(f"  (empty — no Sibyl Memory for {vendor})")
    print(f"[agent] Selected: {tactic} (confidence: {confidence:.2f})")

    if not vendor_mem:
        print(f"[agent] *** DELETION TEST: No memory — using default '{DEFAULT_TACTIC}' ***")

    # Step 3: Negotiate
    print(f"[agent] Negotiating with '{tactic}'...")
    result = negotiate_with_vendor(vendor, tactic, original_amount)
    accepted = result.get("accepted", False)
    final_amount = result.get("final_amount", original_amount)
    print(f"[agent] Vendor: {result.get('vendor_response', '')}")
    print(f"[agent] ${original_amount:.2f} -> ${final_amount:.2f}  {'SAVED' if accepted else 'NO SAVE'}")

    # Step 4: Pay (real x402 on Base Sepolia, or simulated)
    print(f"[agent] Paying ${final_amount:.2f}...")
    pay_result = pay_vendor(vendor, final_amount)
    mode = pay_result.get("mode", "?")
    tx_info = pay_result.get("tx_hash", pay_result.get("error", ""))
    print(f"[agent] Payment: {mode} — {tx_info}")

    # Step 5: Update Sibyl Memory (self-modifying via SDK)
    confidence_after = mem.update_after_negotiation(vendor, tactic, accepted)
    mem.log_negotiation(
        vendor=vendor, tactic=tactic,
        original_amount=original_amount, final_amount=final_amount,
        accepted=accepted, confidence_before=confidence, confidence_after=confidence_after,
    )
    print(f"[agent] Sibyl Memory: {tactic} confidence -> {confidence_after:.2f}")

    # Dashboard persistence (optional, best-effort)
    _log_to_dashboard({
        "vendor": vendor,
        "tactic": tactic,
        "original_amount": original_amount,
        "final_amount": final_amount,
        "savings": original_amount - final_amount,
        "confidence_before": confidence,
        "confidence_after": confidence_after,
        "accepted": accepted,
        "payment_mode": mode,
        "tx_hash": pay_result.get("tx_hash", ""),
        "explorer_url": pay_result.get("explorer", ""),
    })

    return {
        "vendor": vendor,
        "status": "success" if accepted else "failed",
        "tactic_used": tactic,
        "confidence_before": confidence,
        "confidence_after": confidence_after,
        "original_amount": original_amount,
        "final_amount": final_amount,
        "savings": original_amount - final_amount,
        "accepted": accepted,
        "payment_mode": mode,
        "tx_hash": pay_result.get("tx_hash", ""),
        "explorer": pay_result.get("explorer", ""),
    }


# ---------------------------------------------------------------------------
# Dashboard persistence (optional — silent when dashboard DB is absent)
# ---------------------------------------------------------------------------
def _log_to_dashboard(result: dict) -> None:
    """Write this negotiation to the agent_logs table for the Streamlit dashboard."""
    try:
        from persistence import log_agent_run

        log_agent_run({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vendor": result.get("vendor", ""),
            "tactic": result.get("tactic", result.get("tactic_used", "")),
            "original_amount": result.get("original_amount", 0),
            "final_amount": result.get("final_amount", 0),
            "savings": result.get("savings", 0),
            "confidence_before": result.get("confidence_before"),
            "confidence_after": result.get("confidence_after"),
            "accepted": result.get("accepted", False),
            "payment_mode": result.get("payment_mode", "unknown"),
            "tx_hash": result.get("tx_hash", ""),
            "explorer_url": result.get("explorer_url", result.get("explorer", "")),
            "note": result.get("note", ""),
        })
    except Exception:
        pass  # dashboard persistence is best-effort; never break the CLI


def negotiate_all_vendors() -> list:
    results = []
    for vendor in ["Comcast", "Netflix", "Spotify", "DisneyPlus"]:
        r = negotiate_bill(vendor)
        results.append(r)
        if r["status"] == "no_invoice":
            print(f"[agent] Skipping {vendor} — no invoice.")
        time.sleep(0.5)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python agent.py <command> [args]")
        print("Commands: negotiate <vendor>, negotiate-all, status")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "negotiate":
        vendor = sys.argv[2] if len(sys.argv) > 2 else "Comcast"
        sibyl_memory.reset_store()
        result = negotiate_bill(vendor)
        print(f"\n[agent] Result: {json.dumps(result, indent=2)}")

    elif cmd == "negotiate-all":
        sibyl_memory.reset_store()
        results = negotiate_all_vendors()
        total_orig = sum(r.get("original_amount", 0) for r in results if r.get("original_amount"))
        total_final = sum(r.get("final_amount", 0) for r in results if r.get("final_amount"))
        total_saved = total_orig - total_final
        print(f"\n{'='*60}")
        print(f"[agent] SUMMARY ({'REAL x402' if X402_ENABLED else 'SIMULATED'})")
        print(f"{'='*60}")
        if total_orig > 0:
            print(f"Total original: ${total_orig:.2f}")
            print(f"Total final:    ${total_final:.2f}")
            print(f"Total saved:    ${total_saved:.2f} ({total_saved/total_orig*100:.1f}%)")
        for r in results:
            if r["status"] != "no_invoice":
                tx = r.get("tx_hash", "")[:20] if r.get("tx_hash") else "N/A"
                print(f"  {r['vendor']:15s} {r['tactic_used']:20s} ${r['original_amount']:.2f} -> ${r['final_amount']:.2f}  {'SAVED' if r['accepted'] else 'NO SAVE'}  tx:{tx}")

    elif cmd == "status":
        mem = sibyl_memory.get_store()
        mem.status()
        print(f"\n  Outstanding invoices:")
        for v in ["Comcast", "Netflix", "Spotify", "DisneyPlus"]:
            inv = check_invoice(v)
            if inv:
                s = "PAID" if inv["paid"] else "PENDING"
                print(f"    {v:15s} ${inv['amount']:.2f}  [{s}]" + (f" (negotiated: ${inv['negotiated_amount']:.2f})" if inv.get('negotiated_amount') else ""))
            else:
                print(f"    {v:15s} No invoice")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
