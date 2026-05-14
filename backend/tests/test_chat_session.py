"""SessionStore — in-memory chat history with TTL + max-size trim."""

from __future__ import annotations

import time

import pytest

from backend.chat.session import MAX_MESSAGES, SESSION_TTL, SessionStore


def test_get_unknown_session_returns_empty():
    s = SessionStore()
    assert s.get("nope") == []


def test_append_and_get_round_trip():
    s = SessionStore()
    msg = {"role": "user", "content": "hello"}
    s.append("sid-1", msg)
    assert s.get("sid-1") == [msg]


def test_get_returns_a_copy_not_internal_list():
    """Mutating the returned list must not affect the stored history."""
    s = SessionStore()
    s.append("sid", {"role": "user", "content": "hi"})
    out = s.get("sid")
    out.append({"role": "user", "content": "tampered"})
    assert len(s.get("sid")) == 1


def test_clear_drops_session():
    s = SessionStore()
    s.append("sid", {"role": "user", "content": "x"})
    s.clear("sid")
    assert s.get("sid") == []


def test_clear_unknown_session_is_idempotent():
    s = SessionStore()
    s.clear("never-existed")  # must not raise


def test_messages_trimmed_at_max_messages():
    s = SessionStore()
    for i in range(MAX_MESSAGES + 5):
        s.append("sid", {"role": "user", "content": f"msg-{i}"})
    history = s.get("sid")
    assert len(history) == MAX_MESSAGES
    # Head is dropped; tail is preserved.
    assert history[-1]["content"] == f"msg-{MAX_MESSAGES + 4}"


def test_expired_session_pruned(monkeypatch):
    s = SessionStore()
    s.append("sid", {"role": "user", "content": "hi"})

    # Simulate the session being touched long ago.
    s._sessions["sid"]["touched_at"] = time.time() - SESSION_TTL - 10
    assert s.get("sid") == []
    assert "sid" not in s._sessions


def test_get_refreshes_touched_at():
    s = SessionStore()
    s.append("sid", {"role": "user", "content": "hi"})
    s._sessions["sid"]["touched_at"] = time.time() - (SESSION_TTL - 60)
    s.get("sid")
    assert time.time() - s._sessions["sid"]["touched_at"] < 1


@pytest.mark.parametrize("count", [1, 5, MAX_MESSAGES])
def test_under_limit_keeps_all_messages(count):
    s = SessionStore()
    for i in range(count):
        s.append("sid", {"role": "user", "content": str(i)})
    assert len(s.get("sid")) == count
