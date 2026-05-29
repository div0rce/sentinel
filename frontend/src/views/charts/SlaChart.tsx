import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SlaResponse } from "../../api";

export function SlaChart({ data }: { data: SlaResponse }): JSX.Element {
  return (
    <div className="chart-card" aria-label="sla risk for needs review">
      <h3>
        SLA risk{" "}
        <span className="muted">
          (threshold {data.threshold_hours}h, {data.over_sla} of{" "}
          {data.total_needs_review} over)
        </span>
      </h3>
      {data.total_needs_review === 0 ? (
        <p className="muted">No items awaiting review.</p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data.buckets} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="label" />
            <YAxis allowDecimals={false} width={28} />
            <Tooltip />
            <Bar dataKey="count" fill="#b3261e" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
