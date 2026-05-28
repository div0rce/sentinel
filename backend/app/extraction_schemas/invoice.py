"""The ``invoice`` schema. Fields match the synthetic invoice corpus in
``data/sample/invoice_inv-*.md``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.extraction_schemas.base import ExtractedField


class InvoicePayload(BaseModel):
    """A structured invoice record extracted from a document."""

    model_config = ConfigDict(extra="forbid")

    invoice_number: ExtractedField[str]
    vendor: ExtractedField[str]
    issue_date: ExtractedField[str]
    """ISO 8601 date string (``YYYY-MM-DD``)."""
    total_due: ExtractedField[float]
