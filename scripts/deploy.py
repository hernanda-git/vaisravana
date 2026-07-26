"""Project Vaiśravaṇa — versioned Fly deploy.

Usage:
    python scripts/deploy.py ["changelog text here"]

What it does (in order):
  1. bump VERSION patch digit (0.0.xxx); major.minor are intentionally frozen.
  2. prepend a `## vX.Y.Z` entry to CHANGELOG.md (with the message you pass).
  3. git tag vX.Y.Z, commit VERSION + CHANGELOG, push (tags + branch).
  4. flyctl deploy --app vaisravana.
The deployed bot reads VERSION on startup and announces vX.Y.Z + changelog to Telegram.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
APP = "vaisravana"


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=False,
                          text=True)


def main() -> None:
    note = " ".join(sys.argv[1:]).strip() or "Versioned deploy (no notes)."

    # 1. bump patch
    sys.path.insert(0, str(ROOT / "scripts"))
    import version as vmod
    new_ver = vmod.bump_patch()
    vmod.write_version(new_ver)
    print(f"VERSION -> {new_ver}")

    # 2. prepend changelog entry
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_entry = f"## v{new_ver} ({today})\n- {note}\n\n"
    existing = CHANGELOG_FILE.read_text(encoding="utf-8") if CHANGELOG_FILE.exists() else ""
    # keep the top title line if present
    lines = existing.splitlines(keepends=True)
    if lines and lines[0].startswith("# "):
        head = lines[0]
        rest = "".join(lines[1:])
        CHANGELOG_FILE.write_text(head + "\n" + new_entry + rest, encoding="utf-8")
    else:
        CHANGELOG_FILE.write_text("# Changelog — Project Vaiśravaṇa\n\n" + new_entry + existing,
                                  encoding="utf-8")

    # 3. git tag + commit + push
    _run(["git", "add", "VERSION", "CHANGELOG.md", "."])
    _run(["git", "commit", "-q", "-m", f"v{new_ver}: {note}"])
    _run(["git", "tag", f"v{new_ver}"])
    _run(["git", "push", "-q"])
    _run(["git", "push", "-q", "--tags"])

    # 4. deploy
    _run(["flyctl", "deploy", "--app", APP])


if __name__ == "__main__":
    main()
