"""The version an automatic release takes: the next patch of pyproject.toml's version once that one is tagged.

    uv run python tools/next_version.py

The weekly refresh runs it before it releases. When v<version> (the version in pyproject.toml) is already a tag, the
release takes the next patch number (0.3.0 -> 0.3.1); when it is not, a person has set that version by hand and not
released it yet, and the release takes it as it is. The version is printed, and `version=<v>` goes to $GITHUB_OUTPUT
when that is set. Nothing is written: the refresh sets the version with `uv version`.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

import stats
import ygjson

VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def next_version(current: str, tagged: bool) -> str:
    """`current` when it is not tagged yet, else its next patch. Refuses anything but three numbers."""
    m = VERSION.fullmatch(current)
    if not m:
        raise ValueError(f"version {current!r} is not MAJOR.MINOR.PATCH")
    if not tagged:
        return current
    major, minor, patch = (int(n) for n in m.groups())
    return f"{major}.{minor}.{patch + 1}"


def is_tagged(version: str, root: Path = ygjson.ROOT) -> bool:
    """Whether the tag v<version> exists in the repository at `root`."""
    found = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/v{version}"], cwd=root,
                           capture_output=True)
    return found.returncode == 0


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    current = stats._version()
    version = next_version(current, is_tagged(current))
    print(version)
    if (output := os.environ.get("GITHUB_OUTPUT")):
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")


if __name__ == "__main__":
    main()
