# HaggleMind

An autonomous agent that negotiates your bills and pays the negotiated price on-chain.

It keeps a memory of every vendor — what worked, what failed, what it cost — and lets that memory change the price it pays next month.

Built for the **Sibyl Labs Hackathon**.

---

## How It Works

### The Problem

Bill negotiations are repetitive. You call Comcast every year, you say the same thing, and you get the same result — unless you've been keeping score.

### The Solution

HaggleMind keeps score. After each negotiation, it remembers which tactics landed and which didn't. Next time an invoice arrives, it uses that history to pick the highest-confidence approach.

### The Deletion Test

This is the proof that memory matters:

**With memory:** Agent sees a $120 Comcast invoice. Recalls that "competitor_promo" has worked 95% of the time. Uses that tactic. Pays $72.

**Without memory:** Same invoice. Agent has no history. Picks a weak default tactic. Vendor rejects it. Pays full $120.

Delete the memory, lose $48. The memory is load-bearing.

---

## Setup

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

## Quickstart

Three things running at once:

```bash
# Terminal 1 — Mock vendor server
python vendor_server.py

# Terminal 2 — API backend
python -m uvicorn api:app --port 8000

# Terminal 3 — Frontend
cd frontend && npm run dev
```

Then open `http://localhost:5173`.

### CLI Commands

```bash
# Inject a bill, run the agent
python haggle_cli.py inject_invoice --vendor "Comcast" --amount 120
python haggle_cli.py run

# Fast-forward time and negotiate again
python haggle_cli.py fast_forward --days 30
python haggle_cli.py run

# Reset everything to clean slate
python haggle_cli.py reset
```

### Run the Deletion Test

```bash
python deletion_test.py
```

This script runs the full test automatically: sets deterministic rules, seeds memory, runs the agent twice (with and without memory), and prints whether the memory was load-bearing.

---

## What's Under the Hood

| Component | What it does |
|-----------|--------------|
| `agent.py` | Reads memory, picks tactic, negotiates with vendor, decides payment path |
| `sibyl_memory.py` | Wraps the Sibyl Memory SDK. Every read/write goes through here. |
| `vendor_server.py` | Simulates Comcast/Netflix/etc. Hidden rules determine accept/reject. |
| `x402_payment.py` | On-chain payments via x402 protocol on Base Sepolia (falls back to mock). |
| `haggle_cli.py` | Time-Machine Simulator — fast-forward months, inject chaos, wipe memory. |
| `frontend/index.html` | Single-file dashboard: memory view, live terminal, on-chain proof table. |

---

## Memory Architecture

HaggleMind uses the real **Sibyl Memory SDK** (`sibyl-memory-client`). No JSON files — all reads/writes go through SQLite.

**Two tiers matter:**

- **WARM entities** — per-vendor tactic confidence scores. `Competitor_promo`, `Loyalty_discount`, etc. Each has a confidence value that updates after every negotiation.
- **COLD journal** — append-only audit trail of every negotiation event.

The confidence update rules:
- **Success:** +0.10 (capped at 0.95)
- **Failure:** -0.15 (floored at 0.05)
- **Skip threshold:** Tactics below 0.20 confidence are ignored until they recover

---

## Payment Flow

**Real path** (when `X402_ENABLED=true`):
1. Vendor returns HTTP 402 + `PAYMENT-REQUIRED` header
2. Agent creates x402 payment payload via SDK
3. Agent signs EIP-3009 authorization with web3
4. Agent submits signature to vendor
5. Vendor settles on Base Sepolia, returns tx hash + BaseScan link

**Fallback** (dev mode):
- Direct `/pay` endpoint on vendor server
- No on-chain transaction, no explorer link
- Labeled `direct_api` or `simulated` in logs

---

## Project Structure

```
hagglemind/
├── agent.py               # Negotiation agent
├── sibyl_memory.py        # Memory SDK wrapper
├── vendor_server.py       # Mock vendor API (port 8777)
├── x402_payment.py        # On-chain payment logic
├── haggle_cli.py          # CLI for time-machine simulation
├── deletion_test.py       # Automated deletion test
├── api.py                 # FastAPI backend (port 8000)
├── frontend/              # Vanilla JS frontend (port 5173)
│   └── index.html         # Single-file editorial UI
└── requirements.txt
```

---

## License

MIT
