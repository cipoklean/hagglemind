"""
HaggleMind persistence layer for the Streamlit verification dashboard.

Provides two additional SQLite tables, stored in the same DB file as
sibyl_memory.db so the frontend has a single local data source:

    agent_logs     — one row per negotiation the agent runs
    transactions   — one row per on-chain (or simulated) payment

The existing CLI (haggle_cli.py / agent.py / x402_payment.py) imports
these helpers optionally so nothing breaks when the dashboard is absent.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

# One DB file per project — sibling to sibyl_memory.db
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hagglemind.db")

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS agent_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    vendor        TEXT    NOT NULL,
    tactic        TEXT    NOT NULL,
    original_amt  REAL    NOT NULL,
    final_amt     REAL    NOT NULL,
    savings       REAL    NOT NULL,
    confidence_before REAL,
    confidence_after  REAL,
    accepted      INTEGER NOT NULL,
    payment_mode  TEXT    NOT NULL DEFAULT 'unknown',
    tx_hash       TEXT,
    explorer_url  TEXT,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    vendor        TEXT    NOT NULL,
    amount_usd    REAL    NOT NULL,
    tx_hash       TEXT    NOT NULL,
    block_number  INTEGER,
    network       TEXT    NOT NULL DEFAULT 'Base Sepolia',
    explorer_url  TEXT,
    payment_mode  TEXT    NOT NULL DEFAULT 'unknown',
    status        TEXT    NOT NULL DEFAULT 'confirmed'
);

CREATE TABLE IF NOT EXISTS memory_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    event_type    TEXT    NOT NULL DEFAULT 'INFO',
    vendor        TEXT    NOT NULL DEFAULT '',
    tactic        TEXT    NOT NULL DEFAULT '',
    confidence    REAL,
    reason        TEXT
);

CREATE TABLE IF NOT EXISTS action_steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    vendor        TEXT    NOT NULL DEFAULT '',
    step_num      INTEGER NOT NULL DEFAULT 0,
    step_type     TEXT    NOT NULL DEFAULT 'info',
    message       TEXT    NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Agent logs
# ---------------------------------------------------------------------------

def log_agent_run(entry: dict[str, Any]) -> int:
    """Append a negotiation log row. Returns the new row id."""
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO agent_logs
               (timestamp, vendor, tactic, original_amt, final_amt, savings,
                confidence_before, confidence_after, accepted, payment_mode,
                tx_hash, explorer_url, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                entry.get("vendor", ""),
                entry.get("tactic", ""),
                float(entry.get("original_amount", 0)),
                float(entry.get("final_amount", 0)),
                float(entry.get("savings", 0)),
                entry.get("confidence_before"),
                entry.get("confidence_after"),
                int(entry.get("accepted", False)),
                entry.get("payment_mode", "unknown"),
                entry.get("tx_hash") or "",
                entry.get("explorer_url") or "",
                entry.get("note", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_agent_logs(limit: int = 50, vendor: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the most recent agent log rows."""
    conn = _connect()
    try:
        if vendor:
            rows = conn.execute(
                "SELECT * FROM agent_logs WHERE vendor = ? ORDER BY id DESC LIMIT ?",
                (vendor, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_agent_log(vendor: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Return the single most recent agent log row (filtered by vendor if given)."""
    rows = get_agent_logs(limit=1, vendor=vendor)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def log_transaction(entry: dict[str, Any]) -> int:
    """Append a transaction row. Returns the new row id."""
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO transactions
               (timestamp, vendor, amount_usd, tx_hash, block_number,
                network, explorer_url, payment_mode, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                entry.get("vendor", ""),
                float(entry.get("amount_usd", entry.get("amount", 0))),
                entry.get("tx_hash", ""),
                entry.get("block_number"),
                entry.get("network", "Base Sepolia"),
                entry.get("explorer_url") or "",
                entry.get("payment_mode", "unknown"),
                entry.get("status", "confirmed"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_transactions(limit: int = 50, vendor: Optional[str] = None, offset: int = 0) -> list[dict[str, Any]]:
    """Return the most recent transaction rows with pagination."""
    conn = _connect()
    try:
        if vendor:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE vendor = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (vendor, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_transaction(vendor: Optional[str] = None) -> Optional[dict[str, Any]]:
    rows = get_transactions(limit=1, vendor=vendor)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Convenience: wipe dashboard tables (used by CLI reset)
# ---------------------------------------------------------------------------

def wipe_dashboard_tables() -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM agent_logs")
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM action_steps")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Memory events (READ/WRITE audit trail for the live event feed)
# ---------------------------------------------------------------------------

def log_memory_event(entry: dict[str, Any]) -> int:
    """Append a memory event row (READ/WRITE/DELETE). Returns the new row id.

    Best-effort: if the DB is absent the call is silently ignored so the
    agent CLI never breaks.
    """
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO memory_events
               (timestamp, event_type, vendor, tactic, confidence, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                entry.get("event_type", "INFO"),
                entry.get("vendor", ""),
                entry.get("tactic", ""),
                entry.get("confidence"),
                entry.get("reason"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_memory_events(limit: int = 50, vendor: Optional[str] = None,
                      event_type: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the most recent memory events, newest first."""
    conn = _connect()
    try:
        sql = "SELECT * FROM memory_events WHERE 1=1"
        params: list[Any] = []
        if vendor:
            sql += " AND vendor = ?"
            params.append(vendor)
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_memory_event(event_type: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Return the single most recent memory event (optionally filtered by type)."""
    rows = get_memory_events(limit=1, event_type=event_type)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Action steps (chat-style negotiation log for the LEFT panel)
# ---------------------------------------------------------------------------

def log_action_step(entry: dict[str, Any]) -> int:
    """Append a negotiation step row. Returns the new row id.

    Best-effort: if the DB is absent the call is silently ignored so the
    agent CLI never breaks.
    """
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO action_steps
               (timestamp, vendor, step_num, step_type, message)
               VALUES (?, ?, ?, ?, ?)""",
            (
                entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                entry.get("vendor", ""),
                int(entry.get("step_num", 0)),
                entry.get("step_type", "info"),
                entry.get("message", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_action_steps(limit: int = 100, vendor: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the most recent action steps, newest first."""
    conn = _connect()
    try:
        sql = "SELECT * FROM action_steps WHERE 1=1"
        params: list[Any] = []
        if vendor:
            sql += " AND vendor = ?"
            params.append(vendor)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_action_steps(limit: int = 100, vendor: Optional[str] = None) -> list[dict[str, Any]]:
    """Alias for get_action_steps — returns the most recent steps newest first."""
    return get_action_steps(limit=limit, vendor=vendor)


def clear_action_steps(vendor: Optional[str] = None) -> None:
    """Delete action steps (called at the start of a run to avoid stale clutter)."""
    conn = _connect()
    try:
        if vendor:
            conn.execute("DELETE FROM action_steps WHERE vendor = ?", (vendor,))
        else:
            conn.execute("DELETE FROM action_steps")
        conn.commit()
    finally:
        conn.close()
