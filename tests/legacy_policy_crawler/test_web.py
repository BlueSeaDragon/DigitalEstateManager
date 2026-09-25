"""Offline tests for the web helpers: website names, ranking, page parsing, robots.txt, fetching, search."""

import sys
import types
from typing import ClassVar

import httpx
import pytest

from legacy_policy_crawler import web
from legacy_policy_crawler.prompts import count_keywords, relevant_sentences

HTML = b"""<html><head><title> Help  - Acme </title></head><body>
<header><a href="/login">Log in</a></header>
<nav><a href="/products">Products</a></nav>
<main><h1>Deceased users</h1>
<p>If a member <a href="/help/legacy">has passed away</a>, contact us.</p>
<ul><li>Death certificate</li><li>Proof of relationship</li></ul></main>
<footer><a href="https://www.acme.com/legal#top">Legal</a>
<a href="mailto:x@acme.com">Mail</a> <a href="javascript:void(0)">JS</a></footer>
<script>var hidden = 1;</script></body></html>"""


def test_normalize_website():
    assert web.normalize_website("www.google.com") == "google.com"
    assert web.normalize_website("https://www.Google.com/foo?x=1") == "google.com"
    assert web.normalize_website("  spotify.com/ ") == "spotify.com"
    assert web.normalize_website("https://aws.amazon.com") == "aws.amazon.com"
    assert web.normalize_website("google.com:8080/x") == "google.com"
    assert web.normalize_website("") == ""
    assert web.normalize_website("http://[bad") == ""


def test_brand_registrable_and_same_brand():
    assert web.brand("support.google.com") == "google"
    assert web.brand("bbc.co.uk") == "bbc"
    assert web.brand("news.bbc.co.uk") == "bbc"
    assert web.registrable("support.google.com") == "google.com"
    assert web.registrable("news.bbc.co.uk") == "bbc.co.uk"
    assert web.same_brand("https://support.google.com/x", "google.com")
    assert web.same_brand("https://google.co.uk/x", "google.com")
    # the brand is the registrable name
    assert not web.same_brand("https://google.evil.com/x", "google.com")
    assert not web.same_brand("https://evilgoogle.com/", "google.com")
    assert not web.same_brand("https://example.org/", "google.com")
    assert not web.same_brand("not a url", "google.com")


def test_keywords_use_word_boundaries_and_several_languages():
    # 'heir' inside a word must not count
    assert count_keywords("their account and the theirs") == 0
    assert count_keywords("Todesfall und Nachlass") == 2
    assert count_keywords("En cas de décès, la succession") == 2
    assert count_keywords("In caso di decesso degli eredi") == 2
    assert count_keywords("Account of a deceased user") == 1
    found = relevant_sentences(
        "Intro line.\nWhen a user has died we close the account. Other text.", limit=2
    )
    assert found == ["When a user has died we close the account."]


def test_score_link_prefers_official_policy_pages():
    policy = web.score_link(
        "https://support.google.com/accounts/troubleshooter/6357590",
        "Submit a request regarding a deceased user's account",
    )
    help_page = web.score_link(
        "https://support.google.com/accounts/answer/1", "About your account"
    )
    shop = web.score_link("https://store.example.com/cart", "Your cart")
    forum = web.score_link(
        "https://community.example.com/t5/thread/1", "Account holder has died"
    )
    assert policy > help_page > shop
    assert policy > forum  # user posts rank below official pages
    assert (
        web.score_link(
            "https://www.swisscom.ch/de/privatkunden/hilfe/todesfall.html",
            "Todesfall melden",
        )
        >= 3.0
    )


def test_user_posts_are_recognised_by_their_address():
    for url in (
        "https://community.spotify.com/t5/Accounts/Deceased-user/m-p/1",
        "https://sellercentral.amazon.com/seller-forums/discussions/t/3ef",
        "https://support.google.com/accounts/thread/425/deceased-family-member",
        "https://learn.microsoft.com/en-us/answers/questions/5612065/how-do-i",
        "https://discussions.apple.com/thread/253888249",
    ):
        assert web.is_user_post(url), url
    for url in (
        "https://support.google.com/accounts/troubleshooter/6357590",
        "https://support.google.com/accounts/answer/3036546",  # 'answer' is an official article
        "https://help.netflix.com/en/node/110165",
        "https://support.apple.com/en-us/102431",
        "https://www.commune.example.ch/tod",  # 'commune' is not 'community'
    ):
        assert not web.is_user_post(url), url


def test_parse_page_text_links_and_title():
    page = web.parse_page("https://www.acme.com/help/", HTML)
    assert page.title == "Help - Acme"
    assert page.text.splitlines() == [
        "Deceased users",
        "If a member has passed away, contact us.",  # the inline link stays on its line
        "Death certificate",
        "Proof of relationship",
    ]
    links = dict(page.links)
    # header and footer links are still collected
    assert links["https://www.acme.com/login"] == "Log in"
    assert links["https://www.acme.com/help/legacy"] == "has passed away"
    assert "https://www.acme.com/legal" in links  # fragment removed
    assert not any(url.startswith(("mailto:", "javascript:")) for url in links)


ROBOTS = """
# comment
USER-AGENT: *
User-agent: Yandex
Disallow: /search
Allow: /search/about
Disallow: /?
Disallow: /private/*.pdf$

User-agent: DigitalEstateManagerBot
Disallow: /secret
"""


def permitted(text, path):
    return web._robots_permits(web._robots_rules(text), path)


def test_robots_star_group_wildcards_and_longest_match():
    star = ROBOTS.split("User-agent: DigitalEstateManagerBot")[0]
    # urllib.robotparser wrongly blocks this because of 'Disallow: /?'
    assert permitted(star, "/")
    assert not permitted(star, "/?hl=en")
    assert not permitted(star, "/search")
    assert permitted(star, "/search/about")  # the longer Allow wins
    assert not permitted(star, "/private/a/b.pdf")
    # '$' anchors at the end of path and query
    assert permitted(star, "/private/a.pdf?x=1")
    assert permitted(star, "/private/a.html")
    # an empty Disallow allows everything
    assert permitted("User-agent: *\nDisallow:\n", "/anything")


def test_robots_own_group_beats_star_group():
    assert not permitted(ROBOTS, "/secret")
    assert permitted(ROBOTS, "/search")  # only our own group applies to us
    assert not permitted("User-agent: *\nDisallow: /\n", "/page")
    assert permitted("", "/page")


@pytest.fixture
def fake_web(monkeypatch):
    """A web client backed by canned responses; returns the list of requested URLs."""
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /blocked\n",
                headers={"content-type": "text/plain"},
            )
        if path == "/old":
            return httpx.Response(
                302, headers={"location": "https://www.acme.com/help/"}
            )
        if path == "/help/":
            return httpx.Response(
                200, content=HTML, headers={"content-type": "text/html; charset=utf-8"}
            )
        if path == "/file.pdf":
            return httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            )
        if path == "/blocked":
            return httpx.Response(
                200, content=HTML, headers={"content-type": "text/html"}
            )
        return httpx.Response(404, text="nope")

    monkeypatch.setattr(
        web,
        "_client",
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    monkeypatch.setattr(web, "_robots", {})
    monkeypatch.setattr(web, "PAUSE", 0.0)
    return requested


def test_fetch_page_follows_redirects_and_parses(fake_web):
    page = web.fetch_page("https://www.acme.com/old")
    assert page.url == "https://www.acme.com/help/"
    assert page.title == "Help - Acme"
    assert "Death certificate" in page.text


def test_fetch_page_reports_problems_as_fetch_errors(fake_web):
    with pytest.raises(web.FetchError, match="HTTP 404"):
        web.fetch_page("https://www.acme.com/missing")
    with pytest.raises(web.FetchError, match="not a web page"):
        web.fetch_page("https://www.acme.com/file.pdf")
    with pytest.raises(web.FetchError, match="robots.txt"):
        web.fetch_page("https://www.acme.com/blocked")
    # robots.txt is fetched once per site
    assert fake_web.count("https://www.acme.com/robots.txt") == 1


def test_fetch_page_network_error_becomes_fetch_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(
        web, "_client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(web, "_robots", {})
    monkeypatch.setattr(web, "PAUSE", 0.0)
    with pytest.raises(web.FetchError, match="ConnectError"):
        web.fetch_page("https://www.acme.com/help/")


class FakeDDGS:
    calls: ClassVar[list] = []
    behaviour: ClassVar[dict] = {}

    def text(self, query, max_results=8, backend="auto"):
        FakeDDGS.calls.append(backend)
        result = FakeDDGS.behaviour[backend]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def fake_ddgs(monkeypatch):
    FakeDDGS.calls, FakeDDGS.behaviour = [], {}
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    monkeypatch.setattr(web, "_last_search", 0.0)
    monkeypatch.setattr(web, "_search_gap", 0.0)
    monkeypatch.setattr(web, "SEARCH_GAP", 0.0)
    return FakeDDGS


def test_search_falls_back_to_the_next_engine(fake_ddgs):
    fake_ddgs.behaviour = {
        "yahoo": Exception("No results found."),
        "auto": [
            {"href": "https://a.example/x", "title": "T", "body": "B"},
            {"title": "no href"},
        ],
        "bing": [],
    }
    assert web.search("q") == [("https://a.example/x", "T", "B")]
    assert fake_ddgs.calls == ["yahoo", "auto"]


def fake_clock(monkeypatch):
    """Replace the clock of the web module; sleeping advances it. Returns the list of sleeps."""
    clock = {"now": 100.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(
        web, "time", types.SimpleNamespace(monotonic=lambda: clock["now"], sleep=sleep)
    )
    return slept


def test_searches_are_spaced_apart(fake_ddgs, monkeypatch):
    slept = fake_clock(monkeypatch)
    monkeypatch.setattr(web, "SEARCH_GAP", 4.0)
    monkeypatch.setattr(web, "_search_gap", 4.0)
    fake_ddgs.behaviour = {"yahoo": [{"href": "https://a.example/x"}]}
    for _ in range(3):
        web.search("q")
    # the first search starts at once
    assert slept == [pytest.approx(4.0), pytest.approx(4.0)]


def test_search_gap_doubles_after_a_failure_and_resets_after_a_success(
    fake_ddgs, monkeypatch
):
    slept = fake_clock(monkeypatch)
    monkeypatch.setattr(web, "SEARCH_GAP", 4.0)
    monkeypatch.setattr(web, "_search_gap", 4.0)
    fake_ddgs.behaviour = {b: Exception("blocked") for b in web.SEARCH_BACKENDS}
    assert web.search("first") == []  # no engine answered: the gap doubles
    assert web._search_gap == 8.0
    fake_ddgs.behaviour = {"yahoo": [{"href": "https://a.example/x"}]}
    assert web.search("second")  # waits the doubled gap; it worked, so the gap resets
    assert web._search_gap == 4.0
    assert web.search("third")
    assert slept == [pytest.approx(8.0), pytest.approx(4.0)]


def test_search_gap_is_capped(fake_ddgs, monkeypatch):
    fake_clock(monkeypatch)
    monkeypatch.setattr(web, "_search_gap", 30.0)
    fake_ddgs.behaviour = {b: Exception("blocked") for b in web.SEARCH_BACKENDS}
    web.search("q")
    assert web._search_gap == web.SEARCH_GAP_MAX
