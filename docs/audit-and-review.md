# Audit log and human-in-the-loop review

The M1 `audit_events` table is **append-only** at the repository layer. M7 adds the
semantic emitters that wrap it, the human-in-the-loop review queue, and the
`replay_workflow_state` primitive that reconstructs current state from the audit
log alone.

The implementation lives in `backend/app/audit.py` and
`backend/app/routers/review.py`.

## Audit-action catalogue

Sentinel emits a small, stable set of named actions. Strings, not an Enum, so a
future migration can add new actions without coordinating an enum-type migration on
the database. The set is pinned by `test_audit_action_catalogue_is_stable`.

| Action               | Emitted by                                  | Target type      | `before`                         | `after` highlights                                      |
| -------------------- | ------------------------------------------- | ---------------- | -------------------------------- | ------------------------------------------------------- |
| `extraction.created` | `extract.extract_document` (M4 success path)| `extraction`     | `null`                           | `schema_name`, `payload`, `field_confidence`, `field_citations`, `model_name` |
| `workflow.routed`    | `workflow.route_extraction` (M6 routing)    | `workflow_item`  | `null` on insert, `{status}` on transition | `{status, reason, extraction_id}`              |
| `review.approved`    | `POST /review/{id}/approve` (M7)            | `workflow_item`  | `{status: needs_review}`         | `{status: auto_approved, reason, note?}`                |
| `review.rejected`    | `POST /review/{id}/reject` (M7)             | `workflow_item`  | `{status: needs_review}`         | `{status: rejected, reason, note?}`                     |

Every event also carries:

- `actor` — `system:extract`, `system:workflow`, or a human identifier such as
  `user:alice`.
- `request_id` — optional correlation id (set per HTTP request once authentication
  lands in M8).
- `ts` — DB-side `now()`; the application never supplies a clock value.
- `target_type`, `target_id` — pair lookup index for cheap `list_for_target` reads.

## Emission rules (DoD: "exactly one event per suggestion / decision")

The DoD is enforced in code:

- `extract.extract_document` calls `emit_extraction_created` **after** persisting
  the row. Failures (parse error, schema invalid, invalid citation) **do not**
  persist and **do not** emit.
- `workflow.route_extraction` captures the prior status before `apply_routing`,
  then emits `workflow.routed` **only when the persistence layer actually changed
  state**. Idempotent re-routes that hit the no-op branch emit nothing.
- The review routes emit exactly one `review.*` event per successful 200 response.
  4xx responses (`409` not in needs_review, `404` unknown id, `422` validation)
  emit nothing.

Tests pin every clause: `test_route_extraction_emits_one_workflow_routed_event`,
`test_idempotent_reroute_does_not_emit_duplicate`,
`test_route_extraction_emits_on_status_change`,
`test_post_approve_transitions_and_audits`, and the rest.

## Human-in-the-loop transitions

The review router is the **only** legitimate path for transitions that the M6
rule engine refuses (`apply_routing` raises `IllegalTransition` for
`REJECTED → AUTO_APPROVED`). The router scope is narrow:

| Endpoint                            | Allowed prior status | Resulting status | Audit action         |
| ----------------------------------- | -------------------- | ---------------- | -------------------- |
| `POST /review/{id}/approve`         | `needs_review`       | `auto_approved`  | `review.approved`    |
| `POST /review/{id}/reject`          | `needs_review`       | `rejected`       | `review.rejected`    |

Items in any other status return 409 Conflict. This keeps the human path scoped
to its purpose; the supervisor-reversal flow (re-opening a rejected item) lives
behind a different action and arrives in a later milestone.

Request body for both endpoints:

```json
{
  "actor": "user:alice",
  "note": "looks good"
}
```

`actor` is required (1–256 chars); `note` is optional free-text up to 4000 chars.
Authentication-derived actors arrive in M8.

`GET /review?limit=50&offset=0` returns the queue: workflow items currently in
`needs_review`, newest first. `limit` is bounded `[1, 200]`; `offset` is `>= 0`.

## State-from-replay protocol (DoD keystone)

`replay_workflow_state(session, *, workflow_item_id) -> WorkflowStatus | None`
walks every event recorded against `(target_type='workflow_item',
target_id=workflow_item_id)` oldest-first and returns the final
`WorkflowStatus`. The function reads from `after.status` on each event; events
without an `after.status` field (or with an unknown value) are skipped.

The contract: for any workflow item whose entire lifecycle was driven through the
emitters in `backend.app.audit`, the result of `replay_workflow_state` equals the
persisted `workflow_items.status`.

`test_state_from_replay_reconstructs_current_status` walks a five-event lifecycle
(insert → route transition → reject → reopen → approve) and asserts equality.

### Limits

- The audit log captures *what changed*, not the full extraction payload at every
  step. Reconstructing a payload as of an arbitrary timestamp would need a
  different replay function (M9 may add one if eval calls for it).
- Replay assumes append-only semantics. The repository layer enforces this by
  exposing only `append` and read helpers; an introspection test in M1
  (`test_audit_events_append_only`) would fail if a future change added a public
  `update_*` or `delete_*` symbol.
- `actor` and `request_id` are not consulted by replay; they are read by the
  M9 evaluation harness and the M8 dashboard.

## Configuration

No new env vars in M7. The review-queue page size is bounded inside the router
(`limit` ∈ `[1, 200]`).

## Reading the audit log directly

The repository layer exposes:

- `audit_events_repo.append(...)` — used only inside the emitters.
- `audit_events_repo.list_for_target(session, target_type, target_id)` — every
  event for one target, oldest first; the engine `replay_workflow_state` relies
  on this ordering.
- `audit_events_repo.list_by_request_id(session, request_id)` — every event
  carrying a given request id, useful for tracing a single API call across
  emitters in M8.
- `audit_events_repo.get(session, event_id)` — single-row read.

## Wiring map

```
extract.extract_document        workflow.route_extraction          POST /review/{id}/(approve|reject)
        │                                │                                       │
        ▼                                ▼                                       ▼
 emit_extraction_created        emit_workflow_routed                emit_review_decision
        │                                │                                       │
        └──────────────────┬─────────────┴───────────────────────────────────────┘
                           ▼
                  audit_events_repo.append
                           │
                           ▼
                       audit_events
                           │
                           ▼
              replay_workflow_state(workflow_item_id)
                           │
                           ▼
                    WorkflowStatus
```
