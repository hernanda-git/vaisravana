"""Tests for Phase 10 Fly deploy: Telegram notifier + restart-safe open reload."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from telegram_bot import TelegramNotifier, html_escape  # noqa: E402
from db import init_db  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402


class _FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Records sendMessage calls; lets us assert escape + fallback behaviour."""
    def __init__(self):
        self.calls = []
        self._mode = "markdown"  # what sendMessage('MarkdownV2') returns

    def post(self, url, json=None):
        mode = json.get("parse_mode", "plain")
        self.calls.append(json)
        if mode == "HTML" and self._mode == "markdown_broken":
            return _FakeResp(400, "Bad Request: can't parse entities")
        return _FakeResp(200)


class StubNotifier(TelegramNotifier):
    def __init__(self, *a, **k):
        super().__init__("TESTTOKEN", "123")
        self._client = _FakeClient()

    def _get_client(self):
        return self._client


def test_mdv2_escape_escapes_special_chars():
    # HTML mode: only & < > are escaped; version/classical chars are safe
    assert html_escape("a<b>&c") == "a&lt;b&gt;&amp;c"
    assert html_escape("") == ""


def test_notify_decision_markdown_and_escapes_reason():
    n = StubNotifier()
    n.notify_decision("BTCUSDT", "5m", "ENTRY", 0.93, "BUY", "bos *hl* >50ema")
    body = n._client.calls[0]["text"]
    assert "ENTRY" in body and "BTCUSDT" in body and "<code>BUY</code>" in body
    assert "&gt;" in body  # reason escaped for HTML


def test_notify_fill_and_close_shape():
    n = StubNotifier()
    n.notify_fill("ETHUSDT", "15m", "BUY", 3000.0, 2980.0, 3040.0, 2.0)
    n.notify_close("ETHUSDT", "15m", "BUY", 3040.0, "TP", 2.0, True)
    assert len(n._client.calls) == 2
    assert "PAPER FILL" in n._client.calls[0]["text"]
    assert "✅" in n._client.calls[1]["text"]


def test_plain_text_fallback_on_parse_entities():
    n = StubNotifier()
    n._client._mode = "markdown_broken"
    ok = n.notify_status("X", "weird * text _ here")
    assert ok is True
    # first call failed markdown, second plain-text succeeded
    assert n._client.calls[0].get("parse_mode") == "HTML"
    assert "parse_mode" not in n._client.calls[1]


def test_startup_card_renders_version_cleanly():
    n = StubNotifier()
    n.notify_startup("0.0.7", ["BTCUSDT", "ETHUSDT"], "1m", ["5m"], 60, "off", 0)
    body = n._client.calls[0]["text"]
    # version must NOT be backslash-escaped (the old v0\\.0\\.4 bug)
    assert "v0.0.7" in body
    assert r"v0\.0\.7" not in body
    # no em-dash artifacts
    assert "—" not in body


def test_no_token_silent_false(tmp_path):
    n = TelegramNotifier("", "123")
    assert n.send_message("hi") is False


def test_get_open_positions_restart_safe():
    import tempfile
    from pathlib import Path
    conn = init_db(Path(tempfile.mkdtemp()) / "x.db")
    lc = TradeLifecycle(conn)
    t = lc.open("c1", "BTCUSDT", "5m", "BUY", 100.0, 1.0, 2.0, 99.0, 101.0)
    opened = lc.get_open_positions()
    assert (("BTCUSDT", "5m", "BUY")) in opened
    assert opened[("BTCUSDT", "5m", "BUY")].entry_price == 100.0
    # after close, reload is empty
    lc.close(t, 101.0, "TP")
    assert lc.get_open_positions() == {}


def test_health_check_sent_on_deploy():
    n = StubNotifier()
    ok = n.notify_health_check("0.0.7", "sin", 0, feed_ok=True)
    assert ok is True
    body = n._client.calls[0]["text"]
    assert "Health Check" in body and "v0.0.7" in body and "sin" in body
