"""Tests: Telegram command @username routing + /status rename (v0.0.28).

Ensures Vaisravana's listener honors ONLY commands addressed to its own
username (e.g. /status@vaisravana_bot) and ignores the other bot's commands
(e.g. /health@xvalarion_bot) that arrive in the same shared chat. Also checks
the /health -> /status dispatch rename.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.telegram_bot import TelegramCommandListener, TelegramNotifier


class _FakeNotifier:
    """Stand-in notifier: exposes _base + _get_client so the listener can poll."""
    def __init__(self):
        self._base = "https://api.telegram.org/botTEST"
        self.sent = []
    def _get_client(self):
        # real httpx client would hit the network; tests feed updates directly
        raise RuntimeError("network disabled in test")
    def send_message(self, text, *a, **k):
        self.sent.append(text)
        return True


def _make_listener(username=None, chat=None):
    n = _FakeNotifier()
    received = []
    def on_cmd(text, raw):
        received.append(text)
    l = TelegramCommandListener(n, on_cmd, poll_s=1, allowed_chat_id=chat,
                                bot_username=username)
    return l, received


def test_status_dispatch_routes_to_health_report():
    """_dispatch maps /status and /health to health_report() (rename landed)."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src = open(os.path.join(repo, "scripts", "bot_paper.py")).read()
    assert 'elif cmd == "/status":' in src
    assert 'elif cmd == "/health":' in src
    assert "health_report()" in src


def test_username_routing_ignores_other_bot():
    """/health@xvalarion_bot is ignored when listener is bound to vaisravana.
    We drive _poll_once via a monkeypatched getUpdates."""
    import urllib3
    l, received = _make_listener(username="vaisravana_bot", chat="5894116684")
    # patch _poll_once's network by feeding updates through a fake client
    class FakeResp:
        status_code = 200
        def json(self):
            return {"result": [
                {"update_id": 1, "message": {"chat": {"id": 5894116684},
                 "text": "/health@xvalarion_bot"}},
                {"update_id": 2, "message": {"chat": {"id": 5894116684},
                 "text": "/status@vaisravana_bot"}},
            ]}
    class FakeClient:
        def get(self, url, params=None):
            return FakeResp()
    l._n._get_client = lambda: FakeClient()
    l._poll_once()
    # only the @vaisravana_bot command should have been delivered
    assert received == ["/status@vaisravana_bot"], received


def test_plain_command_accepted_when_bound():
    l, received = _make_listener(username="vaisravana_bot", chat="5894116684")
    class FakeResp:
        status_code = 200
        def json(self):
            return {"result": [
                {"update_id": 3, "message": {"chat": {"id": 5894116684},
                 "text": "/status"}},
            ]}
    class FakeClient:
        def get(self, url, params=None):
            return FakeResp()
    l._n._get_client = lambda: FakeClient()
    l._poll_once()
    assert received == ["/status"], received


def test_unbound_listener_accepts_any_target():
    """Without a bot_username, all @-suffixed commands are honored."""
    l, received = _make_listener(username=None, chat="5894116684")
    class FakeResp:
        status_code = 200
        def json(self):
            return {"result": [
                {"update_id": 4, "message": {"chat": {"id": 5894116684},
                 "text": "/health@xvalarion_bot"}},
            ]}
    class FakeClient:
        def get(self, url, params=None):
            return FakeResp()
    l._n._get_client = lambda: FakeClient()
    l._poll_once()
    assert received == ["/health@xvalarion_bot"], received
