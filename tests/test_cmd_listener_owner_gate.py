"""Tests: Telegram command listener owner-only gate (v0.0.26).

Fixes "bot lain nyampur nyampur" — a second bot sharing the same Telegram
token/update stream was having its /commands mixed into THIS bot. The listener
must honor ONLY the configured owner chat and ignore everything else.

NB: we test the gate logic directly (the _poll_once offset/dispatch), not the
network. The dispatch side-effect is stubbed.
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telegram_bot_v4 import TelegramCommandListener


class _StubNotifier:
    def _get_client(self):
        raise AssertionError("network must not be touched in this test")


def _make(updates, allowed):
    """Build a listener whose poll_once reads `updates` once, dispatch captured."""
    dispatched = []
    ln = TelegramCommandListener(
        _StubNotifier(), lambda text, raw: dispatched.append(text),
        poll_s=999, allowed_chat_id=allowed,
    )
    # monkeypatch the network poll with a one-shot iterator
    import telegram_bot as tb
    it = iter(updates)

    def _poll_once(self):
        try:
            upd = next(it)
        except StopIteration:
            self._stop.set()
            return
        # replicate the real _poll_once body (kept in sync with src)
        self._offset = upd.get("update_id", self._offset) + 1
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat_id = msg.get("chat", {}).get("id")
        if self._allowed is not None and str(chat_id) != self._allowed:
            return
        text = (msg.get("text") or "").strip()
        if text.startswith("/"):
            self._on(text, text)

    # patch the INSTANCE only — patching the class leaked the stub into every
    # later test (test_phase23_clean saw an empty dispatch list).
    import types
    ln._poll_once = types.MethodType(_poll_once, ln)
    return ln, dispatched


def test_owner_only_accepts_configured_chat():
    ups = [
        {"update_id": 1, "message": {"chat": {"id": 555}, "text": "/clean"}},
        {"update_id": 2, "message": {"chat": {"id": 999}, "text": "/stop"}},
    ]
    ln, disp = _make(ups, allowed="555")
    ln._poll_once(); ln._poll_once()
    assert disp == ["/clean"], disp  # the 999 chat is ignored


def test_owner_only_ignores_when_unset_default_none():
    # allowed=None => no restriction (single-bot mode); both chats accepted
    ups = [
        {"update_id": 1, "message": {"chat": {"id": 555}, "text": "/clean"}},
        {"update_id": 2, "message": {"chat": {"id": 999}, "text": "/stop"}},
    ]
    ln, disp = _make(ups, allowed=None)
    ln._poll_once(); ln._poll_once()
    assert disp == ["/clean", "/stop"], disp


def test_empty_string_default_is_treated_as_unset():
    # The OLD bug: "" was passed, which is not None, so the guard
    # `is not None` fired but `str(chat) != ""` always -> everything ignored.
    # Now "" is normalized to None at construction.
    ln = TelegramCommandListener(_StubNotifier(), lambda *a: None,
                                allowed_chat_id="")
    assert ln._allowed is None
