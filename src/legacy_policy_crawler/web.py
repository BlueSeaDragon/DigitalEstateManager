"""Web helpers: website names, fetching and parsing pages, web search, link ranking.

Polite by design: public HTML pages only, an identifying User-Agent, robots.txt respected,
and a short pause between requests to the same host.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .prompts import HELP_RE, NOISE_RE, OFFICIAL_HOST_RE, STRONG_RE, USER_POSTS_RE

BOT_NAME = "DigitalEstateManagerBot"
USER_AGENT = f"Mozilla/5.0 (compatible; {BOT_NAME}/0.1)"
MAX_BYTES = 2_000_000  # read at most this much of a page
PAUSE = 0.5  # seconds between requests to the same host
SEARCH_BACKENDS = ("yahoo", "auto", "bing")  # tried in this order
SEARCH_GAP = 5.0  # seconds between searches: the engines throttle bursts
SEARCH_GAP_MAX = 40.0  # the gap doubles after a failed search, up to this
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}  # as in bbc.co.uk
# Tags removed before reading a page's text (links are collected first).
DROP_TAGS = [
    "script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe",
]  # fmt: skip
# Tags that get line breaks around them, so text inside links stays on one line.
BLOCK_TAGS = [
    "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "blockquote", "pre",
]  # fmt: skip

_client = httpx.Client(
    headers={"User-Agent": USER_AGENT, "Accept-Language": "en;q=0.9,de;q=0.6,fr;q=0.5"},
    follow_redirects=True,
    max_redirects=5,
    timeout=httpx.Timeout(15.0),
)
# origin -> the robots.txt rules that apply to us
_robots: dict[str, list[tuple[str, bool]]] = {}
_last_hit: dict[str, float] = {}
_hit_lock = threading.Lock()
_search_lock = threading.Lock()
_last_search = 0.0
_search_gap = SEARCH_GAP  # doubles after a failed search, resets after a good one


class FetchError(Exception):
    """A page could not be fetched; the message is a short reason."""


@dataclass
class Page:
    url: str
    title: str
    text: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (URL, anchor text)


# --- website names ---------------------------------------------------------------------------


def normalize_website(text: str) -> str:
    """'https://www.Google.com/foo' -> 'google.com'; '' if invalid."""
    text = text.strip()
    if "://" not in text:
        text = "//" + text
    try:
        host = (urlsplit(text).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _name_labels(host: str) -> int:
    """Number of trailing labels of the registrable domain (3 for bbc.co.uk, else 2)."""
    labels = host.split(".")
    return (
        3
        if len(labels) >= 3 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2
        else 2
    )


def brand(host: str) -> str:
    """The name label of a host: 'support.google.com' -> 'google', 'bbc.co.uk' -> 'bbc'."""
    labels = host.lower().split(".")
    if len(labels) < 2:
        return labels[0]
    return labels[-_name_labels(host)]


def registrable(host: str) -> str:
    """'support.google.com' -> 'google.com'."""
    labels = host.lower().split(".")
    return ".".join(labels[-_name_labels(host) :])


def same_brand(url: str, website: str) -> bool:
    """True if the URL belongs to the website's brand (support.google.com for google.com)."""
    host = _host(url)
    return bool(host) and brand(host) == brand(website)


# --- ranking ---------------------------------------------------------------------------------


def _url_words(url: str) -> str:
    """Host, path and query of a URL as plain words."""
    parts = urlsplit(url)
    return re.sub(
        r"[-_/.+=&?]", " ", unquote(f"{parts.netloc}{parts.path} {parts.query}")
    )


def is_user_post(url: str) -> bool:
    """True for community, forum and Q&A pages: posts by users are not company policy."""
    return USER_POSTS_RE.search(_url_words(url)) is not None


def score_link(url: str, label: str = "") -> float:
    """How likely a link leads to a deceased-account policy (higher is better)."""
    parts = urlsplit(url)
    text = f"{_url_words(url)} {label}"
    score = 3.0 * len({m.lower() for m in STRONG_RE.findall(text)})
    score += 0.5 * len({m.lower() for m in HELP_RE.findall(text)})
    score -= 2.0 * len({m.lower() for m in NOISE_RE.findall(text)})
    if OFFICIAL_HOST_RE.match(parts.netloc):
        score += 2.0
    return score


# --- pages -----------------------------------------------------------------------------------


def _absolute(base: str, href: str) -> str | None:
    try:
        url = urldefrag(urljoin(base, href.strip()))[0]
        return url if urlsplit(url).scheme in ("http", "https") else None
    except ValueError:
        return None


def parse_page(url: str, html: bytes | str) -> Page:
    """HTML -> title, readable text and all links."""
    soup = BeautifulSoup(html, "html.parser")
    title = " ".join(soup.title.get_text().split()) if soup.title else ""
    links, seen = [], {url}
    # links are collected before tags are removed, so footer links count
    for anchor in soup.find_all("a", href=True):
        href = _absolute(url, anchor["href"])
        if href and href not in seen:
            seen.add(href)
            links.append((href, " ".join(anchor.get_text(" ").split())[:120]))
    for tag in soup(DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    for tag in root.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = (" ".join(line.split()) for line in root.get_text().splitlines())
    return Page(
        url=url,
        title=title,
        text="\n".join(line for line in lines if line),
        links=links,
    )


def _robots_rules(text: str) -> list[tuple[str, bool]]:
    """The (pattern, allow) rules for this bot: its own group, else the '*' group.

    Not urllib.robotparser: it turns 'Disallow: /?' into 'Disallow: /' and blocks whole sites.
    """
    groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, bool]] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if in_rules:  # a new group starts
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
        elif field in ("allow", "disallow"):
            in_rules = True
            if value:  # an empty Disallow means "allow everything"
                rules.append((value, field == "allow"))
    groups.append((agents, rules))
    ours = [r for a, r in groups if BOT_NAME.lower() in a]
    star = [r for a, r in groups if "*" in a]
    return (ours or star or [[]])[0]


def _robots_match(pattern: str, target: str) -> bool:
    """A robots.txt pattern (with '*' and a trailing '$') against a path and query."""
    regex = re.escape(pattern).replace(r"\*", ".*")
    if regex.endswith(r"\$"):
        regex = regex[:-2] + "$"
    return re.match(regex, target) is not None


def robots_allowed(url: str) -> bool:
    """True if the site's robots.txt lets our bot fetch this URL (read once per site)."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        rules: list[tuple[str, bool]] = []
        try:
            response = _client.get(f"{origin}/robots.txt", timeout=8.0)
            if (
                response.status_code == 200
                and "html" not in response.headers.get("content-type", "").lower()
            ):
                rules = _robots_rules(response.text)
        except (httpx.HTTPError, httpx.InvalidURL):
            pass  # no readable robots.txt: allowed
        _robots[origin] = rules
    return _robots_permits(
        _robots[origin],
        (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
    )


def _robots_permits(rules: list[tuple[str, bool]], target: str) -> bool:
    """The longest matching pattern wins, Allow on a tie; no match means allowed."""
    best_length, allowed = -1, True
    for pattern, allow in rules:
        if _robots_match(pattern, target) and (
            len(pattern) > best_length or (len(pattern) == best_length and allow)
        ):
            best_length, allowed = len(pattern), allow
    return allowed


def _pause(host: str) -> None:
    with _hit_lock:
        wait = _last_hit.get(host, 0.0) + PAUSE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.monotonic()


def fetch_page(url: str) -> Page:
    """Download one HTML page. Raises FetchError with a short reason."""
    if not robots_allowed(url):
        raise FetchError("disallowed by robots.txt")
    _pause(urlsplit(url).netloc)
    try:
        with _client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}")
            kind = response.headers.get("content-type", "").lower()
            if "html" not in kind and "text/plain" not in kind:
                raise FetchError(f"not a web page ({kind or 'unknown type'})")
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) >= MAX_BYTES:
                    break
            final_url = str(response.url)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise FetchError(type(e).__name__) from e
    return parse_page(final_url, body)


def search(query: str, max_results: int = 8) -> list[tuple[str, str, str]]:
    """Keyless web search (ddgs): (url, title, snippet) tuples, empty if search fails."""
    global _last_search, _search_gap
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    with _search_lock:  # keep searches apart
        wait = _last_search + _search_gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_search = time.monotonic()
    for backend in SEARCH_BACKENDS:
        try:
            hits = DDGS().text(query, max_results=max_results, backend=backend)
        except Exception:
            continue  # ddgs raises its own errors (no results, rate limit, timeout)
        if hits:
            _search_gap = SEARCH_GAP
            return [
                (h["href"], h.get("title", ""), h.get("body", ""))
                for h in hits
                if h.get("href")
            ]
    # no engine answered: slow down; the agent goes on without search
    _search_gap = min(_search_gap * 2, SEARCH_GAP_MAX)
    return []
