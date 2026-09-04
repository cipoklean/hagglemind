"""
HaggleMind Proof-of-Autonomy Verification Dashboard
====================================================

Split-screen layout:
  LEFT  = agent action log (chat-style negotiation steps)
  RIGHT = Brain table (with last-read badge) + LIVE MEMORY EVENT FEED

Features:
  - LIVE MEMORY EVENT FEED (newest-first, READ/WRITE events from sibyl_memory.db)
  - Blinking "● READING LIVE" indicator while a run is in progress
  - LAST-READ HIGHLIGHT badge on the Brain table tactic row
  - Memory Value headline metric ($ saved vs no-memory baseline)
  - Footer caption: "the tactic on screen was read live from sibyl_memory.db"
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

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
    from persistence import (
        get_agent_logs,
        get_latest_agent_log,
        get_transactions,
        get_latest_transaction,
        get_memory_events,
        get_latest_memory_event,
        get_action_steps,
        clear_action_steps,
        wipe_dashboard_tables,
    )
except Exception as e:
    get_agent_logs = get_latest_agent_log = get_transactions = get_latest_transaction = None
    get_memory_events = get_latest_memory_event = None
    get_action_steps = clear_action_steps = wipe_dashboard_tables = None
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
    /* blink animation for the live indicator */
    @keyframes blink { 50% { opacity: 0.2; } }
    .live-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--green);
        animation: blink 1s step-end infinite;
    }
    .chat-bubble {
        background: var(--surface);
        border-left: 3px solid var(--accent);
        padding: 6px 10px;
        margin: 3px 0;
        border-radius: 4px;
        font-size: 0.9rem;
    }
    .chat-bubble.step-run { border-left-color: var(--green); }
    .chat-bubble.step-memory { border-left-color: var(--accent); }
    .chat-bubble.step-vendor { border-left-color: var(--orange); }
    .chat-bubble.step-payment { border-left-color: var(--green); }
    .chat-bubble.step-result { border-left-color: var(--green); }
    .chat-bubble.step-error { border-left-color: var(--red); }
    .chat-bubble.step-warning { border-left-color: var(--orange); }
    .chat-bubble.step-decision { border-left-color: var(--accent); }
    .badge-last-read {
        display: inline-block;
        background: var(--accent);
        color: #0e1117;
        font-size: 0.65rem;
        font-weight: 700;
        padding: 1px 5px;
        border-radius: 3px;
        margin-left: 6px;
        vertical-align: middle;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_usd(v):
    try:
        return f"${float(v):,.2f}"
    except (ValueError, TypeError):
        return "\u2014"


def fmt_ts(ts: str) -> str:
    """Short human-readable timestamp."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts[:19] if ts else ""


# ---------------------------------------------------------------------------
# Memory Value metric — savings vs no-memory baseline
# ---------------------------------------------------------------------------

def _memory_value_saved() -> Optional[float]:
    """Compute 'Memory Value' = average savings on runs WITH memory.

    Baseline heuristic:
      A no-memory run pays the full invoice (no discount) because the agent
      falls back to the weak default tactic (loyalty_discount). We count runs
      where savings > 0 as 'with memory' and report their average savings.
      When the store is wiped, future runs produce savings == 0, which drops
      the metric — visually proving memory is load-bearing.
    """
    if get_agent_logs is None:
        return None
    try:
        logs = get_agent_logs(limit=200) or []
        if not logs:
            return None
        discounted = [r for r in logs if float(r.get("savings", 0)) > 0]
        if not discounted:
            return 0.0
        avg_saved = sum(float(r["savings"]) for r in discounted) / len(discounted)
        return round(avg_saved, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Brain data — with last-read badge
# ---------------------------------------------------------------------------

def _read_brain(vendor_filter: Optional[str] = None) -> tuple[list[dict], Optional[str]]:
    """Read Sibyl Memory entities. Returns (rows, last_read_tactic_key) where
    last_read_tactic_key is 'Vendor::Tactic' of the most recent READ event."""
    rows = []
    last_read_key: Optional[str] = None
    if sibyl_memory is None:
        return rows, last_read_key
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
            for tactic in sorted(vendors[vendor],
                                 key=lambda t: -vendors[vendor][t]["confidence"]):
                d = vendors[vendor][tactic]
                rows.append({
                    "Vendor": vendor,
                    "Tactic": tactic,
                    "Successes": d["successes"],
                    "Failures": d["failures"],
                    "Confidence": round(d["confidence"], 2),
                    "_key": f"{vendor}::{tactic}",
                })

        # Determine the most recently READ tactic from the memory_events table
        if get_latest_memory_event is not None:
            try:
                latest_read = get_latest_memory_event(event_type="READ")
                if latest_read and latest_read.get("vendor"):
                    last_read_key = f"{latest_read['vendor']}::{latest_read['tactic']}" \
                        if latest_read.get("tactic") \
                        else f"{latest_read['vendor']}::"
            except Exception:
                last_read_key = None
    except Exception as e:
        st.error(f"Failed to read Sibyl Memory: {e}")
    return rows, last_read_key


# ===========================================================================
# LAYOUT — two-column split screen
# ===========================================================================

st.title(":robot: HaggleMind · Proof of Autonomy")
st.markdown(
    "Verification dashboard for the autonomous bill-negotiating agent. "
    "All data is read from local SQLite stores — no API calls out."
)

# ---- LIVE indicator (blinks while a run is in progress) ----
_running = False
if sibyl_memory is not None:
    try:
        _running = sibyl_memory.is_running()
    except Exception:
        _running = False
if _running:
    st.markdown(
        '<span class="live-dot"></span> '
        '<span style="color:var(--green);font-weight:600;">● READING LIVE</span> '
        '<span style="color:var(--muted);">— agent is querying sibyl_memory.db right now</span>',
        unsafe_allow_html=True,
    )
else:
    st.caption("\u25CF Idle \u2014 no agent run in progress")

if not sibyl_memory or not persistence:
    st.error(
        "Missing backend dependencies. Make sure sibyl_memory.py and "
        "persistence.py are on the Python path and the required packages are installed."
    )

st.markdown("---")

# ---- Headline: Memory Value metric ----
mv1, mv2, mv3 = st.columns([1, 3, 1])
mv = _memory_value_saved()
if mv is not None:
    mv1.metric("Memory Value", f"${mv:,.2f}", delta="saved vs no-memory baseline")
    if mv > 0:
        mv2.markdown(
            f'<div style="color:var(--muted);font-size:0.85rem;">'
            f'Agent paid <b>${mv:,.2f} less</b> on average when Sibyl Memory was intact '
            f'than on no-memory runs. Delete the memory and the agent pays full price.'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        mv2.markdown(
            '<div style="color:var(--orange);font-size:0.85rem;">'
            'No discounted runs recorded yet. Run the agent with memory intact to see the value.'
            '</div>',
            unsafe_allow_html=True,
        )
    mv3.markdown("")

st.markdown("---")

# ===========================================================================
# TWO-COLUMN SPLIT: LEFT = action log | RIGHT = Brain + event feed
# ===========================================================================

left_col, right_col = st.columns([1, 2], gap="medium")

# -------------------- LEFT COLUMN: Agent action log --------------------
with left_col:
    st.header("📋 Agent Action Log")

    st.markdown(
        "Chat-style log of every negotiation step the agent takes. "
        "Refresh or re-run to see the latest."
    )

    action_vendor = st.text_input(
        "Filter by vendor (optional)",
        placeholder="e.g. Comcast",
        key="action_vendor_filter",
    ).strip() or None

    _, act_refresh_col, _ = st.columns([4, 1, 4])
    act_refresh = act_refresh_col.button("🔄 Refresh", type="primary")

    steps = []
    if act_refresh or "action_cached" not in st.session_state:
        st.session_state.action_cached = datetime.now(timezone.utc).isoformat()
        if get_action_steps is not None:
            try:
                steps = get_action_steps(limit=80, vendor=action_vendor)
                # Return newest-first for display, but we render oldest-first
                steps = list(reversed(steps))
            except Exception as e:
                st.error(f"Failed to load action steps: {e}")

    if steps:
        for s in steps:
            stype = s.get("step_type", "info")
            msg = s.get("message", "")
            ts = fmt_ts(s.get("timestamp", ""))
            css_cls = f"chat-bubble step-{stype}" if stype in (
                "run", "memory", "vendor", "payment", "result",
                "error", "warning", "decision", "info",
            ) else "chat-bubble"
            st.markdown(
                f'<div class="{css_cls}"><span style="color:var(--muted);font-size:0.7rem;">{ts}</span> '
                f'<span style="color:var(--text);font-weight:600;">[{stype.upper()}]</span> '
                f'<span style="color:var(--text);">{msg}</span></div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div style="color:var(--muted);font-size:0.75rem;margin-top:6px;">'
            f'{len(steps)} step(s) shown</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No action steps yet. Run the agent via the Trigger panel or CLI.")

    st.markdown("---")
    st.markdown(
        '<div style="color:var(--muted);font-size:0.75rem;">'
        'Each row is a timestamped step written by the agent to <b>hagglemind.db → action_steps</b> '
        'as it negotiates. The memory read happens in step [MEMORY].</div>',
        unsafe_allow_html=True,
    )

# -------------------- RIGHT COLUMN: Brain + LIVE MEMORY EVENT FEED --------------------
with right_col:
    # ---- BRAIN TABLE with last-read badge ----
    st.header("🧠 The Brain — Sibyl Memory")

    st.markdown(
        "Live per-vendor tactic confidence table from the real Sibyl Memory store "
        "(SQLite, via sibyl-memory-client SDK)."
    )

    brain_vendor = st.text_input(
        "Filter by vendor (optional)",
        placeholder="e.g. Comcast",
        key="brain_vendor_filter",
    ).strip() or None

    _, brain_refresh_col, _ = st.columns([4, 1, 4])
    brain_refresh = brain_refresh_col.button("🔄 Refresh Memory", type="primary")

    brain_rows, last_read_key = _read_brain(vendor_filter=brain_vendor)

    if brain_rows:
        # Mark the last-read row
        for row in brain_rows:
            row["_last_read"] = (row["_key"] == last_read_key)

        display_rows = []
        for r in brain_rows:
            tactic_display = r["Tactic"]
            if r["_last_read"]:
                tactic_display = f'{r["Tactic"]} <span class="badge-last-read">◉ LAST READ</span>'
            display_rows.append({
                "Vendor": r["Vendor"],
                "Tactic": tactic_display,
                "Successes": r["Successes"],
                "Failures": r["Failures"],
                "Confidence": r["Confidence"],
            })

        df_brain = pd.DataFrame(display_rows)

        st.dataframe(
            df_brain,
            column_config={
                "Tactic": st.column_config.TextColumn("Tactic", width="200px"),
                "Confidence": st.column_config.NumberColumn(
                    "Confidence", format=":.2f", width="100px"
                ),
                "Successes": st.column_config.NumberColumn("Successes", format="{:}"),
                "Failures": st.column_config.NumberColumn("Failures", format="{:}"),
            },
            hide_index=True,
            width="stretch",
            use_container_width=True,
        )

        n_vendors = len(set(r["Vendor"] for r in brain_rows))
        st.caption(
            f"{len(brain_rows)} tactic entries across {n_vendors} vendor(s). "
            f'<span style="color:var(--accent);">◉ LAST READ</span> = tactic most recently '
            f'loaded by the agent from sibyl_memory.db.',
            unsafe_allow_html=True,
        )

        # Footer caption under the Brain panel
        st.markdown(
            '<div style="color:var(--muted);font-size:0.75rem;margin-top:4px;">'
            '↳ the tactic on screen was read live from sibyl_memory.db — '
            'not from the prompt or chat history</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No vendor entities found in Sibyl Memory. Run the agent to populate it.")

    st.markdown("---")

    # ---- LIVE MEMORY EVENT FEED (newest-first) ----
    st.header("⚡ Live Memory Event Feed")

    st.markdown(
        "Every READ and WRITE to Sibyl Memory is logged here in real time. "
        "Watch the agent read a tactic, then write back a new confidence — "
        "the same moment it answers."
    )

    ev_vendor = st.text_input(
        "Filter by vendor (optional)",
        placeholder="e.g. Comcast",
        key="event_vendor_filter",
    ).strip() or None

    _, ev_refresh_col, _ = st.columns([4, 1, 4])
    ev_refresh = ev_refresh_col.button("🔄 Refresh Events", type="primary")

    events = []
    if ev_refresh or "events_cached" not in st.session_state:
        st.session_state.events_cached = datetime.now(timezone.utc).isoformat()
        if get_memory_events is not None:
            try:
                events = get_memory_events(limit=40, vendor=ev_vendor)
                # Already newest-first from the DB query
            except Exception as e:
                st.error(f"Failed to load memory events: {e}")

    if events:
        ev_df = pd.DataFrame(events)
        # Render as a styled table
        st.dataframe(
            ev_df[["timestamp", "event_type", "vendor", "tactic", "confidence", "reason"]],
            column_config={
                "timestamp": st.column_config.TextColumn("Time", width="90px"),
                "event_type": st.column_config.TextColumn("Type", width="70px"),
                "vendor": st.column_config.TextColumn("Vendor", width="100px"),
                "tactic": st.column_config.TextColumn("Tactic", width="130px"),
                "confidence": st.column_config.NumberColumn("Conf", format=":.2f", width="70px"),
                "reason": st.column_config.TextColumn("Reason", width="300px"),
            },
            hide_index=True,
            width="stretch",
            use_container_width=True,
        )

        n_read = sum(1 for e in events if e.get("event_type") == "READ")
        n_write = sum(1 for e in events if e.get("event_type") == "WRITE")
        st.caption(
            f"{len(events)} event(s) · {n_read} READ · {n_write} WRITE · "
            f'newest first. <span style="color:var(--muted);">'
            f'These are the actual SDK calls the agent made to sibyl_memory.db.</span>',
            unsafe_allow_html=True,
        )
    else:
        st.info(
            "No memory events yet. Run the agent — every tactic read and confidence "
            "write will appear here."
        )

# ===========================================================================
# FOOTER
# ===========================================================================
st.divider()
st.caption(
    f"HaggleMind · Proof of Autonomy Dashboard · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    "Reads from local SQLite: sibyl_memory.db (Sibyl Memory) + hagglemind.db (agent_logs, transactions, memory_events, action_steps)."
)
