"""
HaggleMind FastAPI Backend Bridge

Bridges the existing Python agent (agent.py / x402_payment.py / sibyl_memory.py /
persistence.py) to a React frontend over HTTP.  Runs on port 8000 by default.

Endpoints
---------
GET  /api/memory          — Sibyl Memory vendor tactics + confidence scores
GET  /api/logs            — agent_logs + transactions tables from hagglemind.db
POST /api/run             — trigger negotiate_all_vendors() synchronously
                            (frontend should call with a fetch timeout and treat
                            a timeout as "run in progress, keep polling /api/logs")
GET  /api/chain-proof/{tx_hash} — live Base Sepolia RPC proof for a tx hash
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Make sure the project directory is on sys.path so we can import the existing
# HaggleMind modules (agent, persistence, sibyl_memory, x402_payment).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Load .env so VENDOR_URL / X402_ENABLED etc. are available to agent.py
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ---------------------------------------------------------------------------
# Import the HaggleMind modules we depend on
# ---------------------------------------------------------------------------
import persistence  # noqa: E402  # dashboard DB helpers
import sibyl_memory  # noqa: E402  # SDK-backed memory wrapper

# agent is imported lazily inside /api/run so startup is fast.

app = FastAPI(
    title="HaggleMind Backend Bridge",
    description="FastAPI bridge exposing HaggleMind agent + on-chain proof endpoints to the React frontend",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite dev server (port 5173) and any localhost origin
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Health
# ===========================================================================

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "hagglemind-api",
    }


# ===========================================================================
# /api/memory — Sibyl Memory vendor tactics + confidence
# ===========================================================================

@app.get("/api/memory")
def get_memory() -> dict[str, Any]:
    """Return every vendor's tactic confidence data from Sibyl Memory (SDK-backed).

    Shape:
        { "vendors": { "Comcast": { "competitor_promo": { "confidence": 0.90,
                                                            "successes": 3,
                                                            "failures": 0 },
                                     ... },
                       ... } }
    """
    try:
        mem = sibyl_memory.get_store()
        vendors: dict[str, dict[str, Any]] = {}
        entities = mem.client.list_entities(category="vendor", status="active", limit=500)
        for ent in entities:
            name = ent.get("name", "")
            if "::" not in name:
                continue
            v, tactic = name.split("::", 1)
            body = ent.get("body", {})
            vendors.setdefault(v, {})[tactic] = {
                "confidence": body.get("confidence", 0.0),
                "successes": body.get("successes", 0),
                "failures": body.get("failures", 0),
                "last_used": body.get("last_used", ""),
            }
        return {"vendors": vendors, "count": sum(len(v) for v in vendors.values())}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read Sibyl Memory: {exc}")


# ===========================================================================
# /api/logs — agent_logs + transactions
# ===========================================================================

class LogsResponse(BaseModel):
    agent_logs: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


@app.get("/api/logs", response_model=LogsResponse)
def get_logs(limit: int = 50) -> LogsResponse:
    """Return the most recent agent negotiation logs and payment transactions."""
    try:
        agent_logs = persistence.get_agent_logs(limit=limit)
        transactions = persistence.get_transactions(limit=limit)
        # Normalise tx_hash: web3 receipt.transactionHash.hex() returns the
        # hex WITHOUT the 0x prefix; our frontend's isRealHash() requires a
        # 66-char 0x-prefixed string.  Prepend 0x for real hashes stored
        # without it.
        for t in transactions:
            h = t.get("tx_hash", "")
            if h and not h.startswith("0x"):
                t["tx_hash"] = "0x" + h
        for log in agent_logs:
            h = log.get("tx_hash", "")
            if h and not h.startswith("0x"):
                log["tx_hash"] = "0x" + h
        return LogsResponse(agent_logs=agent_logs, transactions=transactions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {exc}")


# ===========================================================================
# /api/run — synchronous agent trigger
#
# NOTE: a full negotiation run takes ~20-40s (4 vendors * ~5s each).  The
# frontend should call this endpoint with a generous fetch timeout (e.g. 60s),
# or call it and immediately start polling /api/logs for the action_steps to
# appear.  If the fetch times out, the run is still in progress on the server.
# ===========================================================================

class RunRequest(BaseModel):
    vendor: str | None = None  # if None → run all vendors


class RunResponse(BaseModel):
    started: bool
    message: str
    vendor: str | None = None


@app.post("/api/run", response_model=RunResponse)
def trigger_run(req: RunRequest | None = None) -> RunResponse:
    """Kick off a negotiation run, same as `haggle_cli.py run`.

    Blocks until the run finishes.  For a non-blocking UX, the frontend should
    call this from a worker thread / with a long fetch timeout, then poll
    /api/logs to watch the Console fill up.
    """
    vendor = req.vendor if req else None
    try:
        from agent import negotiate_bill, negotiate_all_vendors

        if vendor:
            sibyl_memory.reset_store()
            negotiate_bill(vendor)
            return RunResponse(
                started=True,
                message=f"Negotiation complete for {vendor}",
                vendor=vendor,
            )
        else:
            sibyl_memory.reset_store()
            negotiate_all_vendors()
            return RunResponse(
                started=True,
                message="Negotiation run complete for all vendors",
                vendor=None,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent run failed: {exc}")


# ===========================================================================
# /api/chain-proof/{tx_hash} — REAL on-chain verification via Base Sepolia RPC
# ===========================================================================

class ChainProofResponse(BaseModel):
    verified: bool
    hash: str
    network: str
    raw: dict[str, Any] | None = None
    error: str | None = None


@app.get("/api/chain-proof/{tx_hash}", response_model=ChainProofResponse)
def verify_on_chain(tx_hash: str) -> ChainProofResponse:
    """Fetch a REAL transaction receipt from Base Sepolia and return parsed proof.

    Returns verified=true with blockNumber, gasUsed, timestamp, and parsed USDC
    Transfer logs (from, to, value) when the hash is a real 66-char 0x-prefixed
    hex found on-chain.  Returns verified=false for mock/vendor-marker hashes
    (e.g. 0x_vendor_x402_...) or any hash not found on Base Sepolia.
    """
    # --- Sanity check: real tx hashes are 66-char 0x-prefixed hex ---
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        return ChainProofResponse(
            verified=False,
            hash=tx_hash,
            network="Base Sepolia",
            error="Not a real 66-char hex tx hash — likely a vendor mock marker",
        )
    try:
        int(tx_hash, 16)
    except ValueError:
        return ChainProofResponse(
            verified=False,
            hash=tx_hash,
            network="Base Sepolia",
            error="Hash is not valid hexadecimal",
        )

    # --- Connect to Base Sepolia and fetch the receipt ---
    try:
        from web3 import Web3

        rpc = os.environ.get("BASE_RPC", "https://sepolia.base.org")
        rpc_url = rpc
        apikey = os.environ.get("BASE_RPC_KEY", "")
        if apikey and "?" not in rpc_url:
            rpc_url = f"{rpc}?apikey={apikey}"

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
        if not w3.is_connected():
            return ChainProofResponse(
                verified=False,
                hash=tx_hash,
                network="Base Sepolia",
                error=f"Cannot connect to RPC: {rpc}",
            )

        receipt = w3.eth.get_transaction_receipt(tx_hash)

        if receipt is None:
            return ChainProofResponse(
                verified=False,
                hash=tx_hash,
                network="Base Sepolia",
                error="Transaction not found on Base Sepolia",
            )

        status = "SUCCESS" if receipt["status"] == 1 else "FAILED"

        # --- Parse USDC Transfer logs from the receipt ---
        usdc_address = os.environ.get(
            "USDC_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
        )
        usdc_checksum = Web3.to_checksum_address(usdc_address)

        TRANSFER_ABI = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": True, "name": "to", "type": "address"},
                    {"indexed": False, "name": "value", "type": "uint256"},
                ],
                "name": "Transfer",
                "type": "event",
            }
        ]

        usdc_contract = w3.eth.contract(address=usdc_checksum, abi=TRANSFER_ABI)
        transfer_logs: list[dict[str, Any]] = []
        for log in receipt.get("logs", []):
            if log.get("address", "").lower() == usdc_checksum.lower():
                try:
                    evt = usdc_contract.events.Transfer().process_log(log)
                    transfer_logs.append(
                        {
                            "from": evt["args"]["from"],
                            "to": evt["args"]["to"],
                            "value": evt["args"]["value"],
                            "value_usd": float(
                                w3.from_wei(evt["args"]["value"], "mwei")
                            ),
                        }
                    )
                except Exception:
                    pass

        return ChainProofResponse(
            verified=True,
            hash=tx_hash,
            network="Base Sepolia",
            raw={
                "blockNumber": receipt["blockNumber"],
                "gasUsed": receipt["gasUsed"],
                "timestamp": w3.eth.get_block(receipt["blockNumber"])["timestamp"],
                "status": status,
                "from": receipt.get("from", ""),
                "to": receipt.get("to", ""),
                "value": receipt.get("value", 0),
                "value_eth": float(w3.from_wei(receipt.get("value", 0), "ether")),
                "transactionIndex": receipt.get("transactionIndex"),
                "gasPrice": receipt.get("gasPrice"),
                "effectiveGasPrice": receipt.get("effectiveGasPrice"),
                "cumulativeGasUsed": receipt.get("cumulativeGasUsed"),
                "logs": transfer_logs,
                "log_count": len(transfer_logs),
                "base_scan_url": f"https://sepolia.basescan.org/tx/{tx_hash}",
            },
        )

    except Exception as exc:
        return ChainProofResponse(
            verified=False,
            hash=tx_hash,
            network="Base Sepolia",
            error=f"RPC error: {exc}",
        )


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", "8000"))
    print(f"[api] Starting HaggleMind FastAPI backend on http://0.0.0.0:{port}")
    print(f"[api] Frontend should point to http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
