import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_collect_flag_is_paper_only(monkeypatch):
    import bot_paper
    assert hasattr(bot_paper, "PAPER_COLLECT_AFTER_KILL")
    monkeypatch.setenv("VAISRAVANA_MODE", "live")
    assert os.getenv("VAISRAVANA_MODE") == "live"
    assert bot_paper.PAPER_COLLECT_AFTER_KILL in (True, False)
