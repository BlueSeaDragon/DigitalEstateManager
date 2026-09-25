"""Detector, interpretation, confidence and output schema tests (all offline)."""

import io
import json
from datetime import date, timedelta

import pytest
from tests.subscription_finder.conftest import FakeGmailService, FakeLLM, gmail_message, jsonl_rows, row, series, tx

from subscription_finder import LLMConfigError, detect_subscriptions
from subscription_finder.config import Settings
from subscription_finder.confidence import assess
from subscription_finder.detect.paid_subscription import PaidSubscriptionDetector
from subscription_finder.llm.client import LLMClient
from subscription_finder.llm.interpret import interpret
from subscription_finder.sources.gmail import GmailSource

REF = date(2026, 1, 1)
START = date(2025, 3, 3)


def monthly_rows(amount=12.9, count=10, start=START, description="video access", mcc="5815", **kw):
    return [
        row(ts=f"{(start + timedelta(days=30 * i)).isoformat()}T09:00:00Z", amount=amount, description=description, mcc=mcc, **kw)
        for i in range(count)
    ]


def detect(evidence, settings):
    return PaidSubscriptionDetector().detect(evidence, REF, settings)


# -- detector ------------------------------------------------------------------

def test_detector_infers_type_status_and_dates(settings):
    [c] = detect(series(date(2025, 4, 1), 9, 30, 37.5, description="gym membership", mcc="7997"), settings)
    assert c.service_type == "gym"
    assert c.timeline["status"] == "active"
    assert c.timeline["next_expected_date"] == date(2025, 4, 1) + timedelta(days=270)
    assert c.name is None and c.url is None  # transaction-only: no names


def test_old_series_is_possibly_cancelled(settings):
    [c] = detect(series(date(2024, 1, 1), 6, 30, 10.0), settings)
    assert c.timeline["status"] == "possibly_cancelled"


def test_full_refund_of_last_charge_marks_possibly_cancelled(settings):
    charges = series(date(2025, 6, 1), 7, 30, 20.0)
    refund = tx(charges[-1].date + timedelta(days=2), 20.0, kind="refund", direction="in")
    [c] = detect(charges + [refund], settings)
    assert c.refunds == [refund]
    assert c.timeline["status"] == "possibly_cancelled"


def test_future_evidence_is_ignored(settings):
    charges = series(date(2025, 6, 1), 10, 30, 20.0)
    [c] = detect(charges, settings)
    assert all(e.date <= REF for e in c.charges)


def test_weak_noise_series_is_dropped(settings):
    noise = [tx(date(2025, 1, 5) + timedelta(days=91 * i), 60 + 2 * i, description="grocery store", mcc="5411") for i in range(3)]
    assert detect(noise, settings) == []


def test_mixed_currencies_are_never_combined(settings):
    points = series(START, 3, 60, 10.0, currency="CHF") + series(START + timedelta(days=30), 3, 60, 10.0, currency="EUR")
    for c in detect(points, settings):
        assert len({e.currency for e in c.charges}) == 1


# -- confidence ----------------------------------------------------------------

def test_confidence_rules(settings):
    [regular] = detect(series(START, 6, 30, 9.9, mcc="5734"), settings)
    level, reasons = assess(regular, settings)
    assert level == "high" and any("MCC 5734" in r for r in reasons)

    [plain] = detect(series(START, 3, 30, 9.9, mcc="5999", description="subscription charge"), settings)
    assert assess(plain, settings)[0] == "medium"

    regular.llm_is_subscription = False
    assert assess(regular, settings)[0] == "low"

    plain.llm_failed = True
    level, reasons = assess(plain, settings)
    assert level == "low" and "LLM interpretation unavailable" in reasons


# -- LLM interpretation ----------------------------------------------------------

def _interpretation(**overrides):
    def answer(messages):
        payload = json.loads(messages[-1]["content"].split("Candidates:\n", 1)[1])
        items = []
        for c in payload:
            item = {
                "id": c["id"], "is_subscription": True, "service_type": "streaming", "name": "Streamy",
                "url": "https://streamy.com", "cancel_url": "https://evil.example/cancel",
                "explanation": "A streaming service billed monthly.", "llm_reasons": ["video wording"],
            }
            item.update(overrides)
            items.append(item)
        return json.dumps({"candidates": items})

    return answer


def test_guardrail_nulls_names_without_email_evidence(settings):
    candidates = detect(series(START, 6, 30, 12.9), settings)
    assert interpret(candidates, LLMClient(settings, client=FakeLLM(_interpretation())))
    [c] = candidates
    assert (c.name, c.url, c.cancel_url) == (None, None, None)
    assert c.service_type == "streaming"
    assert c.explanation == "A streaming service billed monthly."


def test_invalid_interpretation_falls_back_to_rules(settings):
    fake = FakeLLM("not json", '{"candidates": []}')
    candidates = detect(series(START, 6, 30, 12.9), settings)
    assert interpret(candidates, LLMClient(settings, client=fake)) is False
    assert candidates[0].llm_failed and len(fake.calls) == 2


def test_missing_api_key_is_a_clear_error():
    with pytest.raises(LLMConfigError, match="SWISSCOM_API_KEY"):
        detect_subscriptions(transactions=io.StringIO(""), use_llm=True, settings=Settings(api_key=None))


# -- end to end ----------------------------------------------------------------

def _gmail_with_receipts():
    messages = [
        gmail_message(f"m{i}", START + timedelta(days=30 * i + 1), "Streamy <billing@mail.streamy.com>",
                      "Your Streamy receipt", "Thanks! You were charged CHF 12.90 for your monthly plan.")
        for i in range(10)
    ]
    return GmailSource(service=FakeGmailService(messages), today=REF)


def _validate_schema(result):
    assert set(result) == {"run", "evidence", "subscriptions"}
    assert {"generated_at", "tool_version", "model", "reference_date", "sources_scanned", "warnings"} <= set(result["run"])
    ids = [e["evidence_id"] for e in result["evidence"]]
    assert len(ids) == len(set(ids))
    for s in result["subscriptions"]:
        assert set(s) >= {"subscription_id", "evidence_ids", "observed", "inferred", "explanation", "confidence", "confidence_reasons"}
        assert set(s["evidence_ids"]) <= set(ids)  # referential integrity
        assert s["confidence"] in {"low", "medium", "high"}
        assert s["inferred"]["status"] in {"active", "possibly_cancelled"}
    for e in result["evidence"]:
        if e["type"] == "email":
            assert len(e["observed"]["snippet"]) <= 200
    json.dumps(result)  # serialisable


def test_end_to_end_merges_email_and_transactions(settings):
    text = jsonl_rows(monthly_rows() + [row(ts="2025-05-05T10:00:00Z", amount=80, description="grocery store", mcc="5411")])
    result = detect_subscriptions(
        email_sources=[_gmail_with_receipts()], transactions=io.StringIO(text), use_llm=False, reference_date=REF, settings=settings
    )
    _validate_schema(result)
    [sub] = result["subscriptions"]
    assert sub["confidence"] == "high"
    assert "confirmed by both bank transactions and billing emails" in sub["confidence_reasons"]
    assert sub["inferred"]["name"] == "Streamy"
    assert sub["inferred"]["url"] == "https://streamy.com"
    assert sub["inferred"]["account_email"] == "owner@example.org"
    assert len(sub["evidence_ids"]) == 20
    assert result["run"]["sources_scanned"]["email"][0]["messages_scanned"] == 10
    assert result["run"]["model"] is None


def test_end_to_end_with_llm(settings):
    answers = [json.dumps({"is_billing_email": True, "merchant": "Streamy", "amount": 12.9, "currency": "CHF",
                           "billing_cycle_hint": "monthly", "date": None})] * 10
    fake = FakeLLM(*answers, _interpretation())
    result = detect_subscriptions(
        email_sources=[_gmail_with_receipts()], transactions=io.StringIO(jsonl_rows(monthly_rows())),
        reference_date=REF, settings=settings, llm_client=fake,
    )
    _validate_schema(result)
    [sub] = result["subscriptions"]
    assert sub["inferred"]["url"] == "https://streamy.com"
    assert sub["inferred"]["cancel_url"] is None  # wrong domain -> guardrail
    assert result["run"]["llm_usage"]["requests"] == 11


def test_email_only_bills_with_varying_amounts(settings):
    amounts = [21.0, 11.0, 12.0, 14.8, 20.3, 12.0]
    days = [date(2025, 12, 4), date(2026, 2, 4), date(2026, 5, 1), date(2026, 6, 3), date(2026, 8, 5), date(2026, 9, 3)]
    messages = [
        gmail_message(f"b{i}", d, "Phoneco <billing@phoneco.ch>", "Ihre Rechnung", f"Rechnung: CHF {a:.2f}, monatlich")
        for i, (d, a) in enumerate(zip(days, amounts))
    ]
    source = GmailSource(service=FakeGmailService(messages), today=date(2026, 9, 24))
    result = detect_subscriptions(email_sources=[source], use_llm=False, reference_date=date(2026, 9, 24), settings=settings)
    [sub] = result["subscriptions"]
    assert sub["inferred"]["name"] == "Phoneco" and sub["inferred"]["url"] == "https://phoneco.ch"
    assert sub["inferred"]["billing_cycle"] == "monthly"
    assert sub["inferred"]["status"] == "active"
    assert sub["inferred"]["currency"] == "CHF"
    assert "varies" in sub["explanation"]


def test_ads_are_not_subscriptions(settings):
    messages = [
        gmail_message(f"a{i}", date(2026, 3, 24) + timedelta(days=8 * i), "Coursera <c@m.learn.coursera.org>",
                      "Grow your skills with Coursera for $239/year", "Unlock Coursera Plus: subscription for $239/year.")
        for i in range(4)
    ]
    source = GmailSource(service=FakeGmailService(messages), today=REF)
    result = detect_subscriptions(email_sources=[source], use_llm=False, reference_date=date(2026, 6, 1), settings=settings)
    assert result["subscriptions"] == []


def test_gmail_failure_degrades_to_transactions(settings):
    broken = GmailSource(service=FakeGmailService([], list_error=RuntimeError("503")), today=REF)
    result = detect_subscriptions(
        email_sources=[broken], transactions=io.StringIO(jsonl_rows(monthly_rows())), use_llm=False, reference_date=REF, settings=settings
    )
    assert len(result["subscriptions"]) == 1
    assert any("gmail could not be read" in w for w in result["run"]["warnings"])


def test_empty_input_gives_valid_empty_output(settings):
    result = detect_subscriptions(transactions=io.StringIO(""), use_llm=False, reference_date=REF, settings=settings)
    _validate_schema(result)
    assert result["subscriptions"] == [] and result["run"]["warnings"]


def test_cli_no_llm(tmp_path, capsys):
    from subscription_finder.cli import main

    data = tmp_path / "tx.jsonl"
    data.write_text(jsonl_rows(monthly_rows() + monthly_rows(client="C2", amount=50)), encoding="utf-8")
    out = tmp_path / "out" / "subs.json"
    code = main(["--transactions", str(data), "--sample-client", "C1", "--no-llm", "--reference-date", "2026-01-01", "--out", str(out)])
    assert code == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert [s["inferred"]["amount"] for s in result["subscriptions"]] == [12.9]
    assert "1 subscription(s) found" in capsys.readouterr().out


def test_cancel_url_must_be_a_link_from_the_emails(settings):
    body = ("Your bill: CHF 12.90 monthly. Manage your plan: https://www.streamy.com/account/subscription?token=SECRET "
            "Help: https://streamy.com/help")
    messages = [
        gmail_message(f"m{i}", START + timedelta(days=30 * i), "Streamy <billing@streamy.com>", "Your invoice", body)
        for i in range(4)
    ]

    def run(cancel_url):
        source = GmailSource(service=FakeGmailService(messages), today=REF)
        answers = [json.dumps({"is_billing_email": True, "merchant": "Streamy", "amount": 12.9, "currency": "CHF",
                               "billing_cycle_hint": "monthly", "date": None})] * 4
        fake = FakeLLM(*answers, _interpretation(cancel_url=cancel_url))
        result = detect_subscriptions(email_sources=[source], reference_date=REF, settings=settings, llm_client=fake)
        return result["subscriptions"][0]["inferred"]["cancel_url"], fake

    # the link from the email (query string with its token stripped) is accepted
    url, fake = run("https://streamy.com/account/subscription")
    assert url == "https://www.streamy.com/account/subscription"
    summary = fake.calls[-1][-1]["content"]
    assert "SECRET" not in summary and "links_found_in_emails" in summary
    # a plausible but invented path on the right domain is rejected
    assert run("https://www.streamy.com/cancel-service")[0] is None
