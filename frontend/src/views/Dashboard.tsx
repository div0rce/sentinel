import { useEffect, useState } from "react";
import {
  ApiError,
  getCategories,
  getConfidence,
  getSla,
  getVolume,
  type CategoryResponse,
  type ConfidenceResponse,
  type SlaResponse,
  type VolumeResponse,
} from "../api";
import { CategoriesChart } from "./charts/CategoriesChart";
import { ConfidenceChart } from "./charts/ConfidenceChart";
import { SlaChart } from "./charts/SlaChart";
import { VolumeChart } from "./charts/VolumeChart";

interface Loaded {
  volume: VolumeResponse;
  categories: CategoryResponse;
  confidence: ConfidenceResponse;
  sla: SlaResponse;
}

type State =
  | { kind: "loading" }
  | { kind: "loaded"; data: Loaded }
  | { kind: "error"; message: string };

export function Dashboard(): JSX.Element {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [volume, categories, confidence, sla] = await Promise.all([
          getVolume(30),
          getCategories(),
          getConfidence(),
          getSla(24),
        ]);
        if (!cancelled) {
          setState({ kind: "loaded", data: { volume, categories, confidence, sla } });
        }
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Network error.";
        setState({ kind: "error", message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return (
      <section aria-labelledby="dash-heading">
        <h2 id="dash-heading">Dashboard</h2>
        <p className="muted">Loading metrics…</p>
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section aria-labelledby="dash-heading">
        <h2 id="dash-heading">Dashboard</h2>
        <div className="error" role="alert">
          {state.message}
        </div>
      </section>
    );
  }
  return (
    <section aria-labelledby="dash-heading">
      <h2 id="dash-heading">Dashboard</h2>
      <div className="charts">
        <VolumeChart data={state.data.volume} />
        <CategoriesChart data={state.data.categories} />
        <ConfidenceChart data={state.data.confidence} />
        <SlaChart data={state.data.sla} />
      </div>
    </section>
  );
}
