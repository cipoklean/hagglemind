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
├── sibyl_memory.py        # Sibyl Memory SDK wrapper (sibyl-memory-client, SQLite-backed)
├── sibyl_memory.db        # SQLite store managed by the Sibyl Memory SDK
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

HaggleMind's memory is backed by the real **Sibyl Memory SDK** (`sibyl-memory-client`), stored in a local SQLite database (`sibyl_memory.db`). There is no JSON file — every read and write goes through the SDK.

The SDK implements a five-tier memory schema (HOT/WARM/COLD/REFERENCE/ARCHIVE). HaggleMind uses two tiers:

- **WARM (entities)** — per-vendor tactic confidence scores. This is the load-bearing memory. Each entity is keyed `Vendor::Tactic` and carries `confidence`, `successes`, `failures`, and `last_used`.
- **COLD (journal)** — append-only negotiation event log. Every negotiation writes an evaluated/acted event pair for auditability.

The agent's memory wrapper is `sibyl_memory.py`, which exposes a `SibylMemoryStore` class. All agent code routes through it:

```python
from sibyl_memory import get_store

mem = get_store()

# Load-bearing recall — returns {} if memory was wiped
tactics = mem.get_vendor_tactics("Comcast")
tactic = mem.pick_tactic("Comcast")          # highest-confidence active tactic

# Self-modifying write — confidence goes up on success, down on failure
new_confidence = mem.update_after_negotiation("Comcast", "competitor_promo", success=True)

# Audit trail
mem.log_negotiation(vendor="Comcast", tactic="competitor_promo",
                    original_amount=120.0, final_amount=75.0,
                    accepted=True, confidence_before=0.90, confidence_after=0.95)
```

The confidence update rules:

- **Success**: confidence += 0.10 (capped at 0.95)
- **Failure**: confidence -= 0.15 (floored at 0.05)
- **Threshold**: tactics below 0.20 confidence are skipped until they recover

The `chaos` command simulates a vendor changing its hidden rules — a tactic that worked suddenly stops working. The agent detects the failure and rewrites its confidence downward automatically via the SDK.

The `wipe_memory` CLI command deletes all WARM entities through the SDK (`client.delete_entity` for every active vendor tactic). After a wipe, `get_vendor_tactics` returns an empty dict and the agent falls back to its default tactic — which produces a materially worse financial outcome. That is the deletion test.

---

## The Negotiation Pipeline

```
Invoice arrives
  → Agent queries Sibyl Memory via SDK (get_vendor_tactics + pick_tactic)
  → Picks highest-confidence active tactic for that vendor
  → Sends negotiation prompt to vendor API
  → Vendor accepts or rejects (based on hidden rules)
  → If accepted:
      → Agent pays negotiated price via x402 on Base (or direct /pay fallback)
      → Sibyl Memory updates tactic confidence upward via SDK (update_after_negotiation)
      → Negotiation event written to COLD journal (log_negotiation)
  → If rejected:
      → Agent pays full price
      → Sibyl Memory updates tactic confidence downward via SDK
      → Negotiation event written to COLD journal
```

All memory reads (`get_vendor_tactics`, `pick_tactic`, `get_tactic`) and writes (`set_vendor_tactic`, `update_after_negotiation`, `delete_entity`, `log_negotiation`) go through `sibyl_memory.py` → `sibyl-memory-client` SDK → `sibyl_memory.db` (SQLite). No code path reads or writes a JSON file.

---

## x402 Payment (Base Sepolia)

The `x402_payment.py` module executes real on-chain micropayments via the x402 protocol on Base Sepolia. The flow:

1. Agent POSTs to the vendor's `/pay-x402` endpoint
2. x402 middleware returns HTTP 402 + a `PAYMENT-REQUIRED` header (base64-encoded `PaymentRequired`)
3. Agent parses `PaymentRequired` via the x402 SDK (`parse_payment_required`)
4. Agent creates a `PaymentPayload` via `x402ClientSync.create_payment_payload`
5. Agent signs the payload with web3.py (EIP-191 via `hash_message` + `sign_hash`, signature hex)
6. Agent resubmits the POST with a `PAYMENT-SIGNATURE` header
7. Vendor verifies on-chain, settles, and returns the transaction hash + BaseScan explorer link

The real path is enabled when `X402_ENABLED=true` in `.env`. It requires:

- `PRIVATE_KEY` — the payer's Base Sepolia private key (the agent derives the wallet address from it)
- `BASE_RPC` — Base Sepolia RPC endpoint (default `https://sepolia.base.org`)
- `VENDOR_BURNER_WALLET` — the destination address on Base Sepolia where the payment settles

When `X402_ENABLED=false`, the module falls back to the vendor's direct `/pay` endpoint. The fallback is labeled `direct_api` or `simulated` in the dashboard — it never prints a `[SIM]` tag or pretends to be on-chain.

Payment results are logged to the dashboard's `transactions` table on every path (real x402, direct API, simulated fallback) via `persistence.log_transaction()`.

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
