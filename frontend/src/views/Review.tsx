import { useCallback, useEffect, useState } from "react";
import { Check, RotateCcw, ShieldCheck, X } from "lucide-react";
import {
  approveReview,
  ApiError,
  getReviewQueue,
  rejectReview,
  type ReviewItem,
} from "../api";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; items: ReviewItem[] }
  | { kind: "error"; message: string };

const DEFAULT_ACTOR = "user:reviewer";

export function Review(): JSX.Element {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [actor, setActor] = useState(DEFAULT_ACTOR);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setState({ kind: "loading" });
    setFlash(null);
    try {
      const queue = await getReviewQueue({ limit: 50 });
      setState({ kind: "loaded", items: queue.items });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Network error.";
      setState({ kind: "error", message });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function decide(item: ReviewItem, decision: "approve" | "reject"): Promise<void> {
    const reviewer = actor.trim();
    if (!reviewer) {
      setFlash("Reviewer name is required.");
      return;
    }
    setBusyId(item.id);
    setFlash(null);
    try {
      const action = decision === "approve" ? approveReview : rejectReview;
      const resp = await action(item.id, { actor: reviewer });
      // Optimistic: drop the row from the local list rather than refetching.
      setState((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", items: prev.items.filter((it) => it.id !== item.id) }
          : prev,
      );
      const verb = decision === "approve" ? "approved" : "rejected";
      setFlash(
        `✓ Item #${item.id} ${verb} · by ${reviewer} · audit event #${resp.audit_event_id} written`,
      );
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Network error.";
      setFlash(`Failed to ${decision}: ${message}`);
    } finally {
      setBusyId(null);
    }
  }

  const pending = state.kind === "loaded" ? state.items.length : 0;

  return (
    <section aria-labelledby="review-heading">
      <div className="view-head">
        <p className="eyebrow">Human-in-the-loop · append-only audit</p>
        <h1 id="review-heading" className="view-title">
          Review queue
        </h1>
        <p className="view-sub">
          Fields below the auto-approve confidence threshold (0.90). Each decision is idempotent
          and writes one append-only audit event.
        </p>
      </div>

      <div className="queue-bar">
        <label htmlFor="actor-input" className="field-label" style={{ margin: 0 }}>
          Reviewer
        </label>
        <input
          id="actor-input"
          type="text"
          aria-label="reviewer"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          maxLength={256}
        />
        <span className="muted mono" style={{ marginLeft: "auto", fontSize: "var(--text-xs)" }}>
          {pending} pending
        </span>
        <button
          type="button"
          className="btn sm"
          onClick={() => void refresh()}
          disabled={state.kind === "loading"}
        >
          <RotateCcw size={14} aria-hidden />
          Refresh
        </button>
      </div>

      {flash && (
        <div className="flash" role="status">
          {flash}
        </div>
      )}

      {state.kind === "loading" && <p className="muted">Loading queue…</p>}
      {state.kind === "error" && (
        <div className="error" role="alert">
          {state.message}
        </div>
      )}
      {state.kind === "loaded" && state.items.length === 0 && (
        <div className="empty">
          <ShieldCheck size={26} aria-hidden />
          <div>Nothing awaiting review. The queue is empty.</div>
        </div>
      )}
      {state.kind === "loaded" &&
        state.items.map((item) => (
          <div className="card" key={item.id} data-testid={`review-item-${item.id}`}>
            <div className="review-item">
              <div>
                <h3>
                  <span className="code">workflow #{item.id}</span>
                  <span className={`badge ${item.status}`}>{item.status}</span>
                </h3>
                <div className="meta">
                  <div className="kv">
                    extraction <span className="mono">#{item.extraction_id}</span>
                    <span className="sep">·</span>
                    key <span className="mono">{item.idempotency_key.slice(0, 16)}…</span>
                  </div>
                  <div className="kv">
                    created <span className="mono">{item.created_at}</span>
                  </div>
                  {item.reason && <div className="kv reason">{item.reason}</div>}
                </div>
              </div>
              <div className="review-actions">
                <button
                  type="button"
                  className="btn primary sm"
                  disabled={busyId === item.id}
                  onClick={() => void decide(item, "approve")}
                >
                  <Check size={14} aria-hidden />
                  Approve
                </button>
                <button
                  type="button"
                  className="btn danger sm"
                  disabled={busyId === item.id}
                  onClick={() => void decide(item, "reject")}
                >
                  <X size={14} aria-hidden />
                  Reject
                </button>
              </div>
            </div>
          </div>
        ))}
    </section>
  );
}
