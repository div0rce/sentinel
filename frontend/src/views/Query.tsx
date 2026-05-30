import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Search } from "lucide-react";
import { ApiError, postQuery, type QueryResponse } from "../api";

// Example questions sourced from the synthetic corpus. Clicking one fills and submits.
// The last is a deliberate refusal case — by design, not an error.
const SUGGESTIONS = [
  "What is the total amount due on the Initech Components invoice issued on 2026-01-22?",
  "Summarize incident INC-0700 and its duration.",
  "Who owns the supplier onboarding policy and when is it effective?",
  "What was our Q3 revenue and projected churn for next year?",
];

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "answered"; result: QueryResponse }
  | { kind: "error"; message: string };

export function Query(): JSX.Element {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const loading = state.kind === "loading";

  async function submitQuestion(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setState({ kind: "loading" });
    try {
      const result = await postQuery({ query: trimmed });
      setState({ kind: "answered", result });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Network error.";
      setState({ kind: "error", message });
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submitQuestion(question);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void submitQuestion(question);
    }
  }

  function onChipClick(text: string): void {
    setQuestion(text);
    void submitQuestion(text);
  }

  return (
    <section aria-labelledby="query-heading">
      <div className="view-head">
        <p className="eyebrow">Retrieval-augmented · citation-grounded</p>
        <h1 id="query-heading" className="view-title">
          Ask a question
        </h1>
        <p className="view-sub">
          Citations are required — Sentinel refuses to answer without them.
        </p>
      </div>

      <form className="card" onSubmit={onSubmit} aria-label="query form">
        <label className="field-label" htmlFor="question">
          Question
        </label>
        <textarea
          id="question"
          aria-label="question"
          placeholder="Ask a question about the synthetic corpus…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={4000}
        />
        <div className="row" style={{ justifyContent: "space-between", marginTop: "var(--sp-3)" }}>
          <span className="muted mono" style={{ fontSize: "var(--text-xs)" }}>
            ⌘↵ to submit
          </span>
          <button type="submit" className="btn primary" disabled={loading || !question.trim()}>
            <Search size={15} aria-hidden />
            {loading ? "Retrieving and generating…" : "Ask"}
          </button>
        </div>
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              onClick={() => onChipClick(s)}
              disabled={loading}
            >
              {s}
            </button>
          ))}
        </div>
      </form>

      <div style={{ marginTop: "var(--sp-4)" }}>
        {state.kind === "idle" && (
          <p className="muted" style={{ textAlign: "center", marginTop: "var(--sp-6)" }}>
            Submit a question to see a cited answer or a deliberate refusal.
          </p>
        )}
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
        <h3 className="result-title">
          <span className="badge rejected">refused</span> Refused
        </h3>
        <p className="answer">{result.answer}</p>
        <div className="cite refusal">
          <div className="cmeta">{result.reason ?? "no_citation"}</div>
          <div className="ctext">
            A refusal is correct behavior, not an error — Sentinel will not answer without a
            grounding citation.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="card" role="status">
      <h3 className="result-title">
        <span className="badge auto_approved">cited</span> Answer
      </h3>
      <p className="answer">{result.answer}</p>
      <div className="section-label">Citations ({result.citations.length})</div>
      {result.citations.length === 0 ? (
        <p className="muted">No citations.</p>
      ) : (
        result.citations.map((c) => (
          <div className="cite" key={c.chunk_id}>
            <div className="cmeta">
              chunk #{c.chunk_id} · doc #{c.document_id} · score {c.score.toFixed(3)}
            </div>
            <div className="ctext">{c.text}</div>
          </div>
        ))
      )}
    </div>
  );
}
