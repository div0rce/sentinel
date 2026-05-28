# Architecture

> The full architecture write-up and the Mermaid diagram land in Milestone M11.
> This file exists from M0 so the docs structure is in place from the start.

Sentinel is a governed document-intelligence platform. The pipeline is:
ingestion → retrieval → citation-grounded RAG and schema-constrained extraction →
guardrails → a deterministic, idempotent, human-in-the-loop workflow with an
immutable audit trail.

Architectural decisions are recorded as ADRs under [`docs/adr/`](adr/).
