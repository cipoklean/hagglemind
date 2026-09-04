"""
HaggleMind Proof-of-Autonomy Verification Dashboard
====================================================

Streamlit app that verifies the agent's actions against real data.

Panels:
  1. THE BRAIN   — Sibyl Memory (SQLite) vendor tactic confidence table
  2. THE ACTION  — Agent logs (latest negotiation detail)
  3. ON-CHAIN    — Base Sepolia transactions + BaseScan verification link
  4. TRIGGER     — One-click "Run Negotiation Agent" button

Backend files used:
  - sibyl_memory.db  (sibyl-memory-client SQLite store)
  - hagglemind.db    (agent_logs + transactions tables, written by persistence.py)

Run:
  streamlit run app.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# Make sibling imports work regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Backend imports — all optional, best-effort
# ---------------------------------------------------------------------------
try:
    import sibyl_memory  # our wrapper around sibyl-memory-client SDK
except Exception as e:
    sibyl_memory = None
    st.warning(f"Sibyl Memory SDK unavailable: {e}")

try:
    import persistence  # agent_logs + transactions tables
except Exception as e:
    persistence = None
    st.warning(f"Persistence layer unavailable: {e}")

try:
    from persistence import (
        get_agent_logs,
        get_latest_agent_log,
        get_transactions,
        get_latest_transaction,
    )
except Exception as e:
    get_agent_logs = get_latest_agent_log = get_transactions = get_latest_transaction = None
    st.warning(f"Persistence helpers unavailable: {e}")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="HaggleMind · Proof of Autonomy",
    page_icon=":robot:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Theme — dark, readable
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    :root {
        --bg: #0e1117;
        --surface: #161b22;
        --border: #30363d;
        --text: #e6edf3;
        --muted: #8b949e;
        --accent: #58a6ff;
        --green: #3fb950;
        --red: #f85149;
        --orange: #d29922;
    }
    .appview-container { background: var(--bg) !important; }
    .main .block-container { background: var(--bg) !important; }
    h1, h2, h3, h4 { color: var(--text) !important; }
    .stDataFrame { background: var(--surface) !important; }
    .metric-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 12px;
        color: var(--text);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title(":robot: HaggleMind · Proof of Autonomy")
st.markdown(
    "Verification dashboard for the autonomous bill-negotiating agent. "
    "All data is read from local SQLite stores — no API calls out."
)

if not sibyl_memory or not persistence:
    st.error(
        "Missing backend dependencies. Make sure sibyl_memory.py and "
        "persistence.py are on the Python path and the required packages are installed."
    )

# ---------------------------------------------------------------------------
# Shared DB/file paths (so the dashboard reads the same files as the CLI)
# ---------------------------------------------------------------------------
DB_DIR = _HERE
SIBYL_DB = os.path.join(DB_DIR, "sibyl_memory.db")
DASHBOARD_DB = os.path.join(DB_DIR, "hagglemind.db")

# ---------------------------------------------------------------------------
# Helper: format a USD amount
# ---------------------------------------------------------------------------
def fmt_usd(v):
    try:
        return f"${float(v):,.2f}"
    except (ValueError, TypeError):
        return "—"


# ===========================================================================
# PANEL 1 — THE BRAIN (Sibyl Memory)
# ===========================================================================
st.header("🧠 The Brain — Sibyl Memory")

st.markdown(
    "Live per-vendor tactic confidence table from the real Sibyl Memory store "
    "(SQLite, via sibyl-memory-client SDK)."
)

col_refresh, col_empty = st.columns([1, 6])
refresh_clicked = col_refresh.button("🔄 Refresh Memory", type="primary")

if refresh_clicked or "brain_cached" not in st.session_state:
    st.session_state.brain_cached = datetime.now(timezone.utc).isoformat()
    brain_rows = []
    if sibyl_memory is not None:
        try:
            mem = sibyl_memory.SibylMemoryStore()
            entities = mem.client.list_entities("vendor", status="active", limit=200)
            vendors: dict[str, dict[str, dict]] = {}
            for ent in entities:
                name = ent.get("name", "")
                if "::" not in name:
                    continue
                v, tactic = name.split("::", 1)
                body = ent.get("body", {})
                vendors.setdefault(v, {})[tactic] = {
                    "confidence": body.get("confidence", 0),
                    "successes": body.get("successes", 0),
                    "failures": body.get("failures", 0),
                }
            mem.storage.close()

            for vendor in sorted(vendors):
                for tactic in sorted(vendors[vendor], key=lambda t: -vendors[vendor][t]["confidence"]):
                    d = vendors[vendor][tactic]
                    brain_rows.append({
                        "Vendor": vendor,
                        "Tactic": tactic,
                        "Success Count": d["successes"],
                        "Failure Count": d["failures"],
                        "Confidence": round(d["confidence"], 2),
                    })
        except Exception as e:
            st.error(f"Failed to read Sibyl Memory: {e}")

    if brain_rows:
        df_brain = pd.DataFrame(brain_rows)
        st.dataframe(
            df_brain,
            column_config={
                "Confidence": st.column_config.NumberColumn(
                    "Confidence", format=":.2f", width="120px"
                ),
                "Success Count": st.column_config.NumberColumn("Successes", format="{:}"),
                "Failure Count": st.column_config.NumberColumn("Failures", format="{:}"),
            },
            hide_index=True,
            width="stretch",
        )
        st.caption(f"{len(brain_rows)} tactic entries across {df_brain['Vendor'].nunique()} vendors.")
    else:
        st.info("No vendor entities found in Sibyl Memory. Run the agent to populate it.")

st.divider()


# ===========================================================================
# PANEL 2 — THE ACTION (Agent Logs)
# ===========================================================================
st.header("⚡ The Action — Agent Logs")

st.markdown(
    "Every negotiation the agent runs is written to the `agent_logs` table. "
    "The latest entry is shown below."
)

col_latest_vendor, col_refresh_logs = st.columns([2, 1])
vendor_filter = col_latest_vendor.text_input(
    "Filter by vendor (optional)",
    placeholder="e.g. Comcast",
    key="log_vendor",
).strip() or None
refresh_logs = col_refresh_logs.button("🔄 Refresh Logs", type="primary")

latest_log = None
if refresh_logs or "action_cached" not in st.session_state:
    st.session_state.action_cached = datetime.now(timezone.utc).isoformat()
    try:
        latest_log = get_latest_agent_log(vendor=vendor_filter)
    except Exception as e:
        st.error(f"Failed to read agent logs: {e}")

if latest_log:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Invoice Amount", fmt_usd(latest_log["original_amt"]))
    c2.metric("Selected Tactic", latest_log["tactic"])
    c3.metric("Negotiated Amount", fmt_usd(latest_log["final_amt"]))
    status_color = "green" if latest_log["accepted"] else "red"
    c4.metric(
        "Status",
        "SAVED" if latest_log["accepted"] else "NO SAVE",
        delta=f"-{fmt_usd(latest_log['savings'])}" if latest_log["savings"] > 0 else None,
    )

    st.markdown("---")
    col_v, col_t, col_conf, col_pm, col_tx = st.columns(5)
    col_v.metric("Vendor", latest_log["vendor"])
    col_t.metric("Tactic Used", latest_log["tactic"])
    col_conf.metric("Confidence Before", f"{latest_log.get('confidence_before', 0):.2f}")
    col_pm.metric("Payment Mode", latest_log.get("payment_mode", "unknown"))
    tx_val = latest_log.get("tx_hash") or "—"
    col_tx.metric("TX Hash", tx_val[:32] + "..." if isinstance(tx_val, str) and len(tx_val) > 34 else tx_val)

    st.markdown("### Recent Logs")
    try:
        history = get_agent_logs(limit=20, vendor=vendor_filter)
        if history:
            df_logs = pd.DataFrame(history)
            st.dataframe(
                df_logs[["timestamp", "vendor", "tactic", "original_amt", "final_amt", "savings", "accepted", "payment_mode", "tx_hash"]],
                column_config={
                    "original_amt": st.column_config.NumberColumn("Invoice $", format="$%.2f"),
                    "final_amt": st.column_config.NumberColumn("Paid $", format="$%.2f"),
                    "savings": st.column_config.NumberColumn("Saved $", format="$%.2f"),
                    "accepted": st.column_config.CheckboxColumn("Saved?"),
                    "tx_hash": st.column_config.TextColumn("TX Hash", width="160px"),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No agent logs yet. Run the agent to generate them.")
    except Exception as e:
        st.error(f"Failed to load log history: {e}")
else:
    st.info("No agent logs found. Run the agent via the Trigger panel or CLI first.")

st.divider()


# ===========================================================================
# PANEL 3 — ON-CHAIN PROOF (Base Sepolia)
# ===========================================================================
st.header("₿ On-Chain Proof — Base Sepolia")

st.markdown(
    "Every payment executed by the agent is recorded here. "
    "Click **Verify on BaseScan** to open the transaction in a new tab."
)

col_tx_vendor, col_refresh_tx = st.columns([2, 1])
tx_vendor_filter = col_tx_vendor.text_input(
    "Filter by vendor (optional)",
    placeholder="e.g. Comcast",
    key="tx_vendor",
).strip() or None
refresh_tx = col_refresh_tx.button("🔄 Refresh Transactions", type="primary")

latest_tx = None
if refresh_tx or "chain_cached" not in st.session_state:
    st.session_state.chain_cached = datetime.now(timezone.utc).isoformat()
    try:
        latest_tx = get_latest_transaction(vendor=tx_vendor_filter)
    except Exception as e:
        st.error(f"Failed to read transactions: {e}")

if latest_tx:
    tx_col1, tx_col2, tx_col3, tx_col4 = st.columns(4)
    tx_col1.metric("Amount Paid", fmt_usd(latest_tx["amount_usd"]))
    tx_col2.metric("Network", latest_tx.get("network", "Base Sepolia"))
    tx_col3.metric("TX Hash", latest_tx["tx_hash"][:32] + ("..." if len(latest_tx["tx_hash"]) > 34 else ""))
    pm = latest_tx.get("payment_mode", "unknown")
    tx_col4.metric("Mode", pm)

    st.markdown("---")
    st.markdown("### Verify on BaseScan")
    tx_hash = latest_tx.get("tx_hash", "")
    explorer = latest_tx.get("explorer_url") or f"https://sepolia.basescan.org/tx/{tx_hash}"
    if tx_hash and tx_hash.startswith("0x"):
        btn_cols = st.columns([1, 4])
        if btn_cols[0].button("🔗 Open BaseScan", type="primary"):
            import webbrowser
            webbrowser.open(explorer)
        btn_cols[1].markdown(
            f'<a href="{explorer}" target="_blank" style="color:var(--accent);text-decoration:none;">👉 {explorer}</a>',
            unsafe_allow_html=True,
        )
    else:
        st.warning("No valid Base Sepolia tx hash recorded. Run a real x402 payment to see it here.")

    st.markdown("### Recent Transactions")
    try:
        tx_history = get_transactions(limit=20, vendor=tx_vendor_filter)
        if tx_history:
            df_tx = pd.DataFrame(tx_history)
            st.dataframe(
                df_tx[["timestamp", "vendor", "amount_usd", "tx_hash", "network", "payment_mode", "status", "explorer_url"]],
                column_config={
                    "amount_usd": st.column_config.NumberColumn("Amount", format="$%.2f"),
                    "tx_hash": st.column_config.TextColumn("TX Hash", width="180px"),
                    "explorer_url": st.column_config.LinkColumn("BaseScan", width="200px"),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No transactions recorded yet. Run the agent to see on-chain (or simulated) payments here.")
    except Exception as e:
        st.error(f"Failed to load transaction history: {e}")
else:
    st.info("No transactions found. Run the agent (or a real x402 payment) to populate this panel.")

st.divider()


# ===========================================================================
# PANEL 4 — TRIGGER (Run Negotiation Agent)
# ===========================================================================
st.header("🎛️ Trigger — Run Negotiation Agent")

st.markdown(
    "Trigger the exact same negotiation logic as `python haggle_cli.py run`. "
    "The agent will process all pending invoices, update Sibyl Memory, "
    "pay via x402 (or simulated), and write logs + transactions."
)

vendor_to_run = st.selectbox(
    "Vendor to negotiate (or 'All' for the full run)",
    options=["All"] + ["Comcast", "Netflix", "Spotify", "DisneyPlus"],
    index=0,
    key="trigger_vendor",
)

run_clicked = st.button("▶ Run Negotiation Agent", type="primary", use_container_width=True)

if run_clicked:
    # Disable the button momentarily to avoid double-clicks
    st.session_state.trigger_running = True
    with st.spinner("🤖 HaggleMind is negotiating…"):
        try:
            from agent import negotiate_bill, negotiate_all_vendors
            from vendor_server import vendor_api as va  # type: ignore

            # Confirm vendor API is reachable
            health = va("GET", "/health")
            if "error" in health:
                st.error(f"Vendor API not reachable: {health['error']}")
                st.session_state.trigger_running = False
                st.stop()

            if vendor_to_run == "All":
                results = negotiate_all_vendors()
                saved = sum(r.get("savings", 0) for r in results if r.get("status") != "no_invoice")
                st.success(f"Run complete. Total saved: {fmt_usd(saved)}")
                # Show the last result as the "latest" for the logs panel
                if results:
                    last = results[-1]
                    st.markdown("---")
                    st.markdown(f"**Last vendor processed:** {last.get('vendor', '—')}")
                    st.markdown(f"**Tactic:** {last.get('tactic_used', '—')}")
                    st.markdown(f"**Result:** {fmt_usd(last.get('original_amount', 0))} → {fmt_usd(last.get('final_amount', 0))}")
                    st.markdown(f"**Status:** {'SAVED' if last.get('accepted') else 'NO SAVE'}")
            else:
                result = negotiate_bill(vendor_to_run)
                st.success(f"Negotiation complete for {vendor_to_run}.")
                st.markdown("---")
                st.markdown(f"**Tactic used:** {result.get('tactic_used', '—')}")
                st.markdown(f"**Amount:** {fmt_usd(result.get('original_amount', 0))} → {fmt_usd(result.get('final_amount', 0))}")
                st.markdown(f"**Status:** {'SAVED' if result.get('accepted') else 'NO SAVE'}")
                st.markdown(f"**Payment mode:** {result.get('payment_mode', '—')}")
                st.markdown(f"**TX hash:** {result.get('tx_hash', '—')}")

            # Refresh dashboard caches so the panels show fresh data
            st.session_state.brain_cached = None
            st.session_state.action_cached = None
            st.session_state.chain_cached = None

        except Exception as e:
            st.error(f"Agent run failed: {e}")
    st.session_state.trigger_running = False


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Proof of Autonomy Dashboard · HaggleMind · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    "Reads from local SQLite: sibyl_memory.db (Sibyl Memory) + hagglemind.db (agent_logs, transactions)."
)
