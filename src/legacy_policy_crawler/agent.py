"""The agent: finds a company's legacy-policy page with Apertus and returns a JSON record.

1. Collect candidate pages: web search, the homepage and common help-center addresses.
2. Loop: Apertus picks the next numbered candidate (open / search / finish).
3. One extraction call on the chosen page gives the summary and tick boxes.
4. The record is saved in data/legacy_policies.json.

The model answers with candidate numbers, never URLs, so it cannot invent a link.
"""

from __future__ import annotations

import datetime
import re
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from . import store
from .llm import AuthError, JSONError, LLMError, chat_json
from .prompts import (
    EXTRACT_PROMPT,
    NAVIGATE_NO_SEARCH,
    NAVIGATE_PROMPT,
    TICK_KEYS,
    count_keywords,
    relevant_sentences,
)
from .web import (
    FetchError,
    Page,
    brand,
    fetch_page,
    is_user_post,
    normalize_website,
    registrable,
    robots_allowed,
    same_brand,
    score_link,
    search,
)

MAX_STEPS = 8  # navigation calls per website
MAX_PAGES = 10  # pages fetched per website, homepage included
MAX_SEARCHES = 2  # searches the model may ask for (the two seed searches come on top)
MAX_EXTRACTIONS = 2  # extraction calls per website
SHOWN = 12  # candidates shown to the model per step
STRONG_SCORE = 4.0  # link score of a strong candidate
PAGE_CHARS = 12_000  # page text sent to the extraction call

# A provider without a clear policy gets NOT_FOUND as link and NO_POLICY as summary.
NOT_FOUND = "not found"
NO_POLICY = "none"

# Candidate statuses for pages the crawler cannot read (403, or robots.txt disallows them).
BLOCKED = "skipped: the site blocks bots (HTTP 403)"
FORBIDDEN = "failed: HTTP 403"
ROBOTS = "skipped: disallowed by robots.txt"
ROBOTS_FAILED = "failed: disallowed by robots.txt"
SKIPPED = (BLOCKED, ROBOTS)  # never tried
UNREADABLE = (*SKIPPED, FORBIDDEN, ROBOTS_FAILED)

# files the crawler does not read
FILE_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")  # fmt: skip
LEAD_NOTE = (
    "(Based on the search result only: the crawler could not read the page itself.)"
)
UNSAVED_TTL = (
    600.0  # seconds an unsaved "not found" is reused instead of crawling again
)

# (website, file) -> (time, record) of results that were not saved
_unsaved: dict[tuple[str, str], tuple[float, dict]] = {}


def make_record(
    website: str, url: str, summary: str, ticks: dict | None = None
) -> dict:
    """One record of data/legacy_policies.json."""
    ticks = ticks or {}
    return {
        "website": website,
        "legacy_policy_url": url,
        "summary": summary,
        "tick_boxes": {key: ticks.get(key) for key in TICK_KEYS},
        "checked": datetime.date.today().isoformat(),
    }


def _tri(value: object) -> bool | None:
    """A tick box is true, false or None (not stated)."""
    if isinstance(value, str):
        value = {"true": True, "yes": True, "false": False, "no": False}.get(
            value.strip().lower()
        )
    return value if isinstance(value, bool) else None


def _squash(text: str) -> str:
    """Lower-case letters and digits only, so quotes match despite spacing and punctuation."""
    return "".join(char for char in text.lower() if char.isalnum())


def _quote_on_page(quote: str, page: str) -> bool:
    """True if every part of the quote is on the page (`page` is squashed text).

    The quote is split at ellipses, colons and semicolons, because the model sometimes skips
    lines in between. Tiny parts are ignored.
    """
    parts = [_squash(part) for part in re.split(r"\.\.\.|…|[:;]", quote)]
    parts = [part for part in parts if len(part) >= 6]
    return sum(len(part) for part in parts) >= 12 and all(
        part in page for part in parts
    )


def _verified_ticks(data: dict, page_text: str) -> dict:
    """The model's tick boxes. A box stays true/false only if its quote is really on the page."""
    boxes = data.get("tick_boxes") if isinstance(data.get("tick_boxes"), dict) else {}
    proof = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    page = _squash(page_text)
    ticks = {}
    for key in TICK_KEYS:
        value = _tri(boxes.get(key))
        proved = _quote_on_page(str(proof.get(key) or ""), page)
        ticks[key] = value if value is not None and proved else None
    return ticks


def _short(text: object, limit: int = 3) -> str:
    """At most `limit` sentences on one line."""
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
    return " ".join(sentences[:limit])


class Run:
    """State of one lookup: numbered candidate pages, fetched pages and counters."""

    def __init__(self, host: str, trace: Callable[[str], None]):
        self.host = host
        self.root = registrable(host)
        self.trace = trace
        # each candidate: id, url, label, snippet, score, status (None until tried)
        self.candidates: list[dict] = []
        self.pages: dict[int, Page] = {}  # candidate id -> fetched page
        self.fetched = self.searches = self.extractions = self.search_hits = 0
        self.step_limit = MAX_STEPS  # grows by one when a search finds new pages
        self.queries: list[str] = []  # searches done so far
        self.blocked: set[str] = set()  # hosts that answered 403

    # -- candidates --------------------------------------------------------------------------

    def add(
        self, url: str, label: str = "", bonus: float = 0.0, hint: str = ""
    ) -> None:
        """Add a candidate page. Other brands, duplicates, files and user posts are ignored."""
        url = url.split("#")[0]
        if not same_brand(url, self.host) or self.by_url(url):
            return
        parts = urlsplit(url)
        if parts.path.lower().endswith(FILE_SUFFIXES) or is_user_post(url):
            return
        if parts.netloc in self.blocked:
            status = BLOCKED
        elif not robots_allowed(url):
            status = ROBOTS
        else:
            status = None
        self.candidates.append(
            {
                "id": len(self.candidates) + 1,
                "url": url,
                "label": " ".join(label.split())[:100],
                "snippet": " ".join(hint.split())[:300],
                "score": round(score_link(url, f"{label} {hint}") + bonus, 1),
                "status": status,
            }
        )

    def by_url(self, url: str) -> dict | None:
        return next((c for c in self.candidates if c["url"] == url), None)

    def by_id(self, cid: int) -> dict:
        return next(c for c in self.candidates if c["id"] == cid)

    def pick(self, cid: object, opened: bool) -> dict | None:
        """The candidate with this number, if it is untried (opened=False) or opened (True)."""
        try:
            cid = int(cid)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        cand = next((c for c in self.candidates if c["id"] == cid), None)
        if cand is None or (cid in self.pages) != opened:
            return None
        return cand if opened or cand["status"] is None else None

    def top_unopened(self, count: int) -> list[dict]:
        untried = [c for c in self.candidates if c["status"] is None]
        return sorted(untried, key=lambda c: -c["score"])[:count]

    # -- actions -----------------------------------------------------------------------------

    def run_search(self, query: str, counted: bool = True) -> None:
        if counted:
            self.searches += 1
        self.queries.append(" ".join(query.split()))
        hits = search(query)
        self.search_hits += len(hits)
        self.trace(f"  search: {query} ({len(hits)} hits)")
        for url, title, snippet in hits:
            self.add(url, title, bonus=1.0, hint=snippet)

    def open(self, cand: dict) -> Page | None:
        if self.fetched >= MAX_PAGES:
            cand["status"] = "skipped: page limit reached"
            return None
        self.fetched += 1
        self.trace(f"  open [{cand['id']}] {cand['url']}")
        try:
            page = fetch_page(cand["url"])
        except FetchError as e:
            cand["status"] = f"failed: {e}"
            self.trace(f"    {cand['status']}")
            if cand["status"] == FORBIDDEN:  # skip the site's other pages too
                host = urlsplit(cand["url"]).netloc
                self.blocked.add(host)
                for other in self.candidates:
                    if (
                        other["status"] is None
                        and urlsplit(other["url"]).netloc == host
                    ):
                        other["status"] = BLOCKED
            return None
        if not same_brand(page.url, self.host):
            cand["status"] = "failed: redirected to another site"
            return None
        cand["status"] = "opened"
        self.pages[cand["id"]] = page
        for url, anchor in page.links:
            self.add(url, anchor)
        return page

    def seed(self) -> None:
        """Candidates from web search, the homepage and common help-center addresses."""
        queries = (
            f"site:{self.root} deceased user account",
            f"{brand(self.host)} help center account of someone who has died",
        )
        for number, query in enumerate(queries):
            if number and sum(c["score"] >= STRONG_SCORE for c in self.candidates) >= 2:
                break  # the first search was enough
            self.run_search(query, counted=False)
        for home in (f"https://{self.host}/", f"https://www.{self.host}/"):
            self.add(home, "homepage", bonus=-10.0)
            if self.open(self.by_url(home)):
                break
        for guess in (
            f"https://support.{self.root}/",
            f"https://help.{self.root}/",
            f"https://{self.host}/help",
            f"https://{self.host}/legal",
        ):
            # a guess may not exist, so it ranks below real links
            self.add(guess, "guess", bonus=-2.0)

    # -- prompts -----------------------------------------------------------------------------

    def messages(self, step: int, last: int | None) -> list[dict]:
        left = MAX_SEARCHES - self.searches
        lines = [
            f"Website: {self.host}",
            f"Step {step} of {self.step_limit}. "
            + (
                f"Searches left: {left}."
                if left > 0
                else "No searches left: answer open or finish."
            ),
        ]
        if self.queries:
            lines.append("Searches already done: " + " | ".join(self.queries))
        tried = [
            c
            for c in self.candidates
            if c["status"] and not c["status"].startswith("skipped")
        ]
        skipped = [c for c in self.candidates if c["status"] in SKIPPED]
        if tried:
            lines += ["", "Already tried:"]
            for c in tried:
                page = self.pages.get(c["id"])
                hits = f", {count_keywords(page.text)} keyword hits" if page else ""
                lines.append(f"[{c['id']}] {c['url']} - {c['status']}{hits}")
        if skipped:
            lines.append(
                f"({len(skipped)} more candidates cannot be read: their site blocks bots or robots.txt disallows them.)"
            )
        lines += ["", "Candidate pages not opened yet (best first):"]
        shown = self.top_unopened(SHOWN)
        lines += [
            f"[{c['id']}] {c['url']} | {c['label']} | score {c['score']}" for c in shown
        ] or ["(none)"]
        if last is not None:
            page = self.pages[last]
            lines += [
                "",
                f"Last opened page [{last}]:",
                "<page>",
                f"Title: {page.title}",
                page.text[:1200],
            ]
            lines += [f"- {sentence}" for sentence in relevant_sentences(page.text)]
            lines.append("</page>")
        prompt = NAVIGATE_PROMPT if left > 0 else NAVIGATE_NO_SEARCH
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "\n".join(lines)},
        ]

    def _read(self, page: Page) -> dict | None:
        """One Apertus call on a page's text. The model's answer, or None if it was not JSON."""
        self.trace(f"  extract from {page.url}")
        user = f"Website: {self.host}\nPage URL: {page.url}\n<page>\n{page.text[:PAGE_CHARS]}\n</page>"
        try:
            return chat_json(
                [
                    {"role": "system", "content": EXTRACT_PROMPT},
                    {"role": "user", "content": user},
                ],
                max_tokens=600,
            )
        except JSONError:
            return None

    def extract(self, cid: int) -> dict | None:
        """Read an opened page. The record, or None if the page states no policy."""
        cand, page = self.by_id(cid), self.pages[cid]
        if cand.get("extracted") or self.extractions >= MAX_EXTRACTIONS:
            return None
        cand["extracted"] = True
        self.extractions += 1
        data = self._read(page)
        if data is None:
            cand["status"] = "opened, could not be read"
            return None
        summary = _short(data.get("summary"))
        if data.get("covers_deceased") is not True or not summary:
            cand["status"] = "opened, no deceased-account policy"
            self.trace("    the page states no deceased-account policy")
            return None
        return make_record(
            self.host, page.url, summary, _verified_ticks(data, page.text)
        )

    def best_page(self) -> int | None:
        """The unread opened page with the most keyword hits (at least 2)."""
        options = [
            (count_keywords(page.text), cid)
            for cid, page in self.pages.items()
            if not self.by_id(cid).get("extracted")
        ]
        hits, cid = max(options, default=(0, None))
        return cid if hits >= 2 else None

    def blocked_lead(self) -> dict | None:
        """The best-scored strong candidate whose page the crawler cannot read."""
        leads = [
            c
            for c in self.candidates
            if c["score"] >= STRONG_SCORE and c["status"] in UNREADABLE
        ]
        return max(leads, key=lambda c: c["score"], default=None)

    def extract_lead(self, cand: dict) -> dict | None:
        """Judge an unreadable page by its title and search snippet.

        The summary says so, and the tick boxes stay empty: a snippet says too little for them.
        """
        text = "\n".join(part for part in (cand["label"], cand["snippet"]) if part)
        data = self._read(Page(url=cand["url"], title=cand["label"], text=text))
        summary = _short(data.get("summary"), limit=2) if data else ""
        if not data or data.get("covers_deceased") is not True or not summary:
            return None
        return make_record(self.host, cand["url"], f"{summary} {LEAD_NOTE}")


def _invalid(why: str) -> dict:
    return {"action": "invalid", "why": why}


def _decide(run: Run, step: int, last: int | None) -> dict:
    """One Apertus call -> a validated action, or {"action": "invalid", "why": reason}."""
    try:
        act = chat_json(run.messages(step, last), max_tokens=150)
    except JSONError:
        return _invalid("the reply was not valid JSON")
    kind = str(act.get("action", "")).lower()
    act["action"] = kind
    if kind == "open":
        if run.pick(act.get("id"), opened=False):
            return act
        return _invalid(f"open {act.get('id')!r}: not an untried candidate")
    if kind == "search":
        query = " ".join(str(act.get("query") or "").split())
        if run.searches >= MAX_SEARCHES:
            return _invalid("no searches left")
        if not query:
            return _invalid("empty search query")
        if query.lower() in {done.lower() for done in run.queries}:
            return _invalid("that search was already done")
        return act
    if kind == "finish":
        if act.get("id") is None:
            return act
        cand = run.pick(act.get("id"), opened=True)
        if cand is None:
            return _invalid(f"finish {act.get('id')!r}: not an opened page")
        if cand.get("extracted"):
            return _invalid("that page was already read and states no policy")
        return act
    return _invalid(f"unknown action {kind!r}")


def _crawl(run: Run) -> dict | None:
    """The record for the website, or None if no page could be fetched."""
    run.seed()
    if not run.pages and not run.search_hits:
        return None  # nothing to work with
    last: int | None = None
    invalid = 0
    step = 0
    while step < run.step_limit:
        step += 1
        act = _decide(run, step, last)
        if act["action"] == "invalid":
            invalid += 1
            run.trace(f"step {step}: invalid reply ({act['why']})")
            if invalid < 2:
                continue
            # second invalid reply: fall back to the best-scored page
            top = run.top_unopened(1)
            act = (
                {"action": "open", "id": top[0]["id"]}
                if top
                else {"action": "finish", "id": None}
            )
        run.trace(f"step {step}: {act.get('thought') or act['action']}")
        if act["action"] == "open":
            cand = run.pick(act["id"], opened=False)
            if cand and run.open(cand):
                last = cand["id"]
        elif act["action"] == "search":
            known = len(run.candidates)
            run.run_search(str(act["query"]))
            if len(run.candidates) > known:
                # a search that brings new pages does not use up a step
                run.step_limit += 1
        else:  # finish
            if act.get("id") is None:
                break
            record = run.extract(int(act["id"]))
            if record:
                return record
    cid = run.best_page()
    if cid is not None:
        record = run.extract(cid)
        if record:
            return record
    lead = run.blocked_lead()
    if lead:
        record = run.extract_lead(lead)
        if record:
            return record
    if not run.pages:
        return None
    return make_record(run.host, NOT_FOUND, NO_POLICY)  # a valid result


def lookup_legacy_policy(
    website: str,
    refresh: bool = False,
    path: str | None = None,
    trace: Callable[[str], None] | None = None,
) -> dict:
    """The record for one website, e.g. 'www.google.com'. Crawls only if it is not saved yet.

    A record has: website, legacy_policy_url, summary, tick_boxes, checked. A provider without a
    clear policy gets "not found" and "none". Found and not-found records are saved in the JSON
    file. Failures (site unreachable, Apertus unavailable) and a "not found" reached without a
    working web search are returned but not saved, so a re-run retries.
    A missing or rejected token raises llm.AuthError.
    """
    host = normalize_website(website)
    if "." not in host:
        return make_record(
            host or website.strip(),
            NOT_FOUND,
            f"'{website.strip()}' is not a valid website address.",
        )
    path = path or store.DEFAULT_PATH
    key = (host, str(path))
    saved = store.get(host, path)
    if not refresh:
        if saved:
            return saved
        memo = _unsaved.get(key)
        if memo and time.monotonic() - memo[0] < UNSAVED_TTL:
            return memo[1]
    run = Run(host, trace or (lambda message: None))
    try:
        record = _crawl(run)
    except AuthError:
        raise
    except LLMError as e:
        return make_record(
            host, NOT_FOUND, f"Apertus was unavailable ({e}); try again later."
        )
    if record is None:
        reasons = [
            c["status"].removeprefix("failed: ") for c in run.candidates if c["status"]
        ]
        return make_record(
            host,
            NOT_FOUND,
            f"{host} could not be reached" + (f" ({reasons[0]})." if reasons else "."),
        )
    if record["legacy_policy_url"] == NOT_FOUND and not run.search_hits:
        # without a working web search, "not found" proves little: do not save it, and
        # never replace an earlier result with it
        if saved:
            return saved
        _unsaved[key] = (time.monotonic(), record)
        return record
    _unsaved.pop(key, None)
    store.upsert(record, path)
    return record
