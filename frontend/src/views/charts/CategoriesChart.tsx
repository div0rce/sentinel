import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CategoryResponse } from "../../api";
import {
  ACCENT,
  AXIS_STROKE,
  AXIS_TICK,
  GRID_STROKE,
  TOOLTIP_CONTENT_STYLE,
  TOOLTIP_CURSOR,
  TOOLTIP_ITEM_STYLE,
  TOOLTIP_LABEL_STYLE,
} from "./chartTheme";

export function CategoriesChart({ data }: { data: CategoryResponse }): JSX.Element {
  if (data.points.length === 0) {
    return (
      <div className="chart-card">
        <h3>Extraction categories</h3>
        <p className="muted">No extractions yet.</p>
      </div>
    );
  }
  return (
    <div className="chart-card" aria-label="categories breakdown">
      <h3>
        Extraction categories <span className="sub">(by schema)</span>
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart
          data={data.points}
          layout="vertical"
          margin={{ top: 8, right: 12, left: 12, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="2 4" horizontal={false} stroke={GRID_STROKE} />
          <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <YAxis
            type="category"
            dataKey="schema_name"
            width={110}
            tick={AXIS_TICK}
            stroke={AXIS_STROKE}
          />
          <Tooltip
            contentStyle={TOOLTIP_CONTENT_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            cursor={TOOLTIP_CURSOR}
          />
          <Bar dataKey="count" fill={ACCENT} radius={[0, 1, 1, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
