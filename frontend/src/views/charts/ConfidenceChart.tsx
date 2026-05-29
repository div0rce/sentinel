import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ConfidenceResponse } from "../../api";

export function ConfidenceChart({ data }: { data: ConfidenceResponse }): JSX.Element {
  if (data.total_fields === 0) {
    return (
      <div className="chart-card">
        <h3>Confidence distribution</h3>
        <p className="muted">No extracted fields yet.</p>
      </div>
    );
  }
  return (
    <div className="chart-card" aria-label="confidence distribution">
      <h3>
        Confidence distribution{" "}
        <span className="muted">(n={data.total_fields})</span>
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.buckets} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" />
          <YAxis allowDecimals={false} width={28} />
          <Tooltip />
          <Bar dataKey="count" fill="#a86a00" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
