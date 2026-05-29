import { useCallback, useEffect, useState } from "react";
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
    if (!actor.trim()) {
      setFlash("Reviewer name is required.");
      return;
    }
    setBusyId(item.id);
    setFlash(null);
    try {
      const action = decision === "approve" ? approveReview : rejectReview;
      await action(item.id, { actor: actor.trim() });
      // Optimistic: drop the row from the local list rather than refetching.
      setState((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", items: prev.items.filter((it) => it.id !== item.id) }
          : prev,
      );
      setFlash(`Item #${item.id} ${decision === "approve" ? "approved" : "rejected"}.`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Network error.";
      setFlash(`Failed to ${decision}: ${message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section aria-labelledby="review-heading">
      <h2 id="review-heading">Review queue</h2>
      <div className="row" style={{ marginBottom: "0.75rem" }}>
        <label htmlFor="actor-input" className="muted">
          Reviewer:
        </label>
        <input
          id="actor-input"
          aria-label="reviewer"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          style={{ maxWidth: "20rem" }}
          maxLength={256}
        />
        <button onClick={() => void refresh()} disabled={state.kind === "loading"}>
          Refresh
        </button>
      </div>

      {flash && (
        <p className="muted" role="status" style={{ marginBottom: "0.75rem" }}>
          {flash}
        </p>
      )}

      {state.kind === "loading" && <p className="muted">Loading queue…</p>}
      {state.kind === "error" && (
        <div className="error" role="alert">
          {state.message}
        </div>
      )}
      {state.kind === "loaded" && state.items.length === 0 && (
        <div className="empty">Nothing awaiting review. The queue is empty.</div>
      )}
      {state.kind === "loaded" && state.items.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {state.items.map((item) => (
            <li key={item.id} className="card" data-testid={`review-item-${item.id}`}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <h3>
                    Workflow item #{item.id}{" "}
                    <span className={`badge ${item.status}`}>{item.status}</span>
                  </h3>
                  <p className="muted">
                    extraction #{item.extraction_id} · key{" "}
                    <code>{item.idempotency_key.slice(0, 12)}…</code>
                    {item.reason ? ` · reason ${item.reason}` : null}
                  </p>
                  <p className="muted">created {item.created_at}</p>
                </div>
                <div className="row">
                  <button
                    className="primary"
                    disabled={busyId === item.id}
                    onClick={() => void decide(item, "approve")}
                  >
                    Approve
                  </button>
                  <button
                    className="danger"
                    disabled={busyId === item.id}
                    onClick={() => void decide(item, "reject")}
                  >
                    Reject
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
