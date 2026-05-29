"""Extraction-schema registry.

Each schema describes an extracted record shape. Every field is wrapped in
:class:`ExtractedField`, which forces ``value``, per-field ``confidence``, and a
``source_chunk_id`` that points back into the chunks supplied as context — that is
the M4 contract ("each field carries confidence + source chunk id").

The registry is a flat ``name → schema class`` mapping. M4 ships one schema
(``invoice``) so the synthetic corpus is actionable; future milestones add more.
"""

from __future__ import annotations

from backend.app.extraction_schemas.base import ExtractedField
from backend.app.extraction_schemas.invoice import InvoicePayload
from backend.app.extraction_schemas.registry import (
    SCHEMAS,
    get_schema,
    list_schemas,
)

__all__ = [
    "SCHEMAS",
    "ExtractedField",
    "InvoicePayload",
    "get_schema",
    "list_schemas",
]
