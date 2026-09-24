"use client";

/** A minimal inline-SVG line chart — no charting library, per Phase 12's
 * "no Prometheus/Grafana" constraint extending to the dashboard side too:
 * hand-rolled rather than a new dependency for a handful of points.
 */
export function Sparkline({
  values,
  width = 160,
  height = 36,
  color = "#3b82f6",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length === 0) {
    return (
      <svg width={width} height={height} role="img" aria-label="no data">
        <text x={4} y={height / 2} fontSize={10} fill="var(--healer-muted, #888)">
          no data
        </text>
      </svg>
    );
  }

  const max = Math.max(100, ...values);
  const min = 0;
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;

  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const last = values[values.length - 1];

  return (
    <svg width={width} height={height} role="img" aria-label={`recent trend, last value ${last}`}>
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}
