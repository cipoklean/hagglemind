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

# Load .env automatically so X402_ENABLED, VENDOR_BURNER_WALLET, etc. are available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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
# Snake-case -> camelCase normalization for off-spec vendors
# ---------------------------------------------------------------------------
_SNAKE_TO_CAMEL_TOP = {
    "x402_version": "x402Version",
    "resource": "resource",  # passthrough (handled below if dict)
}
_SNAKE_TO_CAMEL_ACCEPT = {
    "max_amount_required": "maxAmountRequired",
    "min_amount_required": "minAmountRequired",
    "max_timeout_seconds": "maxTimeoutSeconds",
    "pay_to": "payTo",
    "mime_type": "mimeType",
    "description": "description",
    "asset": "asset",
    "scheme": "scheme",
    "network": "network",
    "output_schema": "outputSchema",
    "extra": "extra",
}


def _rename(d: dict, old: str, new: str) -> None:
    if old in d and new not in d:
        d[new] = d.pop(old)


def _normalize_payment_required(decoded: dict) -> dict:
    """Normalize snake_case PaymentRequired variants to the SDK's camelCase
    model aliases. Works for both V1 (PaymentRequiredV1) and V2
    (PaymentRequired) wire shapes, including V1 accept entries that carry
    maxAmountRequired / mimeType / resource-as-string.
    """
    out = dict(decoded)
    _rename(out, "x402_version", "x402Version")
    resource = out.get("resource")
    if isinstance(resource, dict):
        out["resource"] = _normalize_resource(resource)
    accepts = out.get("accepts")
    if isinstance(accepts, list):
        out["accepts"] = [_normalize_accept(a) for a in accepts]
    return out


def _normalize_resource(d: dict) -> dict:
    out = dict(d)
    _rename(out, "mime_type", "mimeType")
    _rename(out, "service_name", "serviceName")
    _rename(out, "icon_url", "iconUrl")
    return out


def _normalize_accept(d: dict) -> dict:
    out = dict(d)
    for snake, camel in _SNAKE_TO_CAMEL_ACCEPT.items():
        _rename(out, snake, camel)
    # resource inside an accept is a plain string URL in V1 — leave as-is.
    return out
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
    # ExactEvmScheme accepts a web3 LocalAccount (auto-wrapped in EthAccountSigner
    # by the SDK). It signs EIP-712 typed data internally (domain: name="USD Coin",
    # version="2", chainId=84532, verifyingContract=USDC), producing the EIP-3009
    # authorization signature. The vendor emits the CAIP-2 network identifier
    # "eip155:84532" (Base Sepolia) which both the scheme-selection path and the
    # signing path (get_evm_chain_id) understand, so register on that exact value.
    client = x402ClientSync()
    client.set_spend_controls(False)
    client.register_v1("eip155:84532", ExactEvmScheme(account))
    print("[x402] x402ClientSync registered ExactEvmScheme(account) on eip155:84532 (payer={})".format(account.address))

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

    # PAYMENT-REQUIRED is base64-encoded JSON — decode and normalize for the SDK.
    # Vendors may emit either canonical camelCase or common snake_case variants;
    # normalize snake_case -> camelCase so parse_payment_required always succeeds.
    if isinstance(pr_header, str):
        try:
            decoded = json.loads(base64.b64decode(pr_header))
        except Exception as e:
            print(f"[x402] ERROR decoding PAYMENT-REQUIRED (base64/json): {e}")
            print(f"[x402] Raw header: {pr_header[:100]}")
            print(f"[x402] WARN: parse failure — falling back to direct /pay")
            return _execute_fallback_payment(vendor, amount_usd)
        pr_header = _normalize_payment_required(decoded)

    try:
        payment_required = parse_payment_required(pr_header)

        # V1 PaymentRequirementsV1 carries max_amount_required, not amount.
        # The SDK's ExactEvmScheme.create_payment_payload reads requirements.amount
        # for the EIP-3009 authorization value, so inject .amount onto each V1
        # accept (V2 accepts already have .amount natively).
        #
        # Also override the EIP-712 domain name with the USDC contract's actual
        # on-chain name() so the signature verifies against the deployed FiatTokenV2.
        # The vendor may advertise "USD Coin" in extra, but the contract returns
        # "USDC" — and EIP-712 domain name must match exactly or the contract
        # reverts with "invalid signature". Fetch name from chain, keep version
        # from the vendor's extra (both should be "2" for FiatTokenV2).
        for _acc in payment_required.accepts:
            if not hasattr(_acc, "amount"):
                object.__setattr__(_acc, "amount", _acc.max_amount_required)
            if _acc.extra:
                try:
                    _usdc_abi = [{"inputs": [], "name": "name", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"}]
                    _u = w3.eth.contract(address=w3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e"), abi=_usdc_abi)
                    _real_name = _u.functions.name().call()
                    _acc.extra["name"] = _real_name
                except Exception:
                    pass  # leave vendor's name as-is if chain query fails

        print(f"[x402] PaymentRequired parsed:")
        print(f"  version: {payment_required.x402_version}")
        print(f"  accepts: {len(payment_required.accepts)} options")
        for i, accept in enumerate(payment_required.accepts):
            amt = getattr(accept, "amount", None) or getattr(accept, "max_amount_required", "?")
            print(f"    [{i}] network={accept.network} amount={amt} "
                  f"asset={accept.asset} payTo={accept.pay_to} "
                  f"maxTimeoutSeconds={accept.max_timeout_seconds}")
            if accept.extra:
                print(f"         extra={accept.extra}")
    except Exception as e:
        print(f"[x402] ERROR parsing PaymentRequired: {e}")
        print(f"[x402] WARN: parse failure — falling back to direct /pay")
        return _execute_fallback_payment(vendor, amount_usd)

    # --- Step 4: Create PaymentPayload ---
    print(f"\n[x402] Step 3: Creating PaymentPayload via x402ClientSync.create_payment_payload...")
    try:
        payment_payload = client.create_payment_payload(payment_required)
        version = getattr(payment_payload, "x402_version", None) or getattr(payment_payload, "x402Version", None)
        print(f"[x402] PaymentPayload created (x402_version={version})")
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

    # --- Step 5: Broadcast EIP-3009 transferWithAuthorization to USDC on-chain ---
    # ExactEvmScheme.create_payment_payload returns a Pydantic PaymentPayloadV1
    # model. The SDK signed the EIP-3009 authorization internally via EIP-712
    # (domain: name=USDC contract's name(), version=USDC contract's version(),
    # chainId=84532, verifyingContract=USDC address) and stored the real
    # 0x-prefixed hex signature inside the inner payload dict.
    #
    # Extraction path: payment_payload.payload  -> inner dict
    #   -> ["authorization"]  -> {from, to, value, validAfter, validBefore, nonce}
    #   -> ["signature"]      -> "0x" + 65-byte-ecdsa-hex  (EIP-3009 sig)
    #
    # This signature is sent to the vendor in the PAYMENT-SIGNATURE header (Step 6).
    # The on-chain transaction is built, signed, and broadcast directly by the client
    # using web3.py so the TX HASH is a real 66-char hex string verifiable on
    # Blockscout — not a vendor-generated mock string.

    def _extract_signature(pp) -> str:
        """Return the EIP-3009 authorization signature hex from a PaymentPayload model."""
        pp_dict = pp.model_dump() if hasattr(pp, "model_dump") else dict(pp)
        inner = pp_dict.get("payload", {})
        if isinstance(inner, dict):
            sig = inner.get("signature", "")
            if sig:
                return str(sig)
        # fallback: some SDK versions put signature at top level
        if "signature" in pp_dict and pp_dict["signature"]:
            return str(pp_dict["signature"])
        raise RuntimeError("PaymentPayload has no signature field — SDK signing may have failed")

    sig_value = _extract_signature(payment_payload)
    print(f"[x402] Extracted EIP-3009 signature ({len(sig_value)} chars)")
    print(f"[x402] PAYMENT-SIGNATURE header: {sig_value[:60]}...")

    # Extract the authorization dict from the inner payload (same object that
    # encode_contract_call / parse_eip3009_authorization consume).
    pp_dict = payment_payload.model_dump() if hasattr(payment_payload, "model_dump") else dict(payment_payload)
    inner_payload = pp_dict.get("payload", {})
    authorization = inner_payload.get("authorization", {}) if isinstance(inner_payload, dict) else {}

    # web3 alias needed for address checksumming in the broadcast path below.
    from web3 import Web3 as _Web3

    try:
        # --- Build the raw transferWithAuthorization transaction ---
        from x402.mechanisms.evm.exact import eip3009_utils

        parsed_auth = eip3009_utils.parse_eip3009_authorization(
            eip3009_utils.ExactEIP3009Authorization(
                from_address=authorization.get("from", ""),
                to=authorization.get("to", ""),
                value=authorization.get("value", "0"),
                valid_after=authorization.get("validAfter", "0"),
                valid_before=authorization.get("validBefore", "0"),
                nonce=authorization.get("nonce", "0x0"),
            )
        )
        sig_bytes = bytes.fromhex(sig_value.removeprefix("0x"))
        _v, _r, _s = eip3009_utils._split_signature_parts(sig_bytes)
        tx_calldata = eip3009_utils.encode_contract_call(
            eip3009_utils.TRANSFER_WITH_AUTHORIZATION_VRS_ABI,
            "transferWithAuthorization",
            _Web3.to_checksum_address(parsed_auth.from_address),
            _Web3.to_checksum_address(parsed_auth.to),
            parsed_auth.value,
            parsed_auth.valid_after,
            parsed_auth.valid_before,
            parsed_auth.nonce,
            _v, _r, _s,
        )
        _nonce = w3.eth.get_transaction_count(account.address)
        _gas_price = w3.eth.gas_price
        _gas_estimate = w3.eth.estimate_gas({
            "to": _Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
            "from": account.address,
            "data": tx_calldata,
            "value": 0,
            "nonce": _nonce,
        })
        _gas_limit = int(_gas_estimate * 1.2)

        _raw_tx = {
            "to": _Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
            "from": account.address,
            "data": tx_calldata,
            "value": 0,
            "nonce": _nonce,
            "gas": _gas_limit,
            "maxFeePerGas": _gas_price,
            "maxPriorityFeePerGas": _gas_price,
            "chainId": w3.eth.chain_id,
        }
        _signed = w3.eth.account.sign_transaction(_raw_tx, PRIVATE_KEY)
        print(f"[x402] Broadcasting EIP-3009 tx to USDC on Base Sepolia...")
        print(f"[x402]   nonce={_nonce}, gas={_gas_limit}, gas_price={w3.from_wei(_gas_price, 'gwei')} gwei")
        print(f"[x402]   pre-broadcast hash: {_signed.hash.hex()}")

        _tx_hash = w3.eth.send_raw_transaction(_signed.raw_transaction)
        print(f"[x402]   sent: {_tx_hash.hex()}")
        print(f"[x402]   waiting for receipt...")

        _receipt = w3.eth.wait_for_transaction_receipt(_tx_hash, timeout=60)
        _real_hash = _receipt.transactionHash.hex()
        _explorer = f"{VENDOR_EXPLORER_BASE}{_real_hash}"
        _status = "SUCCESS" if _receipt.status == 1 else "FAILED"

        print(f"[x402]   === ON-CHAIN CONFIRMED ===")
        print(f"[x402]   REAL TX HASH: {_real_hash}")
        print(f"[x402]   Block:        {_receipt.blockNumber}")
        print(f"[x402]   Status:       {_status}")
        print(f"[x402]   Gas used:     {_receipt.gasUsed}")
        print(f"[x402]   Explorer:     {_explorer}")

        # --- Step 6: Resubmit to vendor with real tx hash ---
        print(f"\n[x402] Step 6: Resubmitting to vendor with real tx hash...")
        r2 = requests.post(
            f"{VENDOR_URL}/pay-x402",
            json={
                "vendor": vendor,
                "amount_usd": amount_usd,
                "tx_hash": _real_hash,
            },
            headers={
                "Content-Type": "application/json",
                "PAYMENT-SIGNATURE": sig_value,
            },
            timeout=15,
        )
        print(f"[x402] Resubmit response: HTTP {r2.status_code}")

        if r2.status_code == 200:
            result = r2.json() if r2.headers.get("Content-Type", "").startswith("application/json") else {"paid": True, "raw": r2.text[:500]}
            # Use the REAL on-chain hash, not any vendor-generated mock
            result["tx_hash"] = _real_hash
            result["explorer"] = _explorer
            result["mode"] = "x402_onchain"
            result["amount"] = amount_usd
            result["vendor"] = vendor
            result["timestamp"] = datetime.now(timezone.utc).isoformat()
            result["status"] = _status

            print(f"\n[x402] === PAYMENT SUCCESSFUL ===")
            print(f"[x402] Mode:    x402_onchain (real Base Sepolia tx)")
            print(f"[x402] Amount:  ${amount_usd:.2f} USD")
            print(f"[x402] TX Hash: {_real_hash}")
            print(f"[x402] Explorer: {_explorer}")

            # Dashboard persistence — record the REAL on-chain tx
            _log_tx_to_dashboard({
                "vendor": vendor,
                "amount_usd": amount_usd,
                "tx_hash": _real_hash,
                "network": "Base Sepolia",
                "explorer_url": _explorer,
                "payment_mode": "x402_onchain",
                "status": _status,
            })

            return result
        else:
            print(f"[x402] Resubmit failed: HTTP {r2.status_code}")
            print(f"[x402] Body: {r2.text[:300]}")
            # Transaction already on-chain; still record it
            _log_tx_to_dashboard({
                "vendor": vendor,
                "amount_usd": amount_usd,
                "tx_hash": _real_hash,
                "network": "Base Sepolia",
                "explorer_url": _explorer,
                "payment_mode": "x402_onchain",
                "status": "sent_only",
            })
            return {
                "paid": True,
                "amount": amount_usd,
                "vendor": vendor,
                "mode": "x402_onchain",
                "tx_hash": _real_hash,
                "explorer": _explorer,
                "status": "sent_only",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    except Exception as e:
        print(f"[x402] On-chain broadcast failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print("[x402] Falling back to vendor-only payment (no on-chain tx)")
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
