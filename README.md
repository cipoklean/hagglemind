# HaggleMind — Autonomous Bill Negotiator

An autonomous background agent that negotiates your recurring bills and subscriptions. It remembers every negotiation per vendor, rewrites its own confidence in each tactic based on results, and pays the settled price on-chain via x402 on Base.

Built for the **Sibyl Labs Hackathon**.

---

## The Deletion Test (Read This First)

The judges will apply the deletion test:

> "Delete the memory layer. If your project still does what it claims, it is a wrapper and does not qualify."

Here is exactly what happens:

**WITH memory (normal run):**
1. Agent sees Comcast invoice for $120/month.
2. Queries Sibyl Memory. Remembers "competitor_promo" worked last month at 90% confidence.
3. Uses competitor_promo tactic: "I can switch to a competitor offering $70/month."
4. Vendor accepts. New price: $75/month.
5. Agent pays $75 via x402 on Base.
6. Memory updates: competitor_promo confidence += delta.

**WITHOUT memory (wiped):**
1. Agent sees Comcast invoice for $120/month.
2. Memory is empty. No tactic history.
3. Agent picks a generic default tactic: "Can you offer any discounts?"
4. Vendor rejects. No discount.
5. Agent pays full $120 via x402 on Base.
6. **The agent literally paid $45 more because memory was wiped.**

Memory is load-bearing. The agent loses real money without it.

---

## Project Structure

```
hagglemind/
├── README.md              # This file
├── memory.json            # Sibyl Memory — vendor tactic confidence store
├── vendor_server.py       # Mock Vendor API (simulates Comcast, Netflix, etc.)
├── agent.py               # The negotiation agent (reads memory, negotiates, pays)
├── x402_payment.py        # x402 payment wrapper (Base-ready, simulated in dev)
├── haggle_cli.py          # Time-Machine Simulator CLI
├── deletion_test.py       # Automated deletion test script
├── requirements.txt       # Python dependencies
└── .env                   # Config (private key, vendor URL, etc.)
```

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the Mock Vendor API

```bash
python vendor_server.py
```

The vendor server listens on `http://localhost:8777` by default.

### 3. Run the Time-Machine Simulator

```bash
# Inject an invoice
python haggle_cli.py inject_invoice --vendor "Comcast" --amount 120

# Run the agent (negotiates + pays)
python haggle_cli.py run

# Check status
python haggle_cli.py status

# Fast-forward 30 days and run again
python haggle_cli.py fast_forward --days 30
python haggle_cli.py run

# Chaos test: randomly change vendor rules so a tactic stops working
python haggle_cli.py chaos --vendor "Comcast"

# Wipe memory (triggers deletion test)
python haggle_cli.py wipe_memory
python haggle_cli.py run   # Agent now pays full price — memory was load-bearing
```

### 4. Run the automated deletion test

```bash
python deletion_test.py
```

This script:
1. Wipes memory
2. Runs the agent
3. Records the price paid (full price — no discount)
4. Restores memory  
5. Runs the agent again
6. Records the price paid (discounted — memory helped)
7. Prints a diff showing the agent lost money without memory

---

## How Memory Works

`memory.json` stores per-vendor tactic confidence scores:

```json
{
  "Comcast": {
    "competitor_promo": {
      "confidence": 0.90,
      "successes": 3,
      "failures": 0,
      "last_used": "2026-09-03T10:00:00"
    },
    "loyalty_discount": {
      "confidence": 0.60,
      "successes": 1,
      "failures": 1,
      "last_used": "2026-09-01T10:00:00"
    },
    "budget_hardship": {
      "confidence": 0.35,
      "successes": 0,
      "failures": 2,
      "last_used": "2026-08-28T10:00:00"
    }
  }
}
```

The agent reads this file before every negotiation. It picks the tactic with the highest confidence score. After the negotiation, it updates the score:

- **Success**: confidence += 0.10 (capped at 0.95)
- **Failure**: confidence -= 0.15 (floored at 0.05)

If a tactic's confidence drops below 0.20, the agent stops using it entirely until it recovers.

The `chaos` command simulates a vendor changing its hidden rules — a tactic that worked suddenly stops working. The agent detects the failure and rewrites its confidence downward automatically.

---

## The Negotiation Pipeline

```
Invoice arrives
  → Agent reads memory.json
  → Picks highest-confidence tactic for that vendor
  → Sends negotiation prompt to vendor API
  → Vendor accepts or rejects (based on hidden rules)
  → If accepted:
      → Agent pays negotiated price via x402 on Base
      → Updates tactic confidence upward in memory.json
  → If rejected:
      → Agent pays full price via x402 on Base
      → Updates tactic confidence downward in memory.json
```

---

## x402 Payment (Base)

The `x402_payment.py` module wraps the x402 HTTP payment flow:

1. Agent calls the vendor settlement endpoint with `X-Pay-Intent` header
2. x402 middleware returns a payment URI
3. Agent signs and submits the transaction on Base
4. Vendor confirms payment and settles the negotiated price

In development/simulation mode, the payment is logged but not broadcast. Switch to `MAINNET_MODE=true` in `.env` to enable real Base payments.

---

## 💰 Proof of Autonomy Dashboard

HaggleMind is not just a CLI; it includes a real-time verification dashboard that proves the agent's autonomous actions against persistent memory and on-chain settlement.

### How to run the dashboard:

1. Start the mock vendor server (Terminal 1):
   `python vendor_server.py`

2. Launch the Streamlit dashboard (Terminal 2):
   `streamlit run app.py`

3. Open `http://localhost:8501` in your browser.

### The 4 Verification Panels:
1. **The Brain (Sibyl Memory):** Live view of the agent's SQLite memory. Watch the `Confidence` scores update dynamically after every negotiation.
2. **The Action (Agent Logs):** Live feed of the agent's reasoning, tactic selection, and discount achievements.
3. **On-Chain Proof (Base Sepolia):** Live view of x402 payments. Click the "Open BaseScan" button to verify the exact negotiated amount was settled on-chain.
4. **Trigger:** Click "Run Negotiation Agent" to execute the agent and watch the panels update in real-time.

### The Deletion Test (Proving Memory is Load-Bearing):
1. In the dashboard's terminal or via CLI, run `python haggle_cli.py wipe_memory`.
2. Click "Run Negotiation Agent" again on the dashboard.
3. Observe the "Brain" panel: The agent has no memory, defaults to a weak tactic, and the "Action" panel will show a significantly higher payment amount. 
*Conclusion: Deleting Sibyl Memory materially degrades the agent's financial outcome. Memory is load-bearing.*

---

## Scoring Maximization

| Rubric Bucket | How HaggleMind Scores |
|---|---|
| Memory load-bearing (40 pts) | Deletion test proves agent pays more without memory |
| Innovation (25 pts) | Self-rewriting confidence scores + chaos testing |
| Technical execution (20 pts) | Working CLI, mock API, memory store, x402 wrapper |
| Pitch (15 pts) | Demo shows fresh-session recall moment clearly |
| PMF bonus (+10 pts) | Real pain point (bill negotiation) with working prototype |

Partner stacks:
- **Base (x1.15)**: x402 payment on Base for settled negotiations
- **Virtuals Protocol (x1.25)**: Can be added as agent runtime if desired

---

## License

MIT
