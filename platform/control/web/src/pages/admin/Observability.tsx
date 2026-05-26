import { useMemo, useState } from "react";
import { admin, type ChartData, type ObservabilityResponse } from "../../api";
import { Badge } from "../../components/Badge";
import { LineChart } from "../../components/Charts";
import { usePoll } from "../../hooks";

export default function Observability() {
  const [ticks, setTicks] = useState(60);
  const { data, error, loading } = usePoll(
    () => admin.observability({ ticks }),
    5000,
    [ticks],
  );

  // Hooks must run unconditionally and in a stable order, so compute the
  // memoised chart before any early return below.
  const slaChart = useSlaChart(data);

  if (error) return <div className="msg error">{error}</div>;
  if (!data && loading) return <div className="msg">Loading observability...</div>;
  if (!data) return <div className="msg">No observability data available.</div>;

  const submissions = data.submission_rates.reduce((sum, row) => sum + Number(row.n || 0), 0);
  const failures = data.failed_checks.length;

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Observability</h1>
          <p className="subtitle">
            Tick {data.tick_range.start || 0} through {data.tick_range.end || 0}
          </p>
        </div>
        <label className="field-inline">
          <span>Window</span>
          <select value={ticks} onChange={(e) => setTicks(Number(e.target.value))}>
            <option value={30}>30 ticks</option>
            <option value={60}>60 ticks</option>
            <option value={120}>120 ticks</option>
            <option value={240}>240 ticks</option>
          </select>
        </label>
      </header>

      <div className="grid grid-4 mb-1">
        <Stat label="Latest tick" value={data.latest_tick} />
        <Stat label="Queue depth" value={sumDepth(data.queue_depths)} />
        <Stat label="Submissions" value={submissions} />
        <Stat label="Failed checks" value={failures} />
      </div>

      {data.alerts.length > 0 && (
        <section className="alert-panel mb-1">
          {data.alerts.map((alert) => (
            <div className={`alert ${alert.severity === "danger" ? "alert-danger" : "alert-info"}`} key={alert.title}>
              <strong>{alert.title}</strong>
              <span>{alert.detail}</span>
            </div>
          ))}
        </section>
      )}

      <div className="grid grid-2">
        <section className="card">
          <div className="card-header">
            <h2>Per-service SLA</h2>
          </div>
          <LineChart data={slaChart} height={250} max={100} suffix="%" />
        </section>

        <section className="card">
          <div className="card-header">
            <h2>Runtime histogram</h2>
          </div>
          <Histogram buckets={data.runtime_histogram} />
        </section>

        <section className="card">
          <div className="card-header">
            <h2>Queues and workers</h2>
          </div>
          <QueueWorkers data={data} />
        </section>

        <section className="card">
          <div className="card-header">
            <h2>Checker status</h2>
          </div>
          <StatusList status={data.checker_status} />
        </section>

        <section className="card analytics-wide">
          <div className="card-header">
            <h2>Failed checks</h2>
          </div>
          <FailedChecks data={data} />
        </section>

        <section className="card analytics-wide">
          <div className="card-header">
            <h2>First blood timeline</h2>
          </div>
          <FirstBloods data={data} />
        </section>
      </div>
    </>
  );
}

function useSlaChart(data: ObservabilityResponse | null): ChartData {
  const slaRows = data?.sla_rows;
  return useMemo(() => {
    const rows = slaRows ?? [];
    const labels = Array.from(
      new Set(rows.map((row) => String(row.tick))),
    ).sort((a, b) => Number(a) - Number(b));
    const services = Array.from(new Set(rows.map((row) => row.service)));
    return {
      labels,
      datasets: services.map((service, index) => {
        const byTick = new Map(
          rows
            .filter((row) => row.service === service)
            .map((row) => [String(row.tick), Number(row.sla)]),
        );
        return {
          label: service,
          data: labels.map((label) => byTick.get(label) ?? 0),
          backgroundColor: ["#3b82f6", "#34d399", "#fbbf24", "#f87171", "#a78bfa"][index % 5],
        };
      }),
    };
  }, [slaRows]);
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card stat-card">
      <div className="stat stat-tight">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function sumDepth(depths: Record<string, number | null>): number | string {
  const values = Object.values(depths);
  if (values.some((v) => v === null)) return "unknown";
  let total = 0;
  for (const value of values) total += Number(value ?? 0);
  return total;
}

function Histogram({ buckets }: { buckets: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(buckets));
  return (
    <div className="histogram">
      {Object.entries(buckets).map(([bucket, count]) => (
        <div className="hist-row" key={bucket}>
          <span>{bucket}s</span>
          <div>
            <i style={{ width: `${(count / max) * 100}%` }} />
          </div>
          <strong>{count}</strong>
        </div>
      ))}
    </div>
  );
}

function QueueWorkers({ data }: { data: ObservabilityResponse }) {
  return (
    <div className="kv-list">
      {Object.entries(data.queue_depths).map(([queue, depth]) => (
        <div key={queue}>
          <span>{queue}</span>
          <strong>{depth ?? "unknown"}</strong>
        </div>
      ))}
      {data.workers.map((worker) => (
        <div key={worker.worker_name}>
          <span>{worker.worker_name}</span>
          <strong>{worker.active_jobs} active</strong>
        </div>
      ))}
      {!data.workers.length && <div className="msg compact">No worker heartbeat.</div>}
    </div>
  );
}

function StatusList({ status }: { status: Record<string, number> }) {
  if (!Object.keys(status).length) return <div className="msg compact">No checker jobs yet.</div>;
  return (
    <div className="kv-list">
      {Object.entries(status).map(([key, value]) => (
        <div key={key}>
          <Badge>{key}</Badge>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function FailedChecks({ data }: { data: ObservabilityResponse }) {
  if (!data.failed_checks.length) return <div className="msg compact">No failed checks in the window.</div>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Tick</th>
            <th>Team</th>
            <th>Service</th>
            <th>Status</th>
            <th>Method</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {data.failed_checks.map((row) => (
            <tr key={row.id}>
              <td className="num">{row.tick}</td>
              <td>{row.team}</td>
              <td>{row.service}</td>
              <td>
                <Badge>{row.status}</Badge>
              </td>
              <td>{row.method ?? "-"}</td>
              <td className="truncate" title={row.trace ?? row.message}>
                {row.message.slice(0, 220)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstBloods({ data }: { data: ObservabilityResponse }) {
  if (!data.first_bloods.length) return <div className="msg compact">No first bloods yet.</div>;
  return (
    <ol className="firstblood-list">
      {data.first_bloods.map((event) => (
        <li key={event.id}>
          <time>{event.submitted_at ? new Date(event.submitted_at).toLocaleString() : "-"}</time>
          <strong>{event.attacker}</strong>
          <span>
            captured {event.service ?? "service"} from {event.victim ?? "unknown"} at tick {event.tick ?? "-"}
          </span>
        </li>
      ))}
    </ol>
  );
}
