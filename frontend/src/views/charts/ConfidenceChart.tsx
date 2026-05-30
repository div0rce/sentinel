import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ConfidenceResponse } from "../../api";
import {
  AXIS_STROKE,
  AXIS_TICK,
  confidenceColor,
  GRID_STROKE,
  TOOLTIP_CONTENT_STYLE,
  TOOLTIP_CURSOR,
  TOOLTIP_ITEM_STYLE,
  TOOLTIP_LABEL_STYLE,
} from "./chartTheme";

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
        Confidence distribution <span className="sub">(n={data.total_fields})</span>
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.buckets} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={GRID_STROKE} />
          <XAxis dataKey="label" tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <YAxis allowDecimals={false} width={28} tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <Tooltip
            contentStyle={TOOLTIP_CONTENT_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            cursor={TOOLTIP_CURSOR}
          />
          <Bar dataKey="count" radius={[1, 1, 0, 0]}>
            {data.buckets.map((b) => (
              <Cell key={b.label} fill={confidenceColor(b.lower)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
