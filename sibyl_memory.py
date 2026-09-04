"""
Sibyl Memory integration for HaggleMind.

Routes ALL store/recall/update operations through the official sibyl-memory-client SDK.
This is the real Sibyl Memory layer — SQLite-backed, five-tier schema, FTS5 search.
No more direct JSON file manipulation.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

# Add the project dir so we can import from sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sibyl_memory_client import MemoryClient, Storage, SearchResults


# ---------------------------------------------------------------------------
# Constants — maps our HaggleMind concepts onto Sibyl's five-tier schema
# ---------------------------------------------------------------------------
# Sibyl tiers: HOT (state/), WARM (entities/), COLD (journal/), REFERENCE, ARCHIVE
# We use:
#   WARM entities  → per-vendor tactic confidence (the load-bearing memory)
#   COLD journal   → negotiation event log (audit trail)

ENTITY_CATEGORY = "vendor"
JOURNAL_PREFIX = "negotiation"

# Module-level flag: when True, the agent is running and events are live-streamed
_RUNNING = False


def set_running(running: bool) -> None:
    """Signal whether a negotiation run is in progress (for the live indicator)."""
    global _RUNNING
    _RUNNING = running


def is_running() -> bool:
    return _RUNNING


def _log_event(event_type: str, vendor: str, tactic: str,
               confidence: Optional[float] = None, reason: Optional[str] = None) -> None:
    """Best-effort memory event logger for the dashboard live feed.

    Writes a row to the `memory_events` table so the frontend can show the
    read/write happening in real time. Silent on any failure so the SDK
    never breaks because the dashboard DB is absent.
    """
    try:
        from persistence import log_memory_event
        from datetime import datetime, timezone
        log_memory_event({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "vendor": vendor,
            "tactic": tactic,
            "confidence": confidence,
            "reason": reason,
        })
    except Exception:
        pass  # best-effort; never break the memory layer


# ---------------------------------------------------------------------------
# SibylMemoryStore — wraps the SDK so the rest of HaggleMind never touches
# the JSON file directly. Every read and write goes through Sibyl.
# ---------------------------------------------------------------------------

class SibylMemoryStore:
    """Load-bearing memory store backed by the real Sibyl Memory SDK.

    Usage:
        mem = SibylMemoryStore()
        mem.set_vendor("Comcast", "competitor_promo", confidence=0.90, successes=3, failures=0)
        tactics = mem.get_vendor_tactics("Comcast")
        mem.update_after_negotiation("Comcast", "competitor_promo", success=True)
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the Sibyl Memory client.

        Args:
            db_path: Path to the SQLite memory DB. Defaults to a project-local
                     file so HaggleMind's memory is self-contained in the repo.
        """
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "sibyl_memory.db"
            )
        self.db_path = db_path
        self.storage = Storage(db_path)
        self.client = MemoryClient(
            self.storage,
            tenant_id="hagglemind-agent",
            tier="free",
        )

    # ------------------------------------------------------------------
    # Vendor tactic CRUD (WARM tier — entities)
    # ------------------------------------------------------------------

    def _entity_key(self, vendor: str, tactic: str) -> str:
        """Construct the entity name for a vendor+tactic pair."""
        return f"{vendor}::{tactic}"

    def get_vendor_tactics(self, vendor: str) -> dict[str, Any]:
        """Read ALL tactic confidence data for a vendor from Sibyl Memory.

        This is the LOAD-BEARING recall call. If memory was wiped, this
        returns an empty dict and the agent falls back to the default tactic.

        Returns:
            dict mapping tactic_name -> {confidence, successes, failures, last_used}
        """
        _log_event("READ", vendor, "", reason="agent loading vendor tactics")
        entities = self.client.list_entities(
            category=ENTITY_CATEGORY,
            status="active",
            limit=200,
        )
        result: dict[str, Any] = {}
        for ent in entities:
            name = ent.get("name", "")
            if "::" not in name:
                continue
            v, tactic = name.split("::", 1)
            if v == vendor:
                body = ent.get("body", {})
                result[tactic] = {
                    "confidence": body.get("confidence", 0.5),
                    "successes": body.get("successes", 0),
                    "failures": body.get("failures", 0),
                    "last_used": body.get("last_used", ""),
                }
        return result

    def get_tactic(self, vendor: str, tactic: str) -> Optional[dict[str, Any]]:
        """Read a single tactic's confidence data from Sibyl Memory."""
        _log_event("READ", vendor, tactic, reason="agent reading single tactic")
        entities = self.client.list_entities(
            category=ENTITY_CATEGORY,
            status="active",
            limit=200,
        )
        for ent in entities:
            name = ent.get("name", "")
            if name == self._entity_key(vendor, tactic):
                body = ent.get("body", {})
                return {
                    "confidence": body.get("confidence", 0.5),
                    "successes": body.get("successes", 0),
                    "failures": body.get("failures", 0),
                    "last_used": body.get("last_used", ""),
                }
        return None

    def set_vendor_tactic(
        self,
        vendor: str,
        tactic: str,
        confidence: float,
        successes: int,
        failures: int,
    ):
        """Write or update a vendor+tactic entity in Sibyl Memory (WARM tier)."""
        _log_event("WRITE", vendor, tactic, confidence=confidence,
                   reason=f"confidence -> {confidence:.2f} (s:{successes} f:{failures})")
        now = datetime.now(timezone.utc).isoformat()
        body = {
            "confidence": round(confidence, 2),
            "successes": successes,
            "failures": failures,
            "last_used": now,
            "vendor": vendor,
            "tactic": tactic,
        }
        self.client.set_entity(
            category=ENTITY_CATEGORY,
            name=self._entity_key(vendor, tactic),
            body=body,
            status="active",
        )

    def delete_vendor(self, vendor: str):
        """Delete ALL tactic entities for a vendor (used by wipe_memory)."""
        _log_event("WRITE", vendor, "", reason=f"wipe_memory: deleting vendor {vendor}")
        entities = self.client.list_entities(
            category=ENTITY_CATEGORY, status="active", limit=200
        )
        for ent in entities:
            name = ent.get("name", "")
            if "::" in name and name.split("::")[0] == vendor:
                self.client.delete_entity(ENTITY_CATEGORY, name)

    def wipe_all(self):
        """Wipe ALL vendor tactic memory (deletion test)."""
        _log_event("WRITE", "", "", reason="wipe_memory: clearing all vendors")
        entities = self.client.list_entities(
            category=ENTITY_CATEGORY, status="active", limit=200
        )
        for ent in entities:
            self.client.delete_entity(ENTITY_CATEGORY, ent["name"])

    # ------------------------------------------------------------------
    # Negotiation journal (COLD tier — append-only event log)
    # ------------------------------------------------------------------

    def log_negotiation(
        self,
        vendor: str,
        tactic: str,
        original_amount: float,
        final_amount: float,
        accepted: bool,
        confidence_before: float,
        confidence_after: float,
    ):
        """Append a negotiation event to the COLD journal tier."""
        reason = ("negotiation complete → journal write"
                   f" ({'accepted' if accepted else 'rejected'}, "
                   f"conf {confidence_before:.2f}→{confidence_after:.2f})")
        _log_event("WRITE", vendor, tactic, confidence=confidence_after, reason=reason)
        self.client.write_event(
            evaluated={
                "vendor": vendor,
                "tactic": tactic,
                "original_amount": original_amount,
                "final_amount": final_amount,
                "accepted": accepted,
                "confidence_before": confidence_before,
                "confidence_after": confidence_after,
            },
            acted={"payment_made": True},
            ts=datetime.now(timezone.utc).isoformat(),
        )

    def get_negotiation_history(self, vendor: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Read negotiation events from the COLD journal."""
        events = self.client.read_events(limit=limit)
        result = []
        for ev in events:
            eval_data = ev.get("evaluated", {})
            if vendor is None or eval_data.get("vendor") == vendor:
                result.append(ev)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def pick_tactic(self, vendor: str) -> str:
        """Pick the best tactic for a vendor from Sibyl Memory.

        Load-bearing: if memory is empty, returns DEFAULT_TACTIC.
        """
        from agent import DEFAULT_TACTIC, CONFIDENCE_DROP_THRESHOLD

        vendor_mem = self.get_vendor_tactics(vendor)
        if not vendor_mem:
            return DEFAULT_TACTIC

        best_tactic = None
        best_confidence = 0.0
        for tactic, data in vendor_mem.items():
            confidence = data.get("confidence", 0.0)
            if confidence < CONFIDENCE_DROP_THRESHOLD:
                continue
            if confidence > best_confidence:
                best_confidence = confidence
                best_tactic = tactic

        return best_tactic if best_tactic else DEFAULT_TACTIC

    def update_after_negotiation(self, vendor: str, tactic: str, success: bool):
        """Read current confidence, adjust it, write back — all via Sibyl."""
        from agent import (
            CONFIDENCE_SUCCESS_BOOST,
            CONFIDENCE_FAILURE_PENALTY,
            CONFIDENCE_MAX,
            CONFIDENCE_MIN,
        )

        current = self.get_tactic(vendor, tactic)
        if current is None:
            # First time seeing this tactic — seed it
            confidence = 0.50
            successes = 1 if success else 0
            failures = 0 if success else 1
        else:
            confidence = current["confidence"]
            successes = current["successes"]
            failures = current["failures"]
            if success:
                confidence = min(confidence + CONFIDENCE_SUCCESS_BOOST, CONFIDENCE_MAX)
                successes += 1
            else:
                confidence = max(confidence - CONFIDENCE_FAILURE_PENALTY, CONFIDENCE_MIN)
                failures += 1

        self.set_vendor_tactic(vendor, tactic, confidence, successes, failures)
        return confidence

    def status(self):
        """Print memory status (for CLI status command)."""
        entities = self.client.list_entities(
            category=ENTITY_CATEGORY, status="active", limit=200
        )
        vendors: dict[str, dict[str, Any]] = {}
        for ent in entities:
            name = ent.get("name", "")
            if "::" not in name:
                continue
            v, tactic = name.split("::", 1)
            body = ent.get("body", {})
            if v not in vendors:
                vendors[v] = {}
            vendors[v][tactic] = {
                "confidence": body.get("confidence", 0),
                "successes": body.get("successes", 0),
                "failures": body.get("failures", 0),
            }

        print("  --- Sibyl Memory (SDK-backed) ---")
        if not vendors:
            print("    (empty — no entities in Sibyl Memory)")
        else:
            for vendor in sorted(vendors):
                print(f"    {vendor}:")
                for tactic in sorted(vendors[vendor], key=lambda t: -vendors[vendor][t]["confidence"]):
                    d = vendors[vendor][tactic]
                    print(f"      {tactic:25s} conf={d['confidence']:.2f}  s:{d['successes']} f:{d['failures']}")

        # Journal size
        events = self.client.read_events(limit=1)
        print(f"    Negotiation events logged: {len(self.client.read_events(limit=200))}")


# ---------------------------------------------------------------------------
# Module-level singleton — one DB per project, shared across calls
# ---------------------------------------------------------------------------

_default_store: Optional[SibylMemoryStore] = None


def get_store() -> SibylMemoryStore:
    """Get or create the module-level SibylMemoryStore singleton."""
    global _default_store
    if _default_store is None:
        _default_store = SibylMemoryStore()
    return _default_store


def reset_store():
    """Reset the singleton (used by tests/reset)."""
    global _default_store
    if _default_store is not None:
        _default_store.storage.close()
    _default_store = SibylMemoryStore()
    _log_event("WRITE", "", "", reason="store reset")
