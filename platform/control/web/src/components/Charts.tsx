import type { ChartData } from "../api";

// Lightweight SVG charts — no external dependency.

export function StackedBars({ data, height = 220 }: { data: ChartData; height?: number }) {
  const totalsByCol = data.labels.map((_, i) =>
    data.datasets.reduce((s, d) => s + (d.data[i] ?? 0), 0),
  );
  const max = Math.max(1, ...totalsByCol);
  const w = 100 / Math.max(1, data.labels.length);
  return (
    <div className="chart">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" width="100%" height={height}>
        {data.labels.map((_, i) => {
          let y = height;
          return data.datasets.map((ds, di) => {
            const v = ds.data[i] ?? 0;
            const h = (v / max) * (height - 20);
            y -= h;
            const color = colorOf(ds, di);
            return (
              <rect
                key={`${i}-${di}`}
                x={i * w + 0.6}
                y={y}
                width={w - 1.2}
                height={h}
                fill={color}
                opacity={v ? 0.95 : 0}
              >
                <title>{`${ds.label ?? ""} · ${data.labels[i]}: ${v}`}</title>
              </rect>
            );
          });
        })}
      </svg>
      <div className="chart-x">
        {data.labels.map((l) => (
          <span key={l}>{l}</span>
        ))}
      </div>
      <div className="chart-legend">
        {data.datasets.map((d, i) => (
          <span key={d.label ?? i}>
            <i style={{ background: colorOf(d, i) }} /> {d.label ?? `series ${i}`}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Donut({ data, size = 180 }: { data: ChartData; size?: number }) {
  const ds = data.datasets[0];
  if (!ds) return null;
  const total = ds.data.reduce((s, v) => s + v, 0) || 1;
  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  let angle = -Math.PI / 2;
  const arcs = ds.data.map((v, i) => {
    const frac = v / total;
    const start = angle;
    angle += frac * 2 * Math.PI;
    const end = angle;
    const large = end - start > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(start);
    const y1 = cy + r * Math.sin(start);
    const x2 = cx + r * Math.cos(end);
    const y2 = cy + r * Math.sin(end);
    const innerR = r * 0.55;
    const ix1 = cx + innerR * Math.cos(end);
    const iy1 = cy + innerR * Math.sin(end);
    const ix2 = cx + innerR * Math.cos(start);
    const iy2 = cy + innerR * Math.sin(start);
    const path = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${ix1} ${iy1} A ${innerR} ${innerR} 0 ${large} 0 ${ix2} ${iy2} Z`;
    const color = colorOf(ds, i);
    return { path, color, label: data.labels[i], value: v };
  });
  return (
    <div className="chart">
      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {arcs.map((a, i) => (
            <path key={i} d={a.path} fill={a.color}>
              <title>{`${a.label}: ${a.value}`}</title>
            </path>
          ))}
          <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize="22" fill="var(--text)" fontWeight={700}>
            {total}
          </text>
        </svg>
        <div className="chart-legend column">
          {arcs.map((a) => (
            <span key={a.label}>
              <i style={{ background: a.color }} /> {a.label}
              <em>{a.value}</em>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function LineChart({
  data,
  height = 240,
  min = 0,
  max: explicitMax,
  suffix = "",
}: {
  data: ChartData;
  height?: number;
  min?: number;
  max?: number;
  suffix?: string;
}) {
  const width = 100;
  const values = data.datasets.flatMap((d) => d.data);
  const max = explicitMax ?? Math.max(min + 1, ...values, 1);
  const span = Math.max(1, max - min);
  const count = Math.max(1, data.labels.length);
  const xFor = (i: number) => (count <= 1 ? width / 2 : (i / (count - 1)) * width);
  const yFor = (v: number) => height - 18 - ((v - min) / span) * (height - 34);
  if (!data.labels.length || !data.datasets.length) {
    return <div className="msg compact">No chart data yet.</div>;
  }
  return (
    <div className="chart line-chart">
      <div className="chart-plot">
        <div className="chart-y">
          <span>{`${formatNumber(max)}${suffix}`}</span>
          <span>{`${formatNumber((max + min) / 2)}${suffix}`}</span>
          <span>{`${formatNumber(min)}${suffix}`}</span>
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" width="100%" height={height}>
        {[0.25, 0.5, 0.75].map((p) => (
          <line
            key={p}
            x1="0"
            x2={width}
            y1={18 + p * (height - 34)}
            y2={18 + p * (height - 34)}
            stroke="var(--border)"
            strokeWidth="0.4"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {data.datasets.map((ds, di) => {
          const color = colorOf(ds, di);
          const points = ds.data.map((v, i) => `${xFor(i)},${yFor(v)}`).join(" ");
          return (
            <g key={ds.label ?? di}>
              <polyline
                points={points}
                fill="none"
                stroke={color}
                strokeWidth="1.8"
                vectorEffect="non-scaling-stroke"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {ds.data.map((v, i) => (
                <circle key={i} cx={xFor(i)} cy={yFor(v)} r="1.4" fill={color}>
                  <title>{`${ds.label ?? "series"} · tick ${data.labels[i]}: ${formatNumber(v)}${suffix}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
        </svg>
      </div>
      <div className="chart-x">
        {sampleLabels(data.labels).map((l) => (
          <span key={l}>{l}</span>
        ))}
      </div>
      <div className="chart-legend">
        {data.datasets.map((d, i) => (
          <span key={d.label ?? i}>
            <i style={{ background: colorOf(d, i) }} /> {d.label ?? `series ${i}`}
          </span>
        ))}
      </div>
    </div>
  );
}

function sampleLabels(labels: string[]): string[] {
  if (labels.length <= 8) return labels;
  const step = Math.ceil(labels.length / 8);
  return labels.filter((_, i) => i % step === 0 || i === labels.length - 1);
}

function formatNumber(n: number): string {
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1);
}

function colorOf(ds: ChartData["datasets"][number], i: number): string {
  if (Array.isArray(ds.backgroundColor)) return ds.backgroundColor[i] ?? "#64748b";
  if (typeof ds.backgroundColor === "string") return ds.backgroundColor;
  const fallback = ["#3b82f6", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#fb923c"];
  return fallback[i % fallback.length];
}
