import { useMemo, useState } from "react";
import {
  admin,
  type AnalyticsResponse,
  type AnalyticsServiceActivity,
  type HeatmapCell,
} from "../../api";
import { LineChart } from "../../components/Charts";
import { usePoll } from "../../hooks";

export default function Analytics() {
  const [ticks, setTicks] = useState(60);
  const [top, setTop] = useState(8);
  const { data, error, loading } = usePoll(
    () => admin.analytics({ ticks, top }),
    5000,
    [ticks, top],
  );

  if (error) return <div className="msg error">{error}</div>;
  if (!data && loading) return <div className="msg">Loading analytics...</div>;
  if (!data) return <div className="msg">No analytics data available.</div>;

  const captureCount = data.service_activity.services.reduce(
    (sum, svc) => sum + svc.captures.reduce((s, n) => s + n, 0),
    0,
  );

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Scoreboard Analytics</h1>
          <p className="subtitle">
            Tick {data.tick_range.start || 0} through {data.tick_range.end || 0}
          </p>
        </div>
        <div className="filters inline-filters">
          <label className="field-inline">
            <span>Window</span>
            <select value={ticks} onChange={(e) => setTicks(Number(e.target.value))}>
              <option value={30}>30 ticks</option>
              <option value={60}>60 ticks</option>
              <option value={120}>120 ticks</option>
              <option value={240}>240 ticks</option>
            </select>
          </label>
          <label className="field-inline">
            <span>Teams</span>
            <select value={top} onChange={(e) => setTop(Number(e.target.value))}>
              <option value={5}>Top 5</option>
              <option value={8}>Top 8</option>
              <option value={10}>Top 10</option>
              <option value={15}>Top 15</option>
            </select>
          </label>
        </div>
      </header>

      <div className="grid grid-4 mb-1">
        <Stat value={data.latest_tick} label="Latest scored tick" />
        <Stat value={data.top_teams[0]?.name ?? "-"} label="Leader" />
        <Stat value={captureCount} label="Captures in window" />
        <Stat value={data.first_bloods.length} label="First bloods" />
      </div>

      <div className="grid grid-2">
        <section className="card">
          <div className="card-header">
            <h2>Top team score history</h2>
          </div>
          <LineChart data={data.score_history} height={260} />
        </section>

        <section className="card">
          <div className="card-header">
            <h2>SLA trend by service</h2>
          </div>
          <LineChart data={data.sla_trends} height={260} max={100} suffix="%" />
        </section>

        <section className="card">
          <div className="card-header">
            <h2>Per-service attackers and victims</h2>
          </div>
          <ServiceActivity data={data} />
        </section>

        <section className="card">
          <div className="card-header">
            <h2>Capture heatmap</h2>
          </div>
          <CaptureHeatmap data={data} />
        </section>

        <section className="card analytics-wide">
          <div className="card-header">
            <h2>First-blood timeline</h2>
          </div>
          <FirstBloodTimeline data={data} />
        </section>
      </div>
    </>
  );
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="card stat-card">
      <div className="stat stat-tight">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function ServiceActivity({ data }: { data: AnalyticsResponse }) {
  if (!data.service_activity.services.length) {
    return <div className="msg compact">No service activity yet.</div>;
  }
  return (
    <div className="activity-list">
      {data.service_activity.services.map((svc) => (
        <ServiceActivityRow key={svc.id} svc={svc} labels={data.service_activity.labels} />
      ))}
    </div>
  );
}

function ServiceActivityRow({
  svc,
  labels,
}: {
  svc: AnalyticsServiceActivity;
  labels: string[];
}) {
  const attackers = svc.attackers.reduce((s, n) => s + n, 0);
  const victims = svc.victims.reduce((s, n) => s + n, 0);
  const captures = svc.captures.reduce((s, n) => s + n, 0);
  return (
    <div className="activity-row">
      <div className="activity-meta">
        <strong>{svc.name}</strong>
        <span>{captures} captures</span>
      </div>
      <SparkPair labels={labels} attackers={svc.attackers} victims={svc.victims} />
      <div className="activity-counts">
        <span>
          <i className="dot dot-blue" /> {attackers} attackers
        </span>
        <span>
          <i className="dot dot-green" /> {victims} victims
        </span>
      </div>
    </div>
  );
}

function SparkPair({
  labels,
  attackers,
  victims,
}: {
  labels: string[];
  attackers: number[];
  victims: number[];
}) {
  const max = Math.max(1, ...attackers, ...victims);
  const count = Math.max(1, labels.length);
  const xFor = (i: number) => (count <= 1 ? 50 : (i / (count - 1)) * 100);
  const yFor = (v: number) => 34 - (v / max) * 30;
  const pathFor = (values: number[]) => values.map((v, i) => `${xFor(i)},${yFor(v)}`).join(" ");
  return (
    <svg className="spark-pair" viewBox="0 0 100 38" preserveAspectRatio="none">
      <polyline points={pathFor(attackers)} fill="none" stroke="#6ea8ff" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      <polyline points={pathFor(victims)} fill="none" stroke="#4ade80" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      {labels.map((label, i) => (
        <circle key={label} cx={xFor(i)} cy={yFor(attackers[i] ?? 0)} r="1" fill="#6ea8ff">
          <title>{`tick ${label}: ${attackers[i] ?? 0} attackers, ${victims[i] ?? 0} victims`}</title>
        </circle>
      ))}
    </svg>
  );
}

function CaptureHeatmap({ data }: { data: AnalyticsResponse }) {
  const byKey = useMemo(() => {
    const map = new Map<string, HeatmapCell>();
    for (const cell of data.heatmap.cells) {
      map.set(`${cell.attacker_id}:${cell.victim_id}`, cell);
    }
    return map;
  }, [data.heatmap.cells]);

  if (!data.heatmap.attackers.length || !data.heatmap.victims.length) {
    return <div className="msg compact">No accepted captures in this window.</div>;
  }

  return (
    <div className="heatmap-scroll">
      <table className="heatmap-table">
        <thead>
          <tr>
            <th>Attacker / victim</th>
            {data.heatmap.victims.map((victim) => (
              <th key={victim.id} title={victim.name}>
                {victim.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.heatmap.attackers.map((attacker) => (
            <tr key={attacker.id}>
              <th title={attacker.name}>{attacker.name}</th>
              {data.heatmap.victims.map((victim) => {
                const captures = byKey.get(`${attacker.id}:${victim.id}`)?.captures ?? 0;
                const alpha = data.heatmap.max ? Math.max(0.08, captures / data.heatmap.max) : 0;
                return (
                  <td
                    key={victim.id}
                    style={{
                      background: captures ? `rgba(110, 168, 255, ${alpha})` : "transparent",
                    }}
                    title={`${attacker.name} -> ${victim.name}: ${captures}`}
                  >
                    {captures || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstBloodTimeline({ data }: { data: AnalyticsResponse }) {
  if (!data.first_bloods.length) {
    return <div className="msg compact">No first bloods in this window.</div>;
  }
  return (
    <ol className="firstblood-list">
      {data.first_bloods.map((event) => (
        <li key={event.id}>
          <time>{event.timestamp ? fmtTime(event.timestamp) : "unknown"}</time>
          <strong>{event.attacker}</strong>
          <span>
            captured {event.service ?? "service"} from {event.victim ?? "unknown"} at tick {event.tick ?? "-"}
          </span>
        </li>
      ))}
    </ol>
  );
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
