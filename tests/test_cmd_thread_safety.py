"""Tests: v0.0.33 command-thread fixes.

1. db.get_connection must open sqlite with check_same_thread=False so the
   Telegram command listener (daemon thread) can run /status queries on the
   main-thread connection. Regression: every /status card died with
   "SQLite objects created in a thread can only be used in that same thread".
2. /config must reference a REAL ParameterSurface field
   (global_max_live_pairs) — max_concurrent_trades never existed and raised
   AttributeError from pydantic.
3. /reload must not import the non-existent `surface` module.
"""
from __future__ import annotations

import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import db  # noqa: E402
import config as cfg  # noqa: E402

BOT_SRC = (ROOT / "scripts" / "bot_paper.py").read_text(encoding="utf-8")


def test_connection_usable_from_other_thread(tmp_path):
    """A connection created on the main thread must work from a worker thread."""
    conn = db.init_db(tmp_path / "t.db")
    errors: list[Exception] = []

    def worker():
        try:
            db.trade_summary(conn, recent_n=5)
            conn.execute("SELECT COUNT(*) FROM trade_logs").fetchone()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join(10)
    assert not errors, f"cross-thread use failed: {errors}"


def test_config_card_uses_real_surface_field():
    assert "max_concurrent_trades" not in BOT_SRC, \
        "/config references max_concurrent_trades which is not a ParameterSurface field"
    assert "global_max_live_pairs" in BOT_SRC
    # the field must actually exist on the model
    assert "global_max_live_pairs" in cfg.ParameterSurface.model_fields


def test_reload_does_not_import_ghost_surface_module():
    assert "from surface import SurfaceLoader" not in BOT_SRC, \
        "/reload imports the non-existent `surface` module"
