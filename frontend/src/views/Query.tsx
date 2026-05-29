import { useState, type FormEvent } from "react";
import { ApiError, postQuery, type QueryResponse } from "../api";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "answered"; result: QueryResponse }
  | { kind: "error"; message: string };

export function Query(): JSX.Element {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    setState({ kind: "loading" });
    try {
      const result = await postQuery({ query: trimmed });
      setState({ kind: "answered", result });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Network error.";
      setState({ kind: "error", message });
    }
  }

  return (
    <section aria-labelledby="query-heading">
      <h2 id="query-heading">Ask a question</h2>
      <form onSubmit={onSubmit} aria-label="query form">
        <textarea
          aria-label="question"
          placeholder="Ask a question about the synthetic corpus…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={4000}
        />
        <div className="row" style={{ marginTop: "0.5rem" }}>
          <button
            type="submit"
            className="primary"
            disabled={state.kind === "loading" || !question.trim()}
          >
            {state.kind === "loading" ? "Asking…" : "Ask"}
          </button>
          <span className="muted">
            Citations are required — Sentinel refuses to answer without them.
          </span>
        </div>
      </form>

      <div style={{ marginTop: "1.25rem" }}>
        {state.kind === "idle" && (
          <p className="muted">Submit a question to see a cited answer or a deliberate refusal.</p>
        )}
        {state.kind === "loading" && <p className="muted">Retrieving and generating…</p>}
        {state.kind === "error" && (
          <div className="error" role="alert">
            {state.message}
          </div>
        )}
        {state.kind === "answered" && <Answer result={state.result} />}
      </div>
    </section>
  );
}

function Answer({ result }: { result: QueryResponse }): JSX.Element {
  if (result.status === "refused") {
    return (
      <div className="card" role="status">
        <h3>Refused</h3>
        <p>{result.answer}</p>
        {result.reason && (
          <p className="muted">
            Reason: <code>{result.reason}</code>
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="card" role="status">
      <h3>Answer</h3>
      <p style={{ whiteSpace: "pre-wrap" }}>{result.answer}</p>
      <h3 style={{ marginTop: "0.75rem" }}>
        Citations ({result.citations.length})
      </h3>
      {result.citations.length === 0 ? (
        <p className="muted">No citations.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {result.citations.map((c) => (
            <li key={c.chunk_id} className="citation">
              <div className="muted">
                chunk #{c.chunk_id} · doc #{c.document_id} · score{" "}
                {c.score.toFixed(3)}
              </div>
              <div style={{ marginTop: "0.25rem", whiteSpace: "pre-wrap" }}>{c.text}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
