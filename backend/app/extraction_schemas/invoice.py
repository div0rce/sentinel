"""The ``invoice`` schema. Fields match the synthetic invoice corpus in
``data/sample/invoice_inv-*.md``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from backend.app.extraction_schemas.base import ExtractedField

ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def _validate_iso_date(value: str) -> str:
    """Require a real ISO calendar date while preserving the stored string shape."""
    date.fromisoformat(value)
    return value


InvoiceDateString = Annotated[
    str,
    StringConstraints(pattern=ISO_DATE_PATTERN),
    AfterValidator(_validate_iso_date),
]


class InvoicePayload(BaseModel):
    """A structured invoice record extracted from a document."""

    model_config = ConfigDict(extra="forbid")

    invoice_number: ExtractedField[str]
    vendor: ExtractedField[str]
    issue_date: ExtractedField[InvoiceDateString]
    """ISO 8601 date string (``YYYY-MM-DD``)."""
    total_due: ExtractedField[float]
