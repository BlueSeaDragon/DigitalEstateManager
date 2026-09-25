"""Digital-footprint detection: signals, catalog, merging, confidence, LLM fallback, output (offline)."""

import io
import json
from datetime import date, timedelta

import pytest
from conftest import FakeGmailService, FakeLLM, gmail_message, jsonl_rows, row

from subscription_finder import FOOTPRINT_TERMS, detect_subscriptions, discover_footprint
from subscription_finder.footprint.catalog import ACCOUNT_TYPES, is_personal_sender, lookup_domain, lookup_text
from subscription_finder.footprint.signals import classify_email, email_signals
from subscription_finder.models import EmailMessage
from subscription_finder.sources.gmail import GmailSource

REF = date(2026, 6, 1)
DAY = date(2026, 3, 2)


def email(sender, subject, body="", day=DAY, mid="m1"):
    return EmailMessage(mid, day, sender, subject, body)


def run(messages, settings, transactions=None, llm_client=None, account="owner@example.org"):
    raw = [gmail_message(f"m{i}", d, s, subj, body) for i, (d, s, subj, body) in enumerate(messages)]
    source = GmailSource(service=FakeGmailService(raw, account=account), today=REF, terms=FOOTPRINT_TERMS)
    return discover_footprint(
        email_sources=[source],
        transactions=io.StringIO(jsonl_rows(transactions)) if transactions else None,
        use_llm=llm_client is not None,
        llm_client=llm_client,
        reference_date=REF,
        settings=settings,
    )


def by_key(result):
    return {a["service"]["key"]: a for a in result["accounts"]}


# -- email classification --------------------------------------------------------

@pytest.mark.parametrize("subject, kind, strength", [
    ("New sign-in to your account", "security", "strong"),
    ("Reset your password", "security", "strong"),
    ("Welcome to Acme!", "account_created", "strong"),
    ("Please verify your email", "account_created", "strong"),
    ("Your monthly statement is ready", "statement", "strong"),
    ("Ihr Kontoauszug März", "statement", "strong"),
    ("Your invoice #1234", "invoice", "strong"),
    ("Your policy documents", "contract", "strong"),
    ("Your order has shipped", "order", "medium"),
    ("We're updating our terms", "account_notice", "medium"),
    ("40% off this weekend only", "marketing", "weak"),
    ("Hello there", "other", "weak"),
])
def test_email_kinds_and_strength(subject, kind, strength):
    got_kind, got_strength, rule = classify_email(email("x@acme.com", subject))
    assert (got_kind, got_strength) == (kind, strength)
    assert rule  # explainable


def test_subject_decides_before_body_footer():
    # a newsletter whose footer mentions passwords stays a newsletter
    msg = email("news@acme.com", "Our spring newsletter", "Forgot your password? Reset your password here.")
    assert classify_email(msg)[0] == "marketing"


def test_one_time_codes_are_redacted():
    msg = EmailMessage("m1", DAY, "Acme <security@acme.com>", "Your verification code 482913",
                       "Use code 482913 to sign in.", snippet="Use code 482913 to sign in.")
    [signal] = email_signals([msg], "gmail:owner")
    assert "482913" not in json.dumps(signal.evidence.to_dict())
    assert "[redacted]" in signal.evidence.observed["snippet"]


# -- catalog -----------------------------------------------------------------------

def test_catalog_matches_longest_domain_suffix():
    assert lookup_domain("accounts.google.com").key == "google"
    assert lookup_domain("mail.instagram.com").key == "instagram"
    assert lookup_domain("aws.amazon.com").key == "aws"
    assert lookup_domain("amazon.de").key == "amazon"
    assert lookup_domain("unknown-shop.ch") is None


def test_transaction_keywords_are_word_bounded():
    assert lookup_text("COINBASE UK LTD").key == "coinbase"
    assert lookup_text("PAYPAL *SHOPNAME").key == "paypal"
    assert lookup_text("coinbasement store") is None


def test_personal_freemail_senders_are_not_services():
    assert is_personal_sender("anna.meier@gmail.com", "gmail.com")
    assert not is_personal_sender("no-reply@accounts.google.com", "accounts.google.com")
    assert not is_personal_sender("anna@acme.ch", "acme.ch")
    assert email_signals([email("Anna <anna.meier@gmail.com>", "Welcome to the family chat")], "gmail:o") == []


# -- one finding per account type -----------------------------------------------------

ACCOUNT_CASES = [
    ("social_media", "instagram", "Instagram <security@mail.instagram.com>", "New login to Instagram"),
    ("bank", "postfinance", "PostFinance <info@postfinance.ch>", "Your account statement is ready"),
    ("investment", "swissquote", "Swissquote <noreply@swissquote.ch>", "Your portfolio statement Q1"),
    ("crypto", "coinbase", "Coinbase <no-reply@coinbase.com>", "New sign-in from a new device"),
    ("cloud_storage", "dropbox", "Dropbox <no-reply@dropbox.com>", "Welcome to Dropbox"),
    ("email", "proton", "Proton <no-reply@proton.me>", "Security alert: new sign-in"),
    ("developer_cloud", "github", "GitHub <noreply@github.com>", "[GitHub] A new SSH key was added. Please verify your email"),
    ("password_manager", "bitwarden", "Bitwarden <no-reply@bitwarden.com>", "Welcome to Bitwarden"),
    ("utility_telecom", "ewz", "ewz <rechnung@ewz.ch>", "Ihre Rechnung Strom"),
    ("insurance", "mobiliar", "Die Mobiliar <service@mobiliar.ch>", "Your policy documents"),
    ("membership", "tcs", "TCS <info@tcs.ch>", "Welcome to TCS"),
    ("shopping", "galaxus", "Galaxus <info@galaxus.ch>", "Your order confirmation"),
    ("travel", "booking", "Booking.com <noreply@booking.com>", "Your booking confirmation"),
    ("payment", "paypal", "PayPal <service@paypal.ch>", "You sent a payment - receipt"),
    ("entertainment", "steam", "Steam <noreply@steampowered.com>", "Steam account verification: verify your email"),
]


@pytest.mark.parametrize("account_type, key, sender, subject", ACCOUNT_CASES, ids=[c[0] for c in ACCOUNT_CASES])
def test_each_account_type_is_detected(settings, account_type, key, sender, subject):
    result = run([(DAY, sender, subject, "Hello, this concerns your account.")], settings)
    account = by_key(result)[key]
    assert account["account_type"] == account_type
    assert account["estate_relevance"] == list(ACCOUNT_TYPES[account_type])
    assert account["classified_by"] == "catalog"
    assert account["evidence_ids"] and account["explanation"]
    assert "not accessed" in account["explanation"]


def test_unknown_domain_is_typed_by_keywords(settings):
    result = run([(DAY, "Alpenbank <kunden@alpenbank-xyz.ch>", "Ihr Kontoauszug", "IBAN CH00 ...")], settings)
    account = by_key(result)["alpenbank-xyz.ch"]
    assert account["account_type"] == "bank"
    assert account["classified_by"] == "keywords"
    assert account["service"]["name"] == "Alpenbank"


# -- merging and strength ---------------------------------------------------------------

def test_emails_from_one_service_are_merged(settings):
    messages = [
        (date(2025, 5, 1), "Coinbase <welcome@coinbase.com>", "Welcome to Coinbase", ""),
        (date(2025, 9, 1), "Coinbase <no-reply@info.coinbase.com>", "Weekly crypto newsletter", "unsubscribe"),
        (date(2026, 2, 1), "Coinbase <security@coinbase.com>", "New sign-in to Coinbase", ""),
    ]
    result = run(messages, settings)
    account = by_key(result)["coinbase"]
    assert len(account["evidence_ids"]) == 3
    assert account["evidence_strength"] == "strong" and account["confidence"] == "high"
    assert account["observed"]["first_seen"] == "2025-05-01" and account["observed"]["last_seen"] == "2026-02-01"
    assert account["observed"]["evidence_kinds"] == {"account_created": 1, "marketing": 1, "security": 1}
    # the strongest evidence is listed first and each record says why it counts
    evidence = {e["evidence_id"]: e for e in result["evidence"]}
    first = evidence[account["evidence_ids"][0]]
    assert first["signal"]["strength"] == "strong" and first["signal"]["rule"]


def test_weak_evidence_is_low_confidence_and_unknown_newsletters_are_dropped(settings):
    messages = [
        (DAY, "Netflix <info@mailer.netflix.com>", "New on Netflix this week", "unsubscribe"),
        (DAY, "Random Shop <news@random-shop.biz>", "Spring sale 40% off", "unsubscribe"),
    ]
    result = run(messages, settings)
    accounts = by_key(result)
    assert accounts["netflix"]["confidence"] == "low"
    assert any("do not prove" in r for r in accounts["netflix"]["confidence_reasons"])
    assert "random-shop.biz" not in accounts
    assert result["run"]["footprint"]["dropped_weak_unknown"] == 1


def test_connected_mailbox_is_an_email_account(settings):
    result = run([(DAY, "Google <no-reply@accounts.google.com>", "Security alert", "")], settings, account="owner@gmail.com")
    google = by_key(result)["google"]
    assert google["account_type"] == "email" and google["confidence"] == "high"
    assert google["observed"]["evidence_kinds"] == {"security": 1, "connected_mailbox": 1}
    assert google["account_email"] == "owner@gmail.com"


def test_evidence_per_account_is_capped(settings):
    settings.footprint_max_evidence_per_account = 3
    messages = [(DAY + timedelta(days=i), "Amazon <ship@amazon.de>", "Your order has shipped", "") for i in range(6)]
    account = by_key(run(messages, settings))["amazon"]
    assert len(account["evidence_ids"]) == 3
    assert account["observed"]["evidence_count"] == 6 and account["observed"]["evidence_omitted"] == 3


# -- other sources ---------------------------------------------------------------------

def test_transactions_naming_a_service_are_evidence(settings):
    rows = [row(ts="2026-02-03T10:00:00Z", amount=500, description="COINBASE IRELAND", mcc="6051")]
    result = discover_footprint(transactions=io.StringIO(jsonl_rows(rows)), use_llm=False, reference_date=REF, settings=settings)
    [account] = result["accounts"]
    assert account["service"]["key"] == "coinbase" and account["account_type"] == "crypto"
    assert account["evidence_strength"] == "medium" and account["confidence"] == "medium"
    [ev] = [e for e in result["evidence"] if e["evidence_id"] in account["evidence_ids"]]
    assert ev["type"] == "transaction" and ev["signal"]["kind"] == "payment"


def test_subscriptions_become_account_evidence_and_are_unchanged(settings):
    start = date(2025, 6, 3)
    receipts = [
        (start + timedelta(days=30 * i + 1), "Netflix <info@account.netflix.com>", "Your Netflix receipt",
         "You were charged CHF 18.90 for your monthly plan.")
        for i in range(8)
    ]
    security = [(date(2026, 1, 10), "Netflix <info@account.netflix.com>", "New sign-in to your Netflix account", "")]
    tx = [row(ts=f"{(start + timedelta(days=30 * i)).isoformat()}T09:00:00Z", amount=18.9, description="video access")
          for i in range(8)]
    result = run(receipts + security, settings, transactions=tx)
    [sub] = result["subscriptions"]
    netflix = by_key(result)["netflix"]
    assert netflix["subscription_ids"] == [sub["subscription_id"]]
    assert netflix["account_type"] == "entertainment"
    # billing emails already in the subscription evidence are reused, not duplicated
    assert set(sub["evidence_ids"]) & set(netflix["evidence_ids"])
    refs = [(e["source"], e["source_ref"]) for e in result["evidence"]]
    assert len(refs) == len(set(refs))

    # the subscription output is the same as from detect_subscriptions (security email aside)
    raw = [gmail_message(f"m{i}", d, s, subj, body) for i, (d, s, subj, body) in enumerate(receipts)]
    plain = detect_subscriptions(
        email_sources=[GmailSource(service=FakeGmailService(raw), today=REF)],
        transactions=io.StringIO(jsonl_rows(tx)), use_llm=False, reference_date=REF, settings=settings,
    )
    assert "accounts" not in plain
    assert plain["subscriptions"][0]["inferred"] == sub["inferred"]
    assert plain["subscriptions"][0]["confidence"] == sub["confidence"]


def test_transaction_only_subscription_is_its_own_account(settings):
    start = date(2025, 6, 3)
    tx = [row(ts=f"{(start + timedelta(days=30 * i)).isoformat()}T09:00:00Z", amount=37.5, description="gym membership", mcc="7997")
          for i in range(9)]
    result = discover_footprint(transactions=io.StringIO(jsonl_rows(tx)), use_llm=False, reference_date=REF, settings=settings)
    [account] = result["accounts"]
    assert account["account_type"] == "membership" and account["classified_by"] == "subscription"
    assert account["service"]["name"] is None and account["subscription_ids"] == ["sub-0001"]


# -- LLM for ambiguous services only -------------------------------------------------------

def _classifier(account_type="insurance", name="Helvetas", reason="subjects mention a premium"):
    def answer(messages):
        assert messages[0]["content"].startswith("You help heirs")
        payload = json.loads(messages[-1]["content"].split("Services:\n", 1)[1])
        return json.dumps({"services": [
            {"id": s["id"], "account_type": account_type, "name": name, "reason": reason} for s in payload
        ]})
    return answer


AMBIGUOUS = [(DAY, "Helvetas Portal <no-reply@helvetas-portal.ch>", "Welcome to your portal", "")]


def test_llm_classifies_only_ambiguous_services(settings):
    known = [(DAY, "GitHub <noreply@github.com>", "Welcome to GitHub", "")]
    fake = FakeLLM(_classifier())
    result = run(AMBIGUOUS + known, settings, llm_client=fake)
    assert len(fake.calls) == 1  # no billing emails -> only the classification call
    sent = fake.calls[0][-1]["content"]
    assert "helvetas-portal.ch" in sent and "github" not in sent.lower()
    account = by_key(result)["helvetas-portal.ch"]
    assert account["account_type"] == "insurance" and account["classified_by"] == "llm"
    assert account["service"]["name"] == "Helvetas"
    assert any("classified by AI" in r for r in account["confidence_reasons"])
    assert result["run"]["footprint"]["llm_classified"] == 1


def test_llm_name_must_come_from_the_evidence(settings):
    result = run(AMBIGUOUS, settings, llm_client=FakeLLM(_classifier(name="Totally Invented AG")))
    assert by_key(result)["helvetas-portal.ch"]["service"]["name"] == "Helvetas Portal"


def test_llm_not_a_service_lowers_confidence(settings):
    result = run(AMBIGUOUS, settings, llm_client=FakeLLM(_classifier(account_type="not_a_service", reason="a club newsletter")))
    account = by_key(result)["helvetas-portal.ch"]
    assert account["confidence"] == "low" and account["account_type"] == "other"


def test_llm_failure_keeps_rules_result(settings):
    settings.llm_retries = 1
    result = run(AMBIGUOUS, settings, llm_client=FakeLLM(RuntimeError("down")))
    account = by_key(result)["helvetas-portal.ch"]
    assert account["account_type"] == "other" and account["classified_by"] is None
    assert any("account type could not be determined" in r for r in account["confidence_reasons"])
    assert any("AI classification of unknown services unavailable" in w for w in result["run"]["warnings"])


# -- output ----------------------------------------------------------------------------

def test_footprint_output_schema(settings):
    messages = [c[2:] for c in ACCOUNT_CASES]
    result = run([(DAY, s, subj, "") for s, subj in messages], settings)
    assert set(result) == {"run", "evidence", "subscriptions", "accounts"}
    ids = [e["evidence_id"] for e in result["evidence"]]
    assert len(ids) == len(set(ids))
    for i, a in enumerate(result["accounts"], start=1):
        assert a["account_id"] == f"acc-{i:04d}"
        assert set(a) >= {"service", "account_type", "estate_relevance", "evidence_ids", "observed",
                          "evidence_strength", "confidence", "confidence_reasons", "explanation", "classified_by"}
        assert set(a["evidence_ids"]) <= set(ids)
        assert a["account_type"] in ACCOUNT_TYPES
    # money-related accounts come first among equally confident findings
    assert result["accounts"][0]["account_type"] == "bank"
    for e in result["evidence"]:
        if e["type"] == "email":
            assert len(e["observed"]["snippet"]) <= 200
    json.dumps(result)


def test_footprint_gmail_query_includes_account_emails():
    source = GmailSource(service=FakeGmailService([]), terms=FOOTPRINT_TERMS)
    assert '"sign-in"' in source.query and "Kontoauszug" in source.query and "receipt" in source.query
    assert "sign-in" not in GmailSource(service=FakeGmailService([])).query


def test_cli_footprint(tmp_path, capsys):
    from subscription_finder.cli import main

    data = tmp_path / "tx.jsonl"
    data.write_text(jsonl_rows([row(ts="2026-02-03T10:00:00Z", amount=50, description="PAYPAL *SHOP")]), encoding="utf-8")
    out = tmp_path / "out.json"
    assert main(["--transactions", str(data), "--no-llm", "--footprint", "--reference-date", "2026-06-01", "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["accounts"][0]["service"]["key"] == "paypal"
    assert "1 account(s)" in capsys.readouterr().out
