"""Name → schema-class mapping.

Adding a schema is a two-line edit: define the model under ``extraction_schemas/``,
register it here. The orchestrator looks up schemas by the string name supplied in
the API request (``POST /extract`` ``schema_name`` field).
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.app.extraction_schemas.invoice import InvoicePayload

SCHEMAS: dict[str, type[BaseModel]] = {
    "invoice": InvoicePayload,
}


def get_schema(name: str) -> type[BaseModel]:
    """Return the schema class for ``name``. Raises :class:`KeyError` if unknown."""
    if name not in SCHEMAS:
        raise KeyError(f"Unknown extraction schema: {name!r}. Known: {sorted(SCHEMAS)}")
    return SCHEMAS[name]


def list_schemas() -> list[str]:
    """Return the registered schema names, sorted alphabetically."""
    return sorted(SCHEMAS)
