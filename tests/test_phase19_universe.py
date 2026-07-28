"""Phase 19 (v0.1.0) — extended monitoring universe + 1000x symbol resolution.

Verifies all 15 configured pairs (leaders + 12 requested alts) resolve to valid Binance
USDⓈ-M symbols, the 1000x meme perps map to their 1000-prefixed contract, and the bot's
default pair list covers everything the owner asked for.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from symbols import DEFAULT_UNIVERSE, resolve_symbol  # noqa: E402


def test_default_universe_has_the_15_requested():
    # 3 leaders + 12 requested alts
    assert "BTCUSDT" in DEFAULT_UNIVERSE
    assert "ETHUSDT" in DEFAULT_UNIVERSE
    assert "SOLUSDT" in DEFAULT_UNIVERSE
    for alt in ["1000PEPEUSDT", "1000BONKUSDT", "ENAUSDT", "WLDUSDT", "PENGUUSDT",
                "AAVEUSDT", "TAOUSDT", "INJUSDT", "APEUSDT", "PUMPUSDT", "WIFUSDT", "CRVUSDT"]:
        assert alt in DEFAULT_UNIVERSE, f"missing {alt}"
    assert len(DEFAULT_UNIVERSE) == 15


def test_1000x_resolution():
    assert resolve_symbol("PEPE") == "1000PEPEUSDT"
    assert resolve_symbol("pepeusdt") == "1000PEPEUSDT"
    assert resolve_symbol("BONK") == "1000BONKUSDT"
    assert resolve_symbol("1000BONKUSDT") == "1000BONKUSDT"  # already prefixed passes


def test_plain_perps_pass_through():
    assert resolve_symbol("ENA") == "ENAUSDT"
    assert resolve_symbol("WLDUSDT") == "WLDUSDT"
    assert resolve_symbol("PENGU") == "PENGUUSDT"


def test_resolved_default_universe_is_unique_and_resolvable():
    resolved = [resolve_symbol(p) for p in DEFAULT_UNIVERSE]
    assert len(set(resolved)) == len(resolved), "duplicated symbols after resolution"
    # every resolved symbol ends in USDT and is non-empty
    assert all(s.endswith("USDT") and s for s in resolved)
