"""SSE event broadcaster for real-time log streaming."""
import asyncio
import json
import queue
import threading

_event_listeners = []
_event_lock = threading.Lock()


def broadcast(event_data: dict) -> None:
    """Send an event to all connected SSE clients."""
    data = json.dumps(event_data)
    with _event_lock:
        dead = []
        for q in _event_listeners:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            if q in _event_listeners:
                _event_listeners.remove(q)


def get_queue() -> queue.Queue:
    """Create and register a new SSE client queue."""
    q: queue.Queue = queue.Queue()
    with _event_lock:
        _event_listeners.append(q)
    return q


def remove_queue(q: queue.Queue) -> None:
    """Unregister an SSE client queue."""
    with _event_lock:
        if q in _event_listeners:
            _event_listeners.remove(q)
