import email.message
import http.client
import json
import urllib.error

import pytest

import fetch
import tcgcsv
import ygoprodeck
import yugipedia

URL = "https://example.test/api"


class Clock:
    """time.monotonic and time.sleep for fetch: sleeping moves the clock, and each sleep is recorded."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Reply:
    def __init__(self, body, headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}

    def read(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "nope", headers, None)


@pytest.fixture
def net(monkeypatch):
    """Replies queued in `net.replies` (a Reply, or an exception to raise), served in order; requests in `net.sent`."""
    clock = Clock()
    monkeypatch.setattr(fetch.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(fetch.time, "sleep", clock.sleep)
    monkeypatch.setattr(fetch, "_last_request", {})

    class Net:
        replies: list = []
        sent: list = []

    def urlopen(req, timeout):
        Net.sent.append((req, timeout))
        reply = Net.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    Net.replies, Net.sent, Net.clock = [], [], clock
    monkeypatch.setattr(fetch.urllib.request, "urlopen", urlopen)
    return Net


# --- get_json ---------------------------------------------------------------------------------------------------

def test_one_get_with_the_user_agent_and_the_timeout(net):
    net.replies = [Reply('{"a": 1}')]
    assert fetch.get_json(URL, timeout=7) == ('{"a": 1}', {"a": 1})
    (req, timeout), = net.sent
    assert (req.full_url, req.get_header("User-agent"), timeout) == (URL, fetch.USER_AGENT, 7)
    assert net.clock.sleeps == []


def test_a_server_error_is_retried_with_a_doubling_backoff(net):
    net.replies = [http_error(503), http_error(502), Reply("[1]")]
    assert fetch.get_json(URL)[1] == [1]
    assert net.clock.sleeps == [fetch.BACKOFF_S, fetch.BACKOFF_S * 2]


def test_retry_after_is_honoured_in_seconds_and_capped(net):
    net.replies = [http_error(429, "7"), http_error(429, "100000"), Reply("[]")]
    fetch.get_json(URL)
    assert net.clock.sleeps == [7.0, fetch.MAX_WAIT_S]


def test_retry_after_as_an_http_date(monkeypatch):
    monkeypatch.setattr(fetch.time, "time", lambda: 784111777.0)  # Sun, 06 Nov 1994 08:49:37 GMT
    assert fetch.retry_after("Sun, 06 Nov 1994 08:49:47 GMT") == 10.0
    assert fetch.retry_after("Sun, 06 Nov 1994 08:49:00 GMT") == 0.0
    assert fetch.retry_after("soon") is None
    assert fetch.retry_after(None) is None


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("connection refused"),
    TimeoutError("timed out"),
    ConnectionResetError("reset by peer"),
])
def test_a_network_error_is_retried(net, failure):
    net.replies = [failure, Reply('{"ok": true}')]
    assert fetch.get_json(URL)[1] == {"ok": True}
    assert len(net.sent) == 2


@pytest.mark.parametrize("cut", [Reply('{"results": [1, 2'), Reply(http.client.IncompleteRead(b'{"res'))])
def test_a_body_cut_short_is_retried(net, cut):
    net.replies = [cut, Reply('{"results": [1, 2]}')]
    assert fetch.get_json(URL)[1] == {"results": [1, 2]}


def test_a_client_error_is_not_retried_and_names_the_url(net):
    net.replies = [http_error(404)]
    with pytest.raises(fetch.FetchError, match=rf"^{URL}: HTTP 404"):
        fetch.get_json(URL)
    assert len(net.sent) == 1


def test_it_gives_up_after_the_last_attempt_naming_the_url_and_the_reason(net):
    net.replies = [http_error(500)] * fetch.ATTEMPTS
    with pytest.raises(fetch.FetchError, match=rf"^{URL}: gave up after {fetch.ATTEMPTS} attempts: HTTP 500"):
        fetch.get_json(URL)
    assert len(net.sent) == fetch.ATTEMPTS
    assert len(net.clock.sleeps) == fetch.ATTEMPTS - 1  # no wait after the last attempt


def test_a_check_can_ask_again_or_refuse(net):
    def check(data, headers):
        if data.get("busy"):
            raise fetch.Retry("busy", 3.0)
        if data.get("bad"):
            raise fetch.Refuse("bad reply")

    net.replies = [Reply('{"busy": 1}'), Reply('{"fine": 1}')]
    assert fetch.get_json(URL, check=check)[1] == {"fine": 1}
    assert net.clock.sleeps == [3.0]
    net.replies = [Reply('{"bad": 1}')]
    with pytest.raises(fetch.FetchError, match=rf"^{URL}: bad reply$"):
        fetch.get_json(URL, check=check)


def test_requests_to_one_host_are_spaced_by_the_delay(net):
    net.replies = [Reply("1"), Reply("2"), Reply("3")]
    fetch.get_json(URL, delay=1.5)
    net.clock.now += 0.5
    fetch.get_json(URL, delay=1.5)
    fetch.get_json("https://other.test/x", delay=1.5)
    assert net.clock.sleeps == [1.0]


# --- the cache --------------------------------------------------------------------------------------------------

def test_write_atomic_replaces_the_file_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "sub" / "a.json"
    fetch.write_atomic(path, "[1]")
    fetch.write_atomic(path, "[2]")
    assert path.read_text() == "[2]"
    assert [p.name for p in path.parent.iterdir()] == ["a.json"]


def test_an_interrupted_write_leaves_the_old_file_whole(tmp_path, monkeypatch):
    path = tmp_path / "a.json"
    path.write_text("[1]")

    def crash(src, dst):
        raise KeyboardInterrupt

    monkeypatch.setattr(fetch.os, "replace", crash)
    with pytest.raises(KeyboardInterrupt):
        fetch.write_atomic(path, "[2, 3]")
    assert path.read_text() == "[1]"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_read_json_treats_a_truncated_file_as_absent(tmp_path):
    (tmp_path / "cut.json").write_text('{"results": [')
    (tmp_path / "ok.json").write_text("[]")
    assert fetch.read_json(tmp_path / "cut.json") is None
    assert fetch.read_json(tmp_path / "gone.json") is None
    assert fetch.read_json(tmp_path / "ok.json") == []


def test_cache_dir_without_refresh_is_the_cache_itself(tmp_path):
    with fetch.cache_dir(tmp_path / "c", refresh=False) as d:
        assert d == tmp_path / "c"


def test_a_refresh_swaps_in_a_new_directory_when_it_succeeds(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "old.json").write_text("[]")
    with fetch.cache_dir(cache, refresh=True) as d:
        assert d != cache and not list(d.iterdir())
        (d / "new.json").write_text("[]")
        assert (cache / "old.json").exists()  # untouched until the whole fetch is done
    assert [p.name for p in cache.iterdir()] == ["new.json"]
    assert [p.name for p in tmp_path.iterdir()] == ["c"]


def test_a_refresh_that_fails_keeps_the_old_cache_whole(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "old.json").write_text("[]")
    with pytest.raises(fetch.FetchError), fetch.cache_dir(cache, refresh=True) as d:
        (d / "new.json").write_text("[]")
        raise fetch.FetchError("halfway")
    assert [p.name for p in cache.iterdir()] == ["old.json"]
    assert [p.name for p in tmp_path.iterdir()] == ["c"]


def test_a_refresh_into_no_cache_yet(tmp_path):
    with fetch.cache_dir(tmp_path / "c", refresh=True) as d:
        (d / "new.json").write_text("[]")
    assert [p.name for p in (tmp_path / "c").iterdir()] == ["new.json"]


def test_a_swap_stopped_between_its_renames_is_put_back(tmp_path):
    (tmp_path / "c.old").mkdir()
    (tmp_path / "c.old" / "a.json").write_text("[]")
    with fetch.cache_dir(tmp_path / "c", refresh=False) as d:
        assert (d / "a.json").exists()


# --- the sources ------------------------------------------------------------------------------------------------

def test_a_truncated_cache_file_is_fetched_again(tmp_path, monkeypatch):
    (tmp_path / "2_groups.json").write_text('{"success": true, "results": [{"grou')
    (tmp_path / "dbver.json").write_text('[{"database_ver')
    asked = []

    def get_json(url, **kw):
        asked.append(url)
        data = {"success": True, "results": [{"groupId": 5}]} if "tcgcsv" in url else [{"database_version": "1"}]
        return json.dumps(data), data

    monkeypatch.setattr(fetch, "get_json", get_json)
    assert tcgcsv.groups(tmp_path) == [{"groupId": 5}]
    assert ygoprodeck.db_version(tmp_path) == {"database_version": "1"}
    assert len(asked) == 2
    assert tcgcsv.groups(tmp_path) == [{"groupId": 5}] and len(asked) == 2  # now cached whole


def test_tcgcsv_refuses_a_reply_that_says_it_failed(net, tmp_path):
    net.replies = [Reply('{"success": false, "errors": ["down"], "results": []}')]
    with pytest.raises(fetch.FetchError, match=r"TCGCSV says \['down'\]"):
        tcgcsv.groups(tmp_path)
    assert not list(tmp_path.iterdir())


def test_yugipedia_asks_with_maxlag_and_waits_out_a_lagged_reply(net, tmp_path):
    lagged = Reply('{"error": {"code": "maxlag", "info": "Waiting for a database server: 7 seconds lagged"}}',
                   {"Retry-After": "6"})
    net.replies = [lagged, Reply('{"query": {"pages": [{"pageid": 3, "title": "T", "revisions": []}]}}')]
    assert yugipedia.page_by_id(3, tmp_path) == {"pageid": 3, "title": "T", "revisions": []}
    assert "maxlag=5" in net.sent[0][0].full_url
    assert 6.0 in net.clock.sleeps


@pytest.mark.parametrize("body, reason", [
    ('{"error": {"code": "badvalue", "info": "Unrecognized value"}}', "MediaWiki error badvalue: Unrecognized value"),
    ('{"batchcomplete": true}', "the reply holds no query.pages"),
])
def test_yugipedia_names_an_api_error_instead_of_a_key_error(net, tmp_path, body, reason):
    net.replies = [Reply(body)]
    with pytest.raises(fetch.FetchError, match=reason):
        yugipedia.page_by_id(3, tmp_path)
    assert not list(tmp_path.iterdir())
