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
import type { SlaResponse } from "../../api";
import {
  AXIS_STROKE,
  AXIS_TICK,
  GRID_STROKE,
  slaColor,
  TOOLTIP_CONTENT_STYLE,
  TOOLTIP_CURSOR,
  TOOLTIP_ITEM_STYLE,
  TOOLTIP_LABEL_STYLE,
} from "./chartTheme";

export function SlaChart({ data }: { data: SlaResponse }): JSX.Element {
  return (
    <div className="chart-card" aria-label="sla risk for needs review">
      <h3>
        SLA risk{" "}
        <span className="sub">
          (threshold {data.threshold_hours}h, {data.over_sla} of {data.total_needs_review} over)
        </span>
      </h3>
      {data.total_needs_review === 0 ? (
        <p className="muted">No items awaiting review.</p>
      ) : (
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
                <Cell key={b.label} fill={slaColor(b.label)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
