"""YGOJSON's aggregate files (its `v1/aggregate` branch), downloaded pinned to one commit into .cache/ygojson.

`download(commit, cache)` reads the commit's tree from the GitHub API, then fetches each file at its top level from
raw.githubusercontent.com at that commit, and refuses a file whose git blob hash is not the one the tree names. The
files land in a new directory that replaces `cache` only once every file has come (fetch.cache_dir), with
`commit.json` ({"commit": sha}) beside them, so `cached_commit(cache)` says which commit the cache holds. `head()` is
the commit the branch points at today. The branch is rewritten on every YGOJSON update, so an old commit can stop being
downloadable once GitHub drops it; take the branch's current one then (import_ygojson.py --update).
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Mapping
from pathlib import Path

import fetch

REPO = "iconmaster5326/YGOJSON"
BRANCH = "v1/aggregate"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
COMMIT_FILE = "commit.json"
SHA = re.compile(r"^[0-9a-f]{40}$")


def blob_sha(body: bytes) -> str:
    """The git blob hash of a file's bytes."""
    return hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()


def head() -> str:
    """The commit BRANCH points at today."""
    _, data = fetch.get_json(f"{API}/branches/{urllib.parse.quote(BRANCH, safe='')}")
    return data["commit"]["sha"]


def cached_commit(cache: Path) -> str | None:
    """The commit the cache was downloaded at, or None when it was not downloaded by `download`."""
    marker = fetch.read_json(cache / COMMIT_FILE)
    return marker.get("commit") if isinstance(marker, dict) else None


def download(commit: str, cache: Path) -> list[str]:
    """Download the top-level files of `commit` into `cache`, replacing what it held. The names of the files."""
    if not SHA.match(commit):
        raise ValueError(f"{commit!r} is not a full commit sha")
    _, tree = fetch.get_json(f"{API}/git/trees/{commit}")
    blobs = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"}
    with fetch.cache_dir(cache, refresh=True) as staging:
        for name, sha in sorted(blobs.items()):
            def same_blob(body: bytes, headers: Mapping[str, str], sha: str = sha) -> None:
                if blob_sha(body) != sha:
                    raise fetch.Retry(f"the file's blob hash is {blob_sha(body)}, the tree says {sha}")

            body = fetch.get_bytes(f"{RAW}/{commit}/{urllib.parse.quote(name)}", timeout=600, check=same_blob)
            fetch.write_atomic(staging / name, body)
        fetch.write_atomic(staging / COMMIT_FILE, json.dumps({"commit": commit}) + "\n")
    return sorted(blobs)
