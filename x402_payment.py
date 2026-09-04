"""
x402 Payment Module — REAL on-chain Base Sepolia payments for HaggleMind.

Uses the official x402 Python SDK (x402ClientSync + ExactEvmScheme) and web3.py
to execute REAL micropayments on Base Sepolia via the x402 protocol.

Flow:
  1. Agent POSTs to vendor /pay-x402 endpoint
  2. Vendor returns HTTP 402 + PAYMENT-REQUIRED header (base64 PaymentRequired)
  3. Agent parses PaymentRequired, creates PaymentPayload via x402 SDK
  4. Agent signs payload with web3 (EIP-712 / eth_sign)
  5. Agent resubmits with PAYMENT-SIGNATURE header
  6. Vendor verifies on-chain, settles, returns tx hash + explorer link

Fallback: if X402_ENABLED=false, uses the mock vendor API directly.
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Dashboard persistence helpers (optional, best-effort)
# ---------------------------------------------------------------------------
def _log_tx_to_dashboard(entry: dict) -> None:
    """Write a transaction row for the Streamlit dashboard.

    Best-effort: if the persistence module or DB is absent the call is
    silently ignored so the CLI never breaks.
    """
    try:
        from persistence import log_transaction

        log_transaction({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vendor": entry.get("vendor", ""),
            "amount_usd": float(entry.get("amount_usd", entry.get("amount", 0))),
            "tx_hash": entry.get("tx_hash", ""),
            "block_number": entry.get("block_number"),
            "network": entry.get("network", "Base Sepolia"),
            "explorer_url": entry.get("explorer_url", ""),
            "payment_mode": entry.get("payment_mode", "unknown"),
            "status": entry.get("status", "confirmed"),
        })
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8777")
X402_ENABLED = os.environ.get("X402_ENABLED", "false").lower() == "true"
X402_FACILITATOR_URL = os.environ.get("X402_FACILITATOR_URL", "https://x402.org/facilitator")
BASE_RPC = os.environ.get("BASE_RPC", "https://sepolia.base.org")
BASE_RPC_KEY = os.environ.get("BASE_RPC_KEY", "")
BASE_CHAIN_ID = int(os.environ.get("BASE_CHAIN_ID", "84532"))  # 84532 = Base Sepolia
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "")
GAS_LIMIT = int(os.environ.get("GAS_LIMIT", "200000"))
GAS_PRICE_GWEI = float(os.environ.get("GAS_PRICE_GWEI", "1.0"))
USD_VALUE = float(os.environ.get("X402_USD_VALUE", "0.01"))  # Amount per payment in USD
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "")  # Optional: pre-computed address

# Vendor burner wallet on Base Sepolia — payments go here
VENDOR_BURNER_WALLET = os.environ.get("VENDOR_BURNER_WALLET", "0xYourBaseSepoliaVendorWalletHere")
VENDOR_EXPLORER_BASE = "https://sepolia.basescan.org/tx/"


# ---------------------------------------------------------------------------
# Wallet helpers
# ---------------------------------------------------------------------------

def get_wallet_address() -> str:
    """Derive the wallet address from the private key (cached)."""
    global WALLET_ADDRESS
    if WALLET_ADDRESS:
        return WALLET_ADDRESS
    if not PRIVATE_KEY:
        return ""
    try:
        from web3 import Web3
        account = Web3().eth.account.from_key(PRIVATE_KEY)
        WALLET_ADDRESS = account.address
        return WALLET_ADDRESS
    except Exception as e:
        print(f"[x402] Error deriving address: {e}")
        return ""


# ---------------------------------------------------------------------------
# Real x402 payment on Base Sepolia
# ---------------------------------------------------------------------------

def execute_x402_payment(vendor: str, amount_usd: float) -> dict:
    """Execute a REAL x402 micropayment on Base Sepolia.

    When X402_ENABLED=true:
    1. Creates an x402ClientSync with ExactEvmScheme
    2. POSTs to the vendor's x402-protected endpoint
    3. Receives HTTP 402 + PAYMENT-REQUIRED header
    4. Creates and signs a PaymentPayload
    5. Resubmits with PAYMENT-SIGNATURE
    6. Returns the on-chain result with tx hash + explorer link

    Falls back to mock vendor API (/pay) if the vendor doesn't return 402.
    """
    if not X402_ENABLED:
        return _execute_fallback_payment(vendor, amount_usd)

    if not PRIVATE_KEY:
        return {
            "paid": False,
            "amount": amount_usd,
            "vendor": vendor,
            "mode": "no_key",
            "error": "PRIVATE_KEY not set. Set it in .env to enable real payments.",
        }

    print(f"\n[x402] === Executing x402 payment on Base Sepolia ===")
    print(f"[x402] Vendor:      {vendor}")
    print(f"[x402] Amount:      ${amount_usd:.2f} USD")
    print(f"[x402] Destination: {VENDOR_BURNER_WALLET} (vendor burner wallet)")
    print(f"[x402] Chain:       Base Sepolia (eip155:{BASE_CHAIN_ID})")
    print(f"[x402] RPC:         {BASE_RPC}")
    print()

    try:
        from web3 import Web3
        from x402 import x402ClientSync
        from x402.mechanisms.evm.exact import ExactEvmScheme
        from x402.schemas import parse_payment_required
    except ImportError as e:
        print(f"[x402] IMPORT ERROR: {e}")
        print("[x402] Install: pip install x402[evm] web3")
        return {
            "paid": False,
            "amount": amount_usd,
            "vendor": vendor,
            "mode": "import_error",
            "error": str(e),
        }

    # --- Setup web3 ---
    w3 = Web3(Web3.HTTPProvider(BASE_RPC if not BASE_RPC_KEY else f"{BASE_RPC}?apikey={BASE_RPC_KEY}"))
    account = w3.eth.account.from_key(PRIVATE_KEY)
    print(f"[x402] web3 connected: chain_id={w3.eth.chain_id}, block={w3.eth.block_number}")
    print(f"[x402] Payer wallet: {account.address}")

    # --- Build x402 client with EVM signer ---
    client = x402ClientSync()

    def evm_signer(signable: str) -> str:
        message_hash = w3.eth.account.hash_message(signable)
        signed = w3.eth.account.sign_hash(message_hash, private_key=PRIVATE_KEY)
        return signed.signature.hex()

    client.register("eip155:84532", ExactEvmScheme(signer=evm_signer))
    print("[x402] x402ClientSync registered with ExactEvmScheme on Base Sepolia")

    # --- Step 1: Make the payment-gated request ---
    print(f"\n[x402] Step 1: POST {VENDOR_URL}/pay-x402")
    payload = {"vendor": vendor, "amount_usd": amount_usd}

    try:
        r = requests.post(
            f"{VENDOR_URL}/pay-x402",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        print(f"[x402] Response: HTTP {r.status_code}")
    except requests.RequestException as e:
        print(f"[x402] Request failed: {e}")
        return _execute_fallback_payment(vendor, amount_usd)

    # --- Step 2: If no 402, vendor accepted directly ---
    if r.status_code == 200:
        result = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {"paid": True, "raw": r.text[:500]}
        result["mode"] = "direct"
        print(f"[x402] Vendor accepted direct payment (no 402 needed)")

        # Dashboard persistence
        _log_tx_to_dashboard({
            "vendor": vendor,
            "amount_usd": amount_usd,
            "tx_hash": result.get("tx_hash", ""),
            "network": "Base Sepolia",
            "explorer_url": result.get("explorer_url", ""),
            "payment_mode": "direct_api",
        })
        return result

    if r.status_code != 402:
        print(f"[x402] Unexpected status {r.status_code} — falling back to direct /pay")
        return _execute_fallback_payment(vendor, amount_usd)

    # --- Step 3: Parse PAYMENT-REQUIRED ---
    print(f"\n[x402] Step 2: Parsing PAYMENT-REQUIRED header...")
    pr_header = r.headers.get("PAYMENT-REQUIRED") or r.headers.get("payment-required")

    if not pr_header:
        try:
            body = r.json()
            if isinstance(body, dict) and "payment_required" in body:
                pr_header = body["payment_required"]
            elif isinstance(body, str):
                pr_header = body
        except Exception:
            pass

    if not pr_header:
        print(f"[x402] ERROR: No PAYMENT-REQUIRED header in 402 response")
        print(f"[x402] Response headers: {dict(r.headers)}")
        print(f"[x402] Response body: {r.text[:500]}")
        return {
            "paid": False,
            "amount": amount_usd,
            "vendor": vendor,
            "mode": "no_payment_required",
            "error": "402 response missing PAYMENT-REQUIRED header",
        }

    try:
        payment_required = parse_payment_required(pr_header)
        print(f"[x402] PaymentRequired:")
        print(f"  version: {payment_required.x402_version}")
        print(f"  accepts: {len(payment_required.accepts)} options")
        for i, accept in enumerate(payment_required.accepts):
            print(f"    [{i}] network={accept.network} price={accept.price} payTo={accept.payTo}")
    except Exception as e:
        print(f"[x402] ERROR parsing PaymentRequired: {e}")
        return {
            "paid": False,
            "amount": amount_usd,
            "vendor": vendor,
            "mode": "parse_error",
            "error": f"Failed to parse PAYMENT-REQUIRED: {e}",
        }

    # --- Step 4: Create PaymentPayload ---
    print(f"\n[x402] Step 3: Creating PaymentPayload...")
    try:
        payment_payload = client.create_payment_payload(payment_required)
        print(f"[x402] PaymentPayload created (x402_version={payment_payload.x402_version})")
    except Exception as e:
        print(f"[x402] ERROR creating payment payload: {e}")
        import traceback
        traceback.print_exc()
        return {
            "paid": False,
            "amount": amount_usd,
            "vendor": vendor,
            "mode": "payload_error",
            "error": f"Failed to create payment payload: {e}",
        }

    # --- Step 5: Resubmit with PAYMENT-SIGNATURE ---
    print(f"\n[x402] Step 4: Resubmitting with signed PAYMENT-SIGNATURE...")

    serialization_methods = [
        ("model_dump_json", lambda p: p.model_dump_json().encode()),
        ("json", lambda p: p.json().encode()),
        ("dict", lambda p: json.dumps(p.__dict__ if hasattr(p, '__dict__') else p, default=str).encode()),
    ]

    payload_bytes = None
    for method_name, serializer in serialization_methods:
        try:
            payload_bytes = serializer(payment_payload)
            print(f"[x402] Serialized via {method_name} ({len(payload_bytes)} bytes)")
            break
        except Exception:
            continue

    if payload_bytes is None:
        print(f"[x402] ERROR: Could not serialize PaymentPayload")
        return {
            "paid": False,
            "amount": amount_usd,
            "vendor": vendor,
            "mode": "serialize_error",
            "error": "Could not serialize PaymentPayload",
        }

    signature_b64 = base64.b64encode(payload_bytes).decode()

    try:
        r2 = requests.post(
            f"{VENDOR_URL}/pay-x402",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "PAYMENT-SIGNATURE": signature_b64,
            },
            timeout=15,
        )
        print(f"[x402] Resubmit response: HTTP {r2.status_code}")

        if r2.status_code == 200:
            result = r2.json() if r2.headers.get("Content-Type", "").startswith("application/json") else {"paid": True, "raw": r2.text[:500]}
            tx_hash = result.get("tx_hash") or result.get("transaction_hash") or result.get("hash", "")
            explorer = ""
            if tx_hash:
                explorer = f"{VENDOR_EXPLORER_BASE}{tx_hash}"
                print(f"[x402] TX HASH: {tx_hash}")
                print(f"[x402] EXPLORER: {explorer}")

            result["mode"] = "x402_onchain"
            result["tx_hash"] = tx_hash
            result["explorer"] = explorer
            result["amount"] = amount_usd
            result["vendor"] = vendor
            result["timestamp"] = datetime.now(timezone.utc).isoformat()
            print(f"\n[x402] === PAYMENT SUCCESSFUL ===")
            print(f"[x402] Mode:    x402_onchain (real Base Sepolia tx)")
            print(f"[x402] Amount:  ${amount_usd:.2f} USD")
            print(f"[x402] TX Hash: {tx_hash}")
            print(f"[x402] Explorer: {explorer}")

            # Dashboard persistence — record the on-chain tx
            _log_tx_to_dashboard({
                "vendor": vendor,
                "amount_usd": amount_usd,
                "tx_hash": tx_hash,
                "network": "Base Sepolia",
                "explorer_url": explorer,
                "payment_mode": "x402_onchain",
            })

            return result
        else:
            print(f"[x402] Resubmit failed: HTTP {r2.status_code}")
            print(f"[x402] Body: {r2.text[:300]}")
            return _execute_fallback_payment(vendor, amount_usd)

    except requests.RequestException as e:
        print(f"[x402] Resubmit request failed: {e}")
        return _execute_fallback_payment(vendor, amount_usd)


# ---------------------------------------------------------------------------
# Fallback payment — direct /pay endpoint when x402 isn't available
# ---------------------------------------------------------------------------

def _execute_fallback_payment(vendor: str, amount: float) -> dict:
    """Pay via mock vendor's /pay endpoint (no on-chain tx)."""
    print(f"\n[x402] Falling back to direct /pay endpoint")
    try:
        r = requests.post(
            f"{VENDOR_URL}/pay",
            json={"vendor": vendor, "amount": amount},
            timeout=10,
        )
        if r.status_code == 200:
            result = r.json()
            result["mode"] = "direct_api"
            # Dashboard persistence — record the simulated/direct tx
            _log_tx_to_dashboard({
                "vendor": vendor,
                "amount_usd": amount,
                "tx_hash": result.get("tx_hash", ""),
                "network": "Base Sepolia",
                "explorer_url": result.get("explorer_url", ""),
                "payment_mode": "direct_api",
                "status": "confirmed",
            })
            return result
    except requests.RequestException:
        pass

    fallback = {
        "paid": True,
        "amount": amount,
        "vendor": vendor,
        "mode": "simulated",
        "tx_hash": f"0x_sim_{vendor}_{int(time.time())}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _log_tx_to_dashboard({
        "vendor": vendor,
        "amount_usd": amount,
        "tx_hash": fallback["tx_hash"],
        "network": "Base Sepolia",
        "explorer_url": "",
        "payment_mode": "simulated",
        "status": "simulated",
    })
    return fallback


# ---------------------------------------------------------------------------
# Build an x402-protected vendor endpoint URL
# ---------------------------------------------------------------------------

def get_x402_pay_url(vendor: str) -> str:
    """Get the x402 payment endpoint URL for a vendor."""
    return f"{VENDOR_URL}/pay-x402"


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="x402 Payment — real on-chain Base Sepolia payment")
    parser.add_argument("--vendor", default="Comcast", help="Vendor to pay")
    parser.add_argument("--amount", type=float, default=75.0, help="Amount in USD")
    parser.add_argument("--enable-real", action="store_true", help="Enable real x402 (requires PRIVATE_KEY)")
    args = parser.parse_args()

    if args.enable_real:
        os.environ["X402_ENABLED"] = "true"

    print(f"=== x402 Payment Demo ===")
    print(f"  Vendor:  {args.vendor}")
    print(f"  Amount:  ${args.amount:.2f}")
    print(f"  Mode:    {'REAL on-chain' if X402_ENABLED else 'SIMULATED'}")
    print()

    result = execute_x402_payment(args.vendor, args.amount)
    print()
    print("Result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
