"""Every download the tools make, and how the cache under .cache is written.

`get_json(url)` sends one GET with the project's User-Agent and a timeout, at least `delay` seconds after the previous
request to the same host. It retries, up to ATTEMPTS in all, on 408/425/429/5xx, on network errors and timeouts, and
on a body that is cut short or is not JSON, waiting BACKOFF_S, then twice that, and so on (never more than MAX_WAIT_S),
or what the reply's Retry-After asks. A `check` can read the parsed body and ask for a retry (MediaWiki's maxlag) or
refuse it. A download that still fails raises FetchError, naming the URL and the last reason.

`write_atomic` writes a cache file through a temporary file and os.replace, so an interrupted run never leaves a
truncated file behind; `read_json` treats a file that is not valid JSON as absent, so one left by an older run is
fetched again. `cache_dir(cache, refresh)` is the directory to fetch into: `cache` itself, or with refresh an empty
sibling that takes `cache`'s place only when the block ends without an error, so a refresh that fails halfway leaves
the old cache whole.
"""
from __future__ import annotations

import contextlib
import email.utils
import http.client
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

USER_AGENT = "ygjson/0.1 (+https://github.com/ArthurG-data/ygjson)"
ATTEMPTS = 5
BACKOFF_S = 2.0
MAX_WAIT_S = 120.0
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_last_request: dict[str, float] = {}


class FetchError(RuntimeError):
    """A download that failed for good."""


class Retry(Exception):
    """Raised by a check: fetch this again, after `wait` seconds when given."""

    def __init__(self, reason: str, wait: float | None = None):
        super().__init__(reason)
        self.wait = wait


class Refuse(Exception):
    """Raised by a check: the reply is an error that asking again will not fix."""


def retry_after(value: str | None) -> float | None:
    """The seconds a Retry-After header asks for (a number of seconds or an HTTP date), or None."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def _wait_for_host(host: str, delay: float) -> None:
    wait = _last_request.get(host, -delay) + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def get_json(url: str, *, timeout: float = 60.0, delay: float = 0.0,
             check: Callable[[Any, Mapping[str, str]], None] | None = None,
             attempts: int = ATTEMPTS) -> tuple[str, Any]:
    """(the body as text, the body parsed). `check(data, headers)` may raise Retry or Refuse."""
    host = urllib.parse.urlsplit(url).netloc
    reason = ""
    for attempt in range(1, attempts + 1):
        _wait_for_host(host, delay)
        wait: float | None = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    headers = resp.headers
            finally:
                _last_request[host] = time.monotonic()
            data = json.loads(raw)
            if check is not None:
                check(data, headers)
            return raw, data
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS:
                raise FetchError(f"{url}: HTTP {e.code} {e.reason}") from None
            reason, wait = f"HTTP {e.code} {e.reason}", retry_after(e.headers.get("Retry-After"))
        except Refuse as e:
            raise FetchError(f"{url}: {e}") from None
        except Retry as e:
            reason, wait = str(e), e.wait
        except (OSError, http.client.HTTPException, ValueError) as e:  # network, timeout, cut short, not JSON
            reason = f"{type(e).__name__}: {e}"
        if attempt < attempts:
            time.sleep(min(MAX_WAIT_S, wait if wait is not None else BACKOFF_S * 2 ** (attempt - 1)))
    raise FetchError(f"{url}: gave up after {attempts} attempts: {reason}")


def read_json(path: Path) -> Any | None:
    """The cached JSON at `path`, or None when the file is absent or is not valid JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` through a temporary file in the same directory, so `path` is never seen half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def cache_dir(cache: Path, refresh: bool) -> Iterator[Path]:
    """The directory to fetch `cache` into. Without refresh, `cache`. With refresh, an empty `<cache>.partial` that
    replaces `cache` when the block ends without an error, and is removed when it raises."""
    old = cache.with_name(cache.name + ".old")
    if not cache.exists() and old.exists():  # a swap stopped between its two renames
        old.rename(cache)
    if not refresh:
        yield cache
        return
    staging = cache.with_name(cache.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        yield staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(old, ignore_errors=True)
    if cache.exists():
        cache.rename(old)
    staging.rename(cache)
    shutil.rmtree(old, ignore_errors=True)
