import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CategoryResponse } from "../../api";

export function CategoriesChart({ data }: { data: CategoryResponse }): JSX.Element {
  if (data.points.length === 0) {
    return (
      <div className="chart-card">
        <h3>Categories</h3>
        <p className="muted">No extractions yet.</p>
      </div>
    );
  }
  return (
    <div className="chart-card" aria-label="categories breakdown">
      <h3>Categories</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart
          data={data.points}
          layout="vertical"
          margin={{ top: 8, right: 12, left: 12, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="2 4" horizontal={false} />
          <XAxis type="number" allowDecimals={false} />
          <YAxis type="category" dataKey="schema_name" width={110} />
          <Tooltip />
          <Bar dataKey="count" fill="#1f6f3d" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
