import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { VolumeResponse } from "../../api";
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

export function VolumeChart({ data }: { data: VolumeResponse }): JSX.Element {
  return (
    <div className="chart-card" aria-label="extraction volume over time">
      <h3>
        Ingestion volume <span className="sub">(docs / day, last {data.days} days)</span>
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.points} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={GRID_STROKE} />
          <XAxis
            dataKey="date"
            tickFormatter={(d: string) => d.slice(5)}
            interval="preserveStartEnd"
            tick={AXIS_TICK}
            stroke={AXIS_STROKE}
          />
          <YAxis allowDecimals={false} width={28} tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <Tooltip
            contentStyle={TOOLTIP_CONTENT_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            cursor={TOOLTIP_CURSOR}
          />
          <Bar dataKey="count" fill={ACCENT} radius={[1, 1, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
