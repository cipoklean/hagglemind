# HaggleMind

An autonomous agent that negotiates your bills and pays on-chain. It remembers which tactics work with each vendor and uses that memory next month.

Built for the **Sibyl Labs Hackathon**.

---

## How It Works

### The Problem

You call Comcast every year, say the same thing, get the same result. Unless you've been keeping score.

### The Solution

HaggleMind keeps score. After each negotiation it remembers what worked. Next invoice arrives, it picks the highest-confidence tactic automatically.

### The Proof

Run `python deletion_test.py`. Same $120 invoice. Two runs:

- **With memory:** Uses competitor_promo (95% confidence). Pays $72.
- **Without memory:** Falls back to loyalty_discount (0% confidence). Pays $120.

Delete the memory, lose $48. That's the point.

---

## Quickstart

Three terminals open at once:

```bash
# Terminal 1 — Mock vendor
python vendor_server.py

# Terminal 2 — API backend
python -m uvicorn api:app --port 8000

# Terminal 3 — Frontend
cd frontend && npm run dev
```

Open `http://localhost:5173`.

### CLI Commands

```bash
python haggle_cli.py inject_invoice --vendor "Comcast" --amount 120
python haggle_cli.py run

python haggle_cli.py fast_forward --days 30
python haggle_cli.py run

python haggle_cli.py reset
```

### Run the Deletion Test

```bash
python deletion_test.py
```

Auto-runs everything: seeds memory, negotiates twice (with/without), prints if memory was load-bearing.

---

## What's Under the Hood

| Component | What it does |
|-----------|--------------|
| `agent.py` | Reads memory, picks tactic, negotiates, decides payment path |
| `sibyl_memory.py` | Wraps Sibyl Memory SDK — all reads/writes go through SQLite |
| `vendor_server.py` | Simulates Comcast/Netflix/etc. Hidden rules determine accept/reject |
| `x402_payment.py` | On-chain payments via x402 protocol on Base Sepolia |
| `haggle_cli.py` | Time-machine simulator — fast-forward months, inject chaos, wipe memory |
| `frontend/index.html` | Single-file dashboard |

---

## Memory Architecture

Uses the real **Sibyl Memory SDK**. No JSON files — everything goes through SQLite.

**Confidence update rules:**
- Success: +0.10 (cap at 0.95)
- Failure: -0.15 (floor at 0.05)
- Tactics below 0.20 confidence are ignored until recovery

---

## License

MIT
