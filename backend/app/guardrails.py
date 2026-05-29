"""Centralized, deterministic safety layer.

Two responsibilities live here:

* **PII redaction.** A small set of named regular expressions matches common PII
  shapes (email, US SSN, US phone, credit card, IPv4). :func:`redact_pii` replaces
  every match with ``[REDACTED:KIND]`` and returns the redacted text alongside a
  list of :class:`RedactionHit` records. Callers redact text **before any LLM
  call** and **before storage**, satisfying the M5 invariant.
* **Confidence gating.** :func:`low_confidence_fields` and :func:`requires_review`
  inspect a per-field confidence map against
  :attr:`backend.app.config.Settings.confidence_review_threshold`. They return
  flags only — they never mutate state and they never block the underlying
  operation. Routing low-confidence records to a review queue is the M6 workflow
  engine's job; this module just labels.

Everything in this module is pure and deterministic: no I/O, no random state, no
hidden globals beyond the compiled regex registry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

PIIKind = Literal["EMAIL", "SSN", "PHONE", "CREDIT_CARD", "IPV4"]


# --- pattern registry ---------------------------------------------------------------
#
# Patterns are intentionally conservative. False positives at this layer are far less
# bad than false negatives — over-redacting a synthetic invoice never hurt anyone, and
# under-redacting a real document leaks PII. Patterns target shape, not content. The
# unit tests pin every pattern's behaviour against a small known set.

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")
_CREDIT_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[- ]){3}\d{4}(?!\d)")
_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Order matters: more specific patterns should win over less-specific ones for a given
# region of text. Email beats IPv4 at "@1.2.3.4"; SSN beats phone for "123-45-6789".
PII_PATTERNS: Final[tuple[tuple[PIIKind, re.Pattern[str]], ...]] = (
    ("EMAIL", _EMAIL_PATTERN),
    ("SSN", _SSN_PATTERN),
    ("CREDIT_CARD", _CREDIT_CARD_PATTERN),
    ("PHONE", _PHONE_PATTERN),
    ("IPV4", _IPV4_PATTERN),
)


# --- redaction ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RedactionHit:
    """One PII match found during :func:`redact_pii`."""

    kind: PIIKind
    start: int
    end: int
    original: str


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Output of :func:`redact_pii`."""

    text: str
    hits: list[RedactionHit] = field(default_factory=list)


def _placeholder(kind: PIIKind) -> str:
    return f"[REDACTED:{kind}]"


def redact_pii(text: str) -> RedactionResult:
    """Return ``text`` with every PII match replaced by ``[REDACTED:KIND]``.

    Determinism: the function depends only on the input string and the compiled
    regex registry; identical input yields identical output.

    Resolution policy: each pattern is applied to the *original* text in
    :data:`PII_PATTERNS` order. Overlapping matches are resolved by keeping the
    earlier-registered pattern (which is the more specific one in the current
    registry). Replacement is a single pass against the original-position spans, so
    placeholder text never re-matches downstream patterns.
    """
    if not text:
        return RedactionResult(text=text, hits=[])

    spans: list[tuple[int, int, PIIKind, str]] = []
    claimed: list[tuple[int, int]] = []

    for kind, pattern in PII_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(_overlaps((start, end), span) for span in claimed):
                continue
            spans.append((start, end, kind, match.group(0)))
            claimed.append((start, end))

    if not spans:
        return RedactionResult(text=text, hits=[])

    spans.sort(key=lambda s: s[0])

    pieces: list[str] = []
    cursor = 0
    hits: list[RedactionHit] = []
    for start, end, kind, original in spans:
        pieces.append(text[cursor:start])
        pieces.append(_placeholder(kind))
        hits.append(RedactionHit(kind=kind, start=start, end=end, original=original))
        cursor = end
    pieces.append(text[cursor:])

    return RedactionResult(text="".join(pieces), hits=hits)


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])


# --- confidence gating -------------------------------------------------------------


def low_confidence_fields(field_confidence: Mapping[str, float], *, threshold: float) -> list[str]:
    """Return the names of fields whose confidence is **strictly below** ``threshold``.

    Field order matches insertion order in ``field_confidence`` so the output is
    deterministic for downstream display and audit purposes.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")
    return [name for name, conf in field_confidence.items() if conf < threshold]


def requires_review(field_confidence: Mapping[str, float], *, threshold: float) -> bool:
    """``True`` iff at least one field is below ``threshold``.

    Pure flag; never mutates state, never blocks an extraction. The M6 workflow
    engine consumes this to route records.
    """
    return bool(low_confidence_fields(field_confidence, threshold=threshold))
