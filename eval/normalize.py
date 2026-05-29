"""Per-field-type normalization for extraction comparison.

Raw exact-match deflates the accuracy number for cosmetic reasons (``"Dr. Smith"``
vs ``"Smith"``, ``"3/4/25"`` vs ``"2025-03-04"``). Normalization documents
exactly which transformations are applied, per field type, so the metric is
honest and explainable.

Rules (keep this list in sync with ``docs/evaluation.md``):

* **Strings** — ``str.strip().casefold()``. Internal whitespace is preserved.
* **ISO dates** (``YYYY-MM-DD`` shape) — round-tripped through ``date.fromisoformat``
  to canonicalise. Non-ISO date strings fall through to the string rule, which is
  the desired behaviour (a non-ISO answer is wrong by the schema).
* **Numbers** — coerced to ``float`` and rounded to ``DEFAULT_NUMERIC_DECIMALS``
  decimals (2). Within ``DEFAULT_NUMERIC_TOLERANCE`` (0.01) of the expected value
  is considered equal.
* ``None`` (missing field) is preserved and only equals ``None``.

These choices are intentionally conservative — they remove cosmetic noise without
forgiving a wrong answer. Per-field precision/recall (in :mod:`eval.harness`)
distinguishes ``wrong-value`` from ``missing-field`` for any optional field, so
that distinction is not lost by normalization.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Final

DEFAULT_NUMERIC_DECIMALS: Final[int] = 2
DEFAULT_NUMERIC_TOLERANCE: Final[float] = 0.01

_ISO_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize(value: Any) -> Any:
    """Return the canonical form of ``value`` for comparison.

    Idempotent: ``normalize(normalize(x)) == normalize(x)``. The function never
    raises — anything not covered by the rules above passes through unchanged.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if _ISO_DATE_PATTERN.fullmatch(stripped):
            try:
                return date.fromisoformat(stripped).isoformat()
            except ValueError:
                # Fall through: shape matched but the date is invalid (e.g. 2026-13-01).
                pass
        return stripped.casefold()
    if isinstance(value, bool):
        # bool is a subclass of int — handle before int.
        return value
    if isinstance(value, (int, float)):
        if math.isnan(value):
            return value
        return round(float(value), DEFAULT_NUMERIC_DECIMALS)
    return value


def values_equal(
    expected: Any,
    actual: Any,
    *,
    numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE,
) -> bool:
    """``True`` iff ``actual`` matches ``expected`` after normalization.

    Numeric comparison uses an absolute tolerance rather than strict equality so
    a model that returns ``$1,234.567`` against an expected ``1234.56`` is not
    penalised for one rounding step. The tolerance is documented and small.
    """
    e_norm = normalize(expected)
    a_norm = normalize(actual)
    if isinstance(e_norm, float) and isinstance(a_norm, float):
        return math.isclose(e_norm, a_norm, abs_tol=numeric_tolerance)
    return bool(e_norm == a_norm)
