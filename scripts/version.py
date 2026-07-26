"""Version handling for Project Vaiśravaṇa.

Version scheme: vMAJOR.MINOR.PATCH  (e.g. 0.0.1).
  - MAJOR / MINOR are intentional / frozen unless a deliberate breaking change.
  - PATCH (0.0.xxx) is bumped on every Fly deployment.

Functions here read/write the repo-root VERSION file and a CHANGELOG.md so the
deployed bot can announce what version is live and what changed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> str:
    """Return the current version string (e.g. '0.0.1'). Falls back to '0.0.0'."""
    try:
        txt = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"
    if not _VERSION_RE.match(txt):
        return "0.0.0"
    return txt


def parse(version: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(version)
    if not m:
        raise ValueError(f"bad version: {version!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump_patch(version: str = "") -> str:
    """Bump only the PATCH digit (0.0.xxx). Major/minor preserved."""
    v = version or read_version()
    major, minor, patch = parse(v)
    return f"{major}.{minor}.{patch + 1}"


def write_version(version: str) -> None:
    if not _VERSION_RE.match(version):
        raise ValueError(f"bad version: {version!r}")
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")


def latest_changelog() -> str:
    """Return the most recent changelog entry (under the top '## vX.Y.Z' heading)."""
    try:
        text = CHANGELOG_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    lines = text.splitlines()
    out: list[str] = []
    started = False
    for ln in lines:
        if ln.startswith("## "):
            if started:
                break
            started = True
            continue
        if started:
            out.append(ln)
    body = "\n".join(l for l in out if l.strip()).strip()
    return body


def deploy_info() -> str:
    """Human-readable one-line deploy summary for Telegram."""
    v = read_version()
    note = latest_changelog().replace("\n", " · ")
    if len(note) > 240:
        note = note[:240] + "…"
    return f"v{v}" + (f" — {note}" if note else "")
