"""In-memory chat session store with idle expiry.

Each session is keyed by a client-supplied UUID (stored in localStorage on
the frontend). Conversations live for SESSION_TTL of inactivity, then are
pruned. Phase 4 will move this to Postgres.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

SESSION_TTL = 60 * 60  # 1 hour idle
MAX_MESSAGES = 40  # cap per session to keep prompts cheap


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def get(self, sid: str) -> list[dict[str, Any]]:
        self._prune()
        with self._lock:
            sess = self._sessions.get(sid)
            if not sess:
                return []
            sess["touched_at"] = time.time()
            return list(sess["messages"])

    def append(self, sid: str, message: dict[str, Any]) -> None:
        with self._lock:
            sess = self._sessions.setdefault(sid, {"messages": [], "touched_at": time.time()})
            sess["messages"].append(message)
            # Trim head when oversize but keep at least one full user turn
            if len(sess["messages"]) > MAX_MESSAGES:
                sess["messages"] = sess["messages"][-MAX_MESSAGES:]
            sess["touched_at"] = time.time()

    def clear(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def _prune(self) -> None:
        now = time.time()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if now - s["touched_at"] > SESSION_TTL]
            for sid in stale:
                self._sessions.pop(sid, None)


# Module-level singleton
store = SessionStore()
