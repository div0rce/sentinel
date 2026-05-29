"""Unit tests for the M5 guardrails module."""

from __future__ import annotations

import pytest

from backend.app.guardrails import (
    PII_PATTERNS,
    RedactionHit,
    low_confidence_fields,
    redact_pii,
    requires_review,
)

# --- redaction patterns ---------------------------------------------------------------


def test_email_redaction() -> None:
    result = redact_pii("Contact john.doe@example.com for details.")
    assert result.text == "Contact [REDACTED:EMAIL] for details."
    assert len(result.hits) == 1
    assert result.hits[0].kind == "EMAIL"
    assert result.hits[0].original == "john.doe@example.com"


def test_ssn_redaction() -> None:
    result = redact_pii("SSN 123-45-6789 on file.")
    assert "[REDACTED:SSN]" in result.text
    assert "123-45-6789" not in result.text
    assert any(h.kind == "SSN" for h in result.hits)


def test_phone_redaction_us_formats() -> None:
    cases = [
        "Call 415-555-0123 today",
        "Call (415) 555-0123 today",
        "Call +1 415-555-0123 today",
        "Call 415.555.0123 today",
    ]
    for sample in cases:
        result = redact_pii(sample)
        assert "[REDACTED:PHONE]" in result.text, f"phone not redacted: {sample}"
        assert any(h.kind == "PHONE" for h in result.hits)


def test_credit_card_redaction() -> None:
    result = redact_pii("Card 4111-1111-1111-1111 expires soon.")
    assert "[REDACTED:CREDIT_CARD]" in result.text
    assert "4111-1111-1111-1111" not in result.text


def test_ipv4_redaction() -> None:
    result = redact_pii("Host 10.0.0.1 logged in at 192.168.1.42.")
    assert result.text.count("[REDACTED:IPV4]") == 2
    assert "10.0.0.1" not in result.text
    assert "192.168.1.42" not in result.text


def test_redaction_handles_multiple_kinds_in_one_string() -> None:
    text = (
        "Contact alice@example.org or 415-555-9999. "
        "SSN 999-88-7777, card 5500 0000 0000 0004, host 8.8.8.8."
    )
    result = redact_pii(text)
    kinds = {h.kind for h in result.hits}
    assert kinds == {"EMAIL", "PHONE", "SSN", "CREDIT_CARD", "IPV4"}
    assert "alice@example.org" not in result.text
    assert "999-88-7777" not in result.text


def test_redaction_is_idempotent() -> None:
    """A second pass over redacted output must not match anything new."""
    original = "Email alice@example.org, phone 415-555-0001."
    once = redact_pii(original).text
    twice = redact_pii(once)
    assert twice.text == once
    assert twice.hits == []


def test_redaction_empty_input() -> None:
    result = redact_pii("")
    assert result.text == ""
    assert result.hits == []


def test_redaction_pii_free_input_passes_through() -> None:
    text = "This is plain prose with no personal data."
    result = redact_pii(text)
    assert result.text == text
    assert result.hits == []


def test_redaction_hits_have_correct_spans() -> None:
    text = "The email is bob@example.com here."
    result = redact_pii(text)
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.kind == "EMAIL"
    assert text[hit.start : hit.end] == "bob@example.com"
    assert hit.original == "bob@example.com"


def test_pattern_registry_contains_expected_kinds() -> None:
    kinds = {kind for kind, _ in PII_PATTERNS}
    assert kinds == {"EMAIL", "SSN", "PHONE", "CREDIT_CARD", "IPV4"}


# --- false-positive cushions --------------------------------------------------------


def test_redaction_does_not_match_isolated_short_digits() -> None:
    # Too few digits to look like a phone or SSN.
    result = redact_pii("Order 123 was shipped.")
    assert result.hits == []


def test_redaction_does_not_match_inside_longer_digits() -> None:
    # 17 contiguous digits should not be misread as a 16-digit credit card.
    result = redact_pii("Refnum 12345678901234567 is internal.")
    cc_hits = [h for h in result.hits if h.kind == "CREDIT_CARD"]
    assert cc_hits == []


# --- confidence gating ---------------------------------------------------------------


def test_low_confidence_fields_filters_strictly_below_threshold() -> None:
    fc = {"a": 0.95, "b": 0.74, "c": 0.75, "d": 0.30}
    assert low_confidence_fields(fc, threshold=0.75) == ["b", "d"]


def test_low_confidence_fields_preserves_insertion_order() -> None:
    fc = {"z": 0.10, "a": 0.20, "m": 0.30}
    assert low_confidence_fields(fc, threshold=0.75) == ["z", "a", "m"]


def test_low_confidence_fields_empty_map() -> None:
    assert low_confidence_fields({}, threshold=0.75) == []


def test_low_confidence_fields_all_high() -> None:
    assert low_confidence_fields({"a": 0.9, "b": 0.95}, threshold=0.75) == []


def test_low_confidence_fields_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        low_confidence_fields({"a": 0.5}, threshold=1.5)
    with pytest.raises(ValueError):
        low_confidence_fields({"a": 0.5}, threshold=-0.1)


def test_requires_review_true_when_any_field_below() -> None:
    assert requires_review({"a": 0.9, "b": 0.4}, threshold=0.75) is True


def test_requires_review_false_when_all_at_or_above() -> None:
    assert requires_review({"a": 0.75, "b": 0.95}, threshold=0.75) is False


def test_requires_review_empty_map_is_false() -> None:
    assert requires_review({}, threshold=0.75) is False


# --- RedactionHit dataclass invariants ------------------------------------------------


def test_redaction_hit_is_frozen() -> None:
    hit = RedactionHit(kind="EMAIL", start=0, end=5, original="x@y.z")
    with pytest.raises((AttributeError, Exception)):
        hit.kind = "SSN"  # type: ignore[misc]
