import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { VolumeResponse } from "../../api";

export function VolumeChart({ data }: { data: VolumeResponse }): JSX.Element {
  return (
    <div className="chart-card" aria-label="extraction volume over time">
      <h3>Volume — last {data.days} days</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.points} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" />
          <YAxis allowDecimals={false} width={28} />
          <Tooltip />
          <Bar dataKey="count" fill="#2a5db0" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
