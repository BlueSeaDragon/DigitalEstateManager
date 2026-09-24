import base64
import json
from datetime import date
from types import SimpleNamespace

import pytest
from conftest import FakeGmailService, FakeLLM, gmail_message

from subscription_finder.config import Settings
from subscription_finder.extract.email_extractor import extract_emails, heuristic_extract
from subscription_finder.llm.client import LLMClient
from subscription_finder.models import EmailMessage
from subscription_finder.sources.email_base import EmailSource, ReconnectRequired
from subscription_finder.sources.gmail import GmailSource, extract_body


def _source(messages, **kw):
    return GmailSource(service=FakeGmailService(messages, **kw), today=date(2026, 1, 1))


def test_gmail_source_fetches_and_parses():
    msg = gmail_message("m1", date(2025, 3, 1), "Streamy <billing@streamy.com>", "Your receipt", "Total CHF 12.90")
    source = _source([msg])
    assert isinstance(source, EmailSource)
    [email] = source.fetch()
    assert email.sender_domain == "streamy.com"
    assert email.subject == "Your receipt"
    assert email.body == "Total CHF 12.90"
    assert source.account == "owner@example.org"
    stats = source.stats()
    assert stats["messages_scanned"] == 1 and stats["skipped"] == 0
    assert "newer_than:24m" in stats["query"] and "-in:spam" in stats["query"]


def test_gmail_body_is_trimmed_and_html_stripped():
    payload = {
        "mimeType": "text/html",
        "body": {"data": base64.urlsafe_b64encode(b"<style>x{}</style><b>Total</b> <p>CHF&nbsp;5</p>").decode()},
    }
    assert extract_body(payload) == "Total CHF 5"
    long = gmail_message("m1", date(2025, 3, 1), "a@b.com", "s", "x" * 5000)
    [email] = GmailSource(service=FakeGmailService([long]), body_chars=1500).fetch()
    assert len(email.body) == 1500


def test_gmail_revoked_token_raises_reconnect():
    error = Exception("unauthorized")
    error.resp = SimpleNamespace(status=401)
    with pytest.raises(ReconnectRequired):
        _source([], list_error=error).fetch()


def test_heuristic_extraction():
    msg = EmailMessage("m1", date(2025, 3, 1), "Streamy <billing@streamy.com>", "Your monthly receipt", "You were charged CHF 12.90")
    facts = heuristic_extract(msg)
    assert facts["is_billing_email"] is True
    assert facts["amount"] == 12.90 and facts["currency"] == "CHF"
    assert facts["billing_cycle_hint"] == "monthly"
    assert facts["merchant"] == "Streamy"

    newsletter = EmailMessage("m2", date(2025, 3, 1), "news@shop.com", "Spring sale", "New arrivals!")
    assert heuristic_extract(newsletter)["is_billing_email"] is False


@pytest.mark.parametrize("subject", [
    "Grow your skills with Coursera for $239/year",
    "For $239/year: Enjoy all that Coursera Plus offers",
    "Make this weekend count: 40% off your subscription",
])
def test_heuristic_rejects_ads_that_name_a_price(subject):
    ad = EmailMessage("m3", date(2026, 3, 24), "Coursera <c@m.learn.coursera.org>", subject, "Subscription from $239/year.")
    assert heuristic_extract(ad)["is_billing_email"] is False


def test_extraction_prompt_rules_out_advertising():
    from subscription_finder.llm.prompts import EXTRACT_SYSTEM

    assert "Advertising is NEVER a billing email" in EXTRACT_SYSTEM


def _answer(**kw):
    base = {"is_billing_email": True, "merchant": "Streamy", "amount": 12.9, "currency": "chf", "billing_cycle_hint": "monthly", "date": "2025-03-01"}
    base.update(kw)
    return json.dumps(base)


def test_llm_extraction_with_repair_retry(settings):
    fake = FakeLLM("sorry, here it is: {broken", "```json\n" + _answer() + "\n```")
    llm = LLMClient(settings, client=fake)
    msg = EmailMessage("m1", date(2025, 3, 1), "billing@streamy.com", "Receipt", "body", snippet="s" * 500)
    [ev], counts = extract_emails([msg], "gmail:owner", llm)
    assert len(fake.calls) == 2  # original + one repair
    assert ev.currency == "CHF" and ev.amount == 12.9
    assert len(ev.observed["snippet"]) == 200
    assert counts == {"billing": 1, "not_billing": 0, "llm_failures": 0}


def test_llm_failure_falls_back_to_heuristics():
    settings = Settings(api_key="k", base_url="u", cache_dir=None, llm_retries=1, max_requests_per_second=1000)
    llm = LLMClient(settings, client=FakeLLM(RuntimeError("down")))
    msg = EmailMessage("m1", date(2025, 3, 1), "billing@streamy.com", "Receipt", "charged EUR 5.00")
    [ev], counts = extract_emails([msg], "gmail:owner", llm)
    assert counts["llm_failures"] == 1
    assert ev.amount == 5.0


def test_non_billing_emails_are_dropped(settings):
    llm = LLMClient(settings, client=FakeLLM(_answer(is_billing_email=False)))
    msg = EmailMessage("m1", date(2025, 3, 1), "news@shop.com", "Sale", "…")
    evidence, counts = extract_emails([msg], "gmail:owner", llm)
    assert evidence == [] and counts["not_billing"] == 1


def test_llm_cache_avoids_repeat_calls(tmp_path):
    settings = Settings(api_key="k", base_url="u", cache_dir=tmp_path, max_requests_per_second=1000)
    msg = EmailMessage("m1", date(2025, 3, 1), "billing@streamy.com", "Receipt", "body")
    fake = FakeLLM(_answer())
    extract_emails([msg], "gmail:owner", LLMClient(settings, client=fake))
    second = LLMClient(settings, client=FakeLLM())
    [ev], _ = extract_emails([msg], "gmail:owner", second)
    assert second.usage["cache_hits"] == 1 and second.usage["requests"] == 0
    assert ev.amount == 12.9
