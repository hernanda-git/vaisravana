"""Phase 13 — version module (offline, no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import version as vmod


def test_parse_roundtrip():
    assert vmod.parse("0.0.1") == (0, 0, 1)
    assert vmod.parse("2.13.457") == (2, 13, 457)


def test_bump_patch_only():
    # only the last digit moves; major.minor frozen
    assert vmod.bump_patch("0.0.1") == "0.0.2"
    assert vmod.bump_patch("0.0.999") == "0.0.1000"
    assert vmod.bump_patch("1.4.7") == "1.4.8"


def test_bad_version_raises():
    try:
        vmod.parse("v0.0.1")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for 'v0.0.1'")


def test_latest_changelog_picks_top_entry():
    # uses the real repo CHANGELOG.md top entry
    body = vmod.latest_changelog()
    assert "Versioning system introduced" in body
    assert "Phase 12" in body
