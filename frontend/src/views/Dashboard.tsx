import { useEffect, useState } from "react";
import {
  ApiError,
  getCategories,
  getConfidence,
  getKpis,
  getSla,
  getVolume,
  type CategoryResponse,
  type ConfidenceResponse,
  type KpiResponse,
  type SlaResponse,
  type VolumeResponse,
} from "../api";
import { CategoriesChart } from "./charts/CategoriesChart";
import { ConfidenceChart } from "./charts/ConfidenceChart";
import { SlaChart } from "./charts/SlaChart";
import { VolumeChart } from "./charts/VolumeChart";

interface Loaded {
  kpis: KpiResponse;
  volume: VolumeResponse;
  categories: CategoryResponse;
  confidence: ConfidenceResponse;
  sla: SlaResponse;
}

type State =
  | { kind: "loading" }
  | { kind: "loaded"; data: Loaded }
  | { kind: "error"; message: string };

function formatGeneratedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function Dashboard(): JSX.Element {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [kpis, volume, categories, confidence, sla] = await Promise.all([
          getKpis(24),
          getVolume(30),
          getCategories(),
          getConfidence(),
          getSla(24),
        ]);
        if (!cancelled) {
          setState({ kind: "loaded", data: { kpis, volume, categories, confidence, sla } });
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

  return (
    <section aria-labelledby="dash-heading">
      <div className="view-head">
        <p className="eyebrow">Operational overview</p>
        <h1 id="dash-heading" className="view-title">
          Dashboard
        </h1>
        <p className="view-sub">
          Ingestion, extraction mix, confidence and SLA health across the governed pipeline.
        </p>
      </div>
      {state.kind === "loading" && <p className="muted">Loading metrics…</p>}
      {state.kind === "error" && (
        <div className="error" role="alert">
          {state.message}
        </div>
      )}
      {state.kind === "loaded" && <DashboardBody data={state.data} />}
    </section>
  );
}

function DashboardBody({ data }: { data: Loaded }): JSX.Element {
  return (
    <>
      <div className="kpis">
        {data.kpis.kpis.map((k) => (
          <div className="kpi" key={k.key}>
            <div className="klabel">{k.label}</div>
            <div className="kval">{k.display}</div>
            {k.delta_display && <div className={`kdelta ${k.direction}`}>{k.delta_display}</div>}
          </div>
        ))}
      </div>
      <div className="charts">
        <VolumeChart data={data.volume} />
        <CategoriesChart data={data.categories} />
        <ConfidenceChart data={data.confidence} />
        <SlaChart data={data.sla} />
      </div>
      <p className="footnote">
        All figures synthetic · derived from the data/sample corpus · refreshed{" "}
        {formatGeneratedAt(data.kpis.generated_at)}
      </p>
    </>
  );
}
