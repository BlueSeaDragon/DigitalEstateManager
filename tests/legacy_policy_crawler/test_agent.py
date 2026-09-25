"""Offline tests for the agent: a scripted fake model and canned web pages, no network, no token."""

import datetime
import re

import pytest

from legacy_policy_crawler import agent, store, web
from legacy_policy_crawler.llm import AuthError, JSONError, LLMError
from legacy_policy_crawler.prompts import (
    NAVIGATE_NO_SEARCH,
    NAVIGATE_PROMPT,
    TICK_KEYS,
)


def page(url, title, body, links=()):
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    html = f"<html><head><title>{title}</title></head><body><main><p>{body}</p></main>{anchors}</body></html>"
    return web.parse_page(url, html)


POLICY_URL = "https://help.acme.com/deceased-users"
PAGES = {
    "https://acme.com/": page(
        "https://acme.com/",
        "Acme",
        "Welcome to Acme.",
        [
            ("/help", "Help"),
            ("/legal", "Legal"),
            ("https://evil.com/deceased", "Deceased users"),
        ],
    ),
    POLICY_URL: page(
        POLICY_URL,
        "Deceased users - Acme Help",
        "When a member has died, the account is closed after we receive a death certificate. "
        "Heirs may request the data.",
    ),
    "https://help.acme.com/billing": page(
        "https://help.acme.com/billing", "Billing", "Invoices and payment methods."
    ),
}
HITS = [
    (POLICY_URL, "Deceased users - Acme Help", "what happens after death"),
    (
        "https://evil.com/deceased-users",
        "Deceased users",
        "another brand: must never be opened",
    ),
    ("https://help.acme.com/billing", "Billing", ""),
]


class World:
    """Fake web, search and model. `nav` lists the model's replies to the navigation prompts:
    a dict, an exception to raise, or a function of the prompt messages."""

    def __init__(self):
        (
            self.fetched,
            self.nav,
            self.nav_calls,
            self.extract_calls,
            self.search_calls,
        ) = ([], [], 0, 0, 0)
        self.hits = HITS
        self.extract_messages = None
        self.extraction = {
            "covers_deceased": True,
            "summary": "One. Two. Three. Four.",
            "tick_boxes": {
                "owner_can_appoint_successor": "yes",
                "heirs_can_request_access": True,
                "subscription_or_balance_addressed": "maybe",
                "proof_required": True,
            },
            "evidence": {
                "owner_can_appoint_successor": "Members may name a successor",  # not on the page
                "heirs_can_request_access": "Heirs may request the data",
                "proof_required": "after we receive a death certificate",
            },
        }

    def fetch(self, url):
        self.fetched.append(url)
        if url in PAGES:
            return PAGES[url]
        raise web.FetchError("HTTP 404")

    def search(self, query, max_results=8):
        self.search_calls += 1
        return list(self.hits)

    def chat_json(self, messages, max_tokens=300):
        if messages[0]["content"] in (NAVIGATE_PROMPT, NAVIGATE_NO_SEARCH):
            self.nav_calls += 1
            step = self.nav.pop(0)
            result = step(messages) if callable(step) else step
        else:
            self.extract_calls += 1
            self.extract_messages = messages
            result = self.extraction
        if isinstance(result, Exception):
            raise result
        return dict(result)


def offered(messages, needle):
    """Number of the not-yet-opened candidate whose URL contains `needle`, read from the prompt."""
    section = messages[1]["content"].split("Candidate pages not opened yet")[1]
    for line in section.splitlines():
        found = re.match(r"\[(\d+)\] (\S+)", line)
        if found and needle in found.group(2):
            return int(found.group(1))
    raise AssertionError(f"{needle!r} was not offered:\n{section}")


def last_opened(messages):
    return int(
        re.search(r"Last opened page \[(\d+)\]", messages[1]["content"]).group(1)
    )


def open_page(needle):
    return lambda messages: {
        "thought": f"open {needle}",
        "action": "open",
        "id": offered(messages, needle),
    }


def finish_last(messages):
    return {
        "thought": "this page states the policy",
        "action": "finish",
        "id": last_opened(messages),
    }


GIVE_UP = {"thought": "nothing here", "action": "finish", "id": None}


@pytest.fixture
def world(monkeypatch, tmp_path):
    fake = World()
    fake.path = tmp_path / "policies.json"
    monkeypatch.setattr(agent, "fetch_page", fake.fetch)
    monkeypatch.setattr(agent, "search", fake.search)
    monkeypatch.setattr(agent, "chat_json", fake.chat_json)
    # no network in tests
    monkeypatch.setattr(agent, "robots_allowed", lambda url: True)
    return fake


def test_finds_the_policy_page_and_saves_the_record(world):
    world.nav = [open_page("deceased-users"), finish_last]
    record = agent.lookup_legacy_policy(
        "https://www.Acme.com/somewhere", path=world.path
    )
    assert record == {
        "website": "acme.com",
        "legacy_policy_url": POLICY_URL,
        "summary": "One. Two. Three.",  # trimmed to three sentences
        "tick_boxes": {
            "owner_can_appoint_successor": None,  # "yes", but its quote is not on the page
            "heirs_can_request_access": True,  # proved by a quote from the page
            "subscription_or_balance_addressed": None,  # "maybe" is not an answer
            "proof_required": True,
        },
        "checked": datetime.date.today().isoformat(),
    }
    assert list(record) == [
        "website",
        "legacy_policy_url",
        "summary",
        "tick_boxes",
        "checked",
    ]
    assert list(record["tick_boxes"]) == list(TICK_KEYS)
    assert store.get("acme.com", world.path) == record
    assert (world.nav_calls, world.extract_calls) == (2, 1)
    # other brands are never opened, and the page text reached the model
    assert not any("evil.com" in url for url in world.fetched)
    assert "death certificate" in world.extract_messages[1]["content"]


def test_saved_websites_are_not_crawled_again(world):
    world.nav = [open_page("deceased-users"), finish_last]
    first = agent.lookup_legacy_policy("acme.com", path=world.path)
    counters = (
        len(world.fetched),
        world.nav_calls,
        world.extract_calls,
        world.search_calls,
    )
    assert agent.lookup_legacy_policy("www.acme.com/help", path=world.path) == first
    assert (
        len(world.fetched),
        world.nav_calls,
        world.extract_calls,
        world.search_calls,
    ) == counters
    world.nav = [open_page("deceased-users"), finish_last]
    agent.lookup_legacy_policy("acme.com", path=world.path, refresh=True)
    assert world.nav_calls == counters[1] + 2
    assert len(store.load(world.path)) == 1  # replaced, not duplicated


def test_model_cannot_invent_ids_or_links(world):
    world.nav = [
        {"action": "open", "id": 99},
        {"action": "open", "id": "abc"},
        finish_last,
    ]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    # after two invalid answers the agent opens the best-scored candidate itself: the policy page
    assert record["legacy_policy_url"] == POLICY_URL
    assert world.nav_calls == 3
    assert world.fetched == ["https://acme.com/", POLICY_URL]


def test_unparseable_model_replies_count_as_invalid(world):
    world.nav = [JSONError("no json"), JSONError("no json"), finish_last]
    assert (
        agent.lookup_legacy_policy("acme.com", path=world.path)["legacy_policy_url"]
        == POLICY_URL
    )


def test_no_clear_policy_is_a_valid_saved_result(world):
    world.extraction = {"covers_deceased": False, "summary": "", "tick_boxes": {}}
    world.nav = [open_page("billing"), finish_last, GIVE_UP]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert record["legacy_policy_url"] == "not found"
    assert record["summary"] == "none"
    assert all(value is None for value in record["tick_boxes"].values())
    assert store.get("acme.com", world.path) == record  # saved: it is not crawled again


def test_not_found_without_a_working_search_is_not_saved(world):
    world.hits = []  # web search returned nothing at all
    world.nav = [GIVE_UP]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert (record["legacy_policy_url"], record["summary"]) == ("not found", "none")
    assert not world.path.exists()  # inconclusive: not saved
    calls = world.nav_calls
    # reused for a few minutes
    assert agent.lookup_legacy_policy("acme.com", path=world.path) == record
    assert world.nav_calls == calls
    world.nav = [GIVE_UP]
    agent.lookup_legacy_policy("acme.com", path=world.path, refresh=True)
    assert world.nav_calls == calls + 1  # refresh crawls again


def test_a_crawl_without_search_never_replaces_an_earlier_result(world):
    world.nav = [open_page("deceased-users"), finish_last]
    first = agent.lookup_legacy_policy("acme.com", path=world.path)
    world.hits = []
    world.nav = [GIVE_UP]
    assert (
        agent.lookup_legacy_policy("acme.com", path=world.path, refresh=True) == first
    )
    assert store.get("acme.com", world.path) == first


def test_unreadable_extraction_ends_as_not_found(world):
    world.extraction = JSONError("no json")
    world.nav = [open_page("deceased-users"), finish_last, GIVE_UP]
    assert (
        agent.lookup_legacy_policy("acme.com", path=world.path)["legacy_policy_url"]
        == "not found"
    )


def test_best_page_is_read_even_if_the_model_gives_up(world):
    world.nav = [open_page("deceased-users"), GIVE_UP]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    # the page has several deceased-account keywords
    assert record["legacy_policy_url"] == POLICY_URL
    assert world.extract_calls == 1


def test_unreachable_site_is_returned_but_not_saved(world, monkeypatch):
    def unreachable(url):
        raise web.FetchError("ConnectError")

    monkeypatch.setattr(agent, "fetch_page", unreachable)
    monkeypatch.setattr(agent, "search", lambda query, max_results=8: [])
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert record["legacy_policy_url"] == "not found"
    # the reason is reported
    assert record["summary"] == "acme.com could not be reached (ConnectError)."
    assert not world.path.exists()
    assert world.nav_calls == 0


def test_second_seed_search_is_skipped_when_the_first_found_strong_candidates(world):
    world.hits = HITS + [
        (
            "https://help.acme.com/legacy-contact",
            "Legacy contact for deceased members",
            "death",
        )
    ]
    world.nav = [open_page("deceased-users"), finish_last]
    agent.lookup_legacy_policy("acme.com", path=world.path)
    # the first search found two strong candidates, so the second is not needed
    assert world.search_calls == 1


def test_crawl_continues_when_the_homepage_blocks_bots_but_search_found_pages(
    world, monkeypatch
):
    def fetch(url):
        world.fetched.append(url)
        if url == POLICY_URL:
            return PAGES[url]
        raise web.FetchError("HTTP 403")  # the main site blocks bots

    monkeypatch.setattr(agent, "fetch_page", fetch)
    world.nav = [open_page("deceased-users"), finish_last]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert record["legacy_policy_url"] == POLICY_URL
    # other pages of a site that blocks bots are skipped
    assert "https://acme.com/help" not in world.fetched


def test_sites_that_answer_403_are_not_tried_again(world, monkeypatch):
    world.hits = [
        ("https://wiki.acme.com/a", "Deceased user article", "died"),
        ("https://wiki.acme.com/b", "Another article about death", ""),
        (POLICY_URL, "Deceased users - Acme Help", "what happens after death"),
    ]

    def fetch(url):
        world.fetched.append(url)
        if "wiki.acme.com" in url:
            raise web.FetchError("HTTP 403")
        return PAGES[url] if url in PAGES else PAGES["https://acme.com/"]

    def open_policy_without_the_blocked_site(messages):
        section = messages[1]["content"].split("Candidate pages not opened yet")[1]
        assert "wiki.acme.com/b" not in section  # not offered any more
        return open_page("deceased-users")(messages)

    monkeypatch.setattr(agent, "fetch_page", fetch)
    world.nav = [
        open_page("wiki.acme.com/a"),
        open_policy_without_the_blocked_site,
        finish_last,
    ]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert record["legacy_policy_url"] == POLICY_URL
    assert "https://wiki.acme.com/b" not in world.fetched


@pytest.fixture
def blocked_policy_page(world, monkeypatch):
    """The policy page itself answers 403; everything else behaves normally."""

    def fetch(url):
        world.fetched.append(url)
        if url == POLICY_URL:
            raise web.FetchError("HTTP 403")
        if url in PAGES:
            return PAGES[url]
        raise web.FetchError("HTTP 404")

    monkeypatch.setattr(agent, "fetch_page", fetch)
    world.nav = [open_page("deceased-users"), GIVE_UP]
    return world


def test_a_promising_page_that_blocks_bots_is_used_through_its_search_result(
    blocked_policy_page,
):
    world = blocked_policy_page
    world.extraction = {
        "covers_deceased": True,
        "summary": "It explains how to claim the account. It lists the documents. A third sentence.",
        "tick_boxes": {"proof_required": True},
    }
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert record["legacy_policy_url"] == POLICY_URL
    assert (
        record["summary"]
        == "It explains how to claim the account. It lists the documents. "
        + agent.LEAD_NOTE
    )
    # a snippet says too little for tick boxes
    assert all(value is None for value in record["tick_boxes"].values())
    # only the title and the search snippet reached the model
    assert "what happens after death" in world.extract_messages[1]["content"]
    assert "death certificate" not in world.extract_messages[1]["content"]
    assert store.get("acme.com", world.path) == record


def test_a_blocked_page_whose_search_result_is_no_policy_is_not_used(
    blocked_policy_page,
):
    world = blocked_policy_page
    world.extraction = {"covers_deceased": False, "summary": "", "tick_boxes": {}}
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert (record["legacy_policy_url"], record["summary"]) == ("not found", "none")


def test_a_repeated_search_is_refused_and_the_model_is_told_what_it_searched(world):
    seen = []

    def repeat_it(messages):
        seen.append(messages[1]["content"])
        # same words as the first search, with other spacing and case
        return {"action": "search", "query": "Death  account"}

    world.nav = [
        {"action": "search", "query": "death account"},
        repeat_it,
        GIVE_UP,
    ]
    agent.lookup_legacy_policy("acme.com", path=world.path)
    assert world.search_calls == 2 + 1  # the repeated search was not executed
    assert "Searches already done:" in seen[0] and "death account" in seen[0]
    assert "Searches left: 1." in seen[0]


def test_the_model_is_told_when_no_searches_are_left():
    run = agent.Run("acme.com", lambda message: None)
    system, user = (m["content"] for m in run.messages(1, None))
    assert system == NAVIGATE_PROMPT and '"action": "search"' in system
    assert "Searches left: 2." in user
    run.searches = agent.MAX_SEARCHES
    system, user = (m["content"] for m in run.messages(1, None))
    assert system == NAVIGATE_NO_SEARCH and '"action": "search"' not in system
    assert "No searches left" in user


def test_pages_that_robots_txt_disallows_are_leads_and_never_fetched(
    world, monkeypatch
):
    monkeypatch.setattr(agent, "robots_allowed", lambda url: url != POLICY_URL)
    world.nav = [GIVE_UP]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert record["legacy_policy_url"] == POLICY_URL
    assert record["summary"].endswith(agent.LEAD_NOTE)
    assert POLICY_URL not in world.fetched  # robots.txt is respected


def test_unreadable_candidates_are_counted_not_listed(world, monkeypatch):
    monkeypatch.setattr(agent, "robots_allowed", lambda url: "private" not in url)
    run = agent.Run("acme.com", lambda message: None)
    run.add("https://help.acme.com/private/a")
    run.add("https://help.acme.com/public/b")
    text = run.messages(1, None)[1]["content"]
    assert "1 more candidates cannot be read" in text
    assert "private/a" not in text and "public/b" in text


def test_pdf_and_word_links_are_not_candidates(world):
    run = agent.Run("acme.com", lambda message: None)
    for name in ("form.pdf", "form.DOCX", "sheet.xlsx", "page.html", "page"):
        run.add(f"https://help.acme.com/{name}")
    assert [c["url"] for c in run.candidates] == [
        "https://help.acme.com/page.html",
        "https://help.acme.com/page",
    ]


def test_finishing_on_a_page_that_was_already_rejected_is_invalid(world):
    lines = []
    world.extraction = {"covers_deceased": False, "summary": "", "tick_boxes": {}}
    world.nav = [open_page("billing"), finish_last, finish_last, GIVE_UP]
    agent.lookup_legacy_policy("acme.com", path=world.path, trace=lines.append)
    assert world.extract_calls == 1  # the second "finish" did not trigger another call
    assert any("already read" in line for line in lines)


def test_user_posts_never_become_candidates_or_leads(world):
    world.hits = [
        ("https://community.acme.com/t5/a", "Deceased member died death", "deceased"),
        (
            "https://sellercentral.acme.com/seller-forums/discussions/t/1",
            "Bereavement",
            "",
        ),
        ("https://support.acme.com/accounts/thread/123", "Deceased user thread", ""),
        ("https://learn.acme.com/en-us/answers/questions/55", "Deceased account", ""),
    ]
    world.nav = [GIVE_UP]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    # only posts by users were found
    assert record["legacy_policy_url"] == "not found"
    assert world.extract_calls == 0
    run = agent.Run("acme.com", lambda message: None)
    for url, title, snippet in world.hits:
        run.add(url, title, hint=snippet)
    assert run.candidates == []


def test_a_search_that_finds_new_pages_does_not_use_up_a_step(world, monkeypatch):
    counter = iter(range(1000))

    def search(query, max_results=8):
        world.search_calls += 1
        return [
            (f"https://help.acme.com/page-{next(counter)}", "Help", "")
            for _ in range(5)
        ]

    monkeypatch.setattr(agent, "search", search)
    world.nav = [
        {"action": "search", "query": "a"},
        {"action": "search", "query": "b"},
    ] + [open_page("page-")] * 30
    agent.lookup_legacy_policy("acme.com", path=world.path)
    assert world.nav_calls == agent.MAX_STEPS + agent.MAX_SEARCHES


def test_missing_token_stops_the_run(world):
    world.nav = [AuthError("SWISSCOM_API_KEY is empty")]
    with pytest.raises(AuthError):
        agent.lookup_legacy_policy("acme.com", path=world.path)
    assert not world.path.exists()


def test_temporary_model_outage_is_returned_but_not_saved(world):
    world.nav = [LLMError("Apertus unavailable: HTTP 503")]
    record = agent.lookup_legacy_policy("acme.com", path=world.path)
    assert "Apertus was unavailable" in record["summary"]
    assert record["legacy_policy_url"] == "not found"
    assert not world.path.exists()


def test_invalid_website_addresses(world):
    for text in ("", "not a site", "localhost"):
        assert (
            "not a valid website address"
            in agent.lookup_legacy_policy(text, path=world.path)["summary"]
        )
    assert not world.path.exists()


def test_loop_is_bounded_by_the_step_search_and_extraction_limits(world):
    world.nav = [{"action": "search", "query": f"q{i}"} for i in range(20)]
    agent.lookup_legacy_policy("acme.com", path=world.path)
    assert world.nav_calls == agent.MAX_STEPS
    # two seed searches plus what the model may ask for
    assert world.search_calls == 2 + agent.MAX_SEARCHES
    assert world.extract_calls <= agent.MAX_EXTRACTIONS
    assert len(world.fetched) <= agent.MAX_PAGES


def test_page_limit(world, monkeypatch):
    monkeypatch.setattr(agent, "MAX_PAGES", 2)
    world.nav = [open_page("deceased-users"), open_page("billing"), GIVE_UP]
    agent.lookup_legacy_policy("acme.com", path=world.path)
    # the homepage and one page, then the limit
    assert world.fetched == ["https://acme.com/", POLICY_URL]


def test_prompt_lists_the_best_candidates_first_and_the_last_page(world):
    run = agent.Run("acme.com", lambda message: None)
    for i in range(20):
        run.add(f"https://help.acme.com/page{i}", f"label {i}", bonus=float(i))
    text = run.messages(1, None)[1]["content"]
    listed = re.findall(
        r"^\[(\d+)\] https", text.split("not opened yet")[1], flags=re.MULTILINE
    )
    assert len(listed) == agent.SHOWN
    assert listed[0] == "20"  # the highest score comes first

    run.pages[1] = PAGES[POLICY_URL]
    run.by_id(1)["status"] = "opened"
    text = run.messages(2, 1)[1]["content"]
    assert (
        "Last opened page [1]" in text
        and "<page>" in text
        and "death certificate" in text
    )
    assert "[1] https://help.acme.com/page0 - opened" in text


def test_trace_reports_the_steps(world):
    lines = []
    world.nav = [open_page("deceased-users"), finish_last]
    agent.lookup_legacy_policy("acme.com", path=world.path, trace=lines.append)
    text = "\n".join(lines)
    assert "search:" in text and "open [" in text and "extract from https://" in text


def test_tick_boxes_need_a_quote_that_is_really_on_the_page():
    text = (
        "When a member has died, the account is closed after we receive a death certificate.\n"
        "Heirs may request the data.\nIm Todesfall können Erben den Vertrag übernehmen."
    )
    data = {
        "tick_boxes": {
            "owner_can_appoint_successor": True,  # the quote is invented
            "heirs_can_request_access": True,  # a verbatim quote
            "subscription_or_balance_addressed": False,  # no quote at all
            "proof_required": True,  # case and punctuation differ: still the same words
        },
        "evidence": {
            "owner_can_appoint_successor": "Members can name a successor in their settings",
            "heirs_can_request_access": "Heirs may request the data",
            "proof_required": "WE RECEIVE a death certificate!",
        },
    }
    assert agent._verified_ticks(data, text) == {
        "owner_can_appoint_successor": None,
        "heirs_can_request_access": True,
        "subscription_or_balance_addressed": None,
        "proof_required": True,
    }
    german = {
        "tick_boxes": {"heirs_can_request_access": True},
        "evidence": {"heirs_can_request_access": "können Erben den Vertrag übernehmen"},
    }
    assert agent._verified_ticks(german, text)["heirs_can_request_access"] is True
    # lines skipped between parts of a quote (ellipsis or colon) are fine; an invented part is not
    parts = {
        "tick_boxes": {"heirs_can_request_access": True, "proof_required": True},
        "evidence": {
            "heirs_can_request_access": "When a member has died ... Heirs may request the data",
            "proof_required": "the account is closed: after we receive a death certificate",
        },
    }
    assert agent._verified_ticks(parts, text)["heirs_can_request_access"] is True
    assert agent._verified_ticks(parts, text)["proof_required"] is True
    parts["evidence"][
        "proof_required"
    ] = "the account is closed: after we receive a court order"
    assert agent._verified_ticks(parts, text)["proof_required"] is None
    none = dict.fromkeys(TICK_KEYS)
    assert agent._verified_ticks({}, text) == none
    assert agent._verified_ticks({"tick_boxes": "oops", "evidence": []}, text) == none
    too_short = {
        "tick_boxes": {"proof_required": True},
        "evidence": {"proof_required": "the"},
    }
    assert agent._verified_ticks(too_short, text) == none  # a tiny quote proves nothing


def test_tick_box_and_summary_cleanup():
    values = [True, False, "yes", "No", "TRUE", "maybe", None, 1, ""]
    assert [agent._tri(value) for value in values] == [
        True,
        False,
        True,
        False,
        True,
        None,
        None,
        None,
        None,
    ]
    assert agent._short("A. B! C? D.") == "A. B! C?"
    assert agent._short("A. B! C? D.", limit=2) == "A. B!"
    assert agent._short(None) == ""
    assert agent._short("  spaced   out \n text. ") == "spaced out text."
