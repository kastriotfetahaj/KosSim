import { admin } from "../../api";
import { Donut, StackedBars } from "../../components/Charts";
import { usePoll } from "../../hooks";

export default function Dashboard() {
  const { data, error } = usePoll(() => admin.dashboard(), 5000, []);
  const { data: obs } = usePoll(() => admin.observability({ ticks: 30 }), 5000, []);
  if (error) return <div className="msg error">{error}</div>;
  if (!data) return <div className="msg">Loading…</div>;
  const t = data.summary.timer;
  const health = obs?.operational_health;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="subtitle">
            Game <strong>{t.state}</strong> · tick {t.current_tick}
          </p>
        </div>
      </header>

      <div className="grid grid-4 mb-1">
        <Stat value={t.current_tick} label="Current tick" />
        <Stat value={`${t.seconds_to_next_tick}s`} label="Next tick in" />
        <Stat value={data.summary.accepted_submissions} label="Flags accepted" />
        <Stat
          value={data.summary.bad_checkers}
          label="Checker issues this tick"
          tone={data.summary.bad_checkers > 0 ? "warn" : undefined}
        />
      </div>

      {health && (
        <section className={`card readiness-card readiness-${health.readiness} mb-1`}>
          <div>
            <h2>Operator readiness</h2>
            <p className="subtitle">
              DB <strong>{health.database}</strong> · Redis <strong>{health.redis}</strong> ·{" "}
              {health.worker_count} workers · {health.queue_total ?? "unknown"} queued
            </p>
          </div>
          <div className="readiness-metrics">
            <MiniStat label="Overdue jobs" value={health.overdue_jobs} />
            <MiniStat label="Crashed jobs" value={health.crashed_jobs} />
            <MiniStat label="Stale boxes" value={health.stale_vulnboxes} />
            <MiniStat label="Alerts" value={obs?.alerts.length ?? 0} />
          </div>
        </section>
      )}

      <section className="card export-panel mb-1">
        <div>
          <h2>Exports</h2>
          <p className="subtitle">
            Download the datasets operators usually need after an incident,
            appeal, or scoreboard review.
          </p>
        </div>
        <div className="export-actions">
          <a className="btn btn-ghost btn-xs" href={admin.scoreboardExportUrl()} download>
            Scoreboard JSON
          </a>
          <a className="btn btn-ghost btn-xs" href={admin.submissionsExportUrl()} download>
            Submissions CSV
          </a>
          <a className="btn btn-ghost btn-xs" href={admin.checkerFailuresExportUrl()} download>
            Checker failures CSV
          </a>
          <a className="btn btn-ghost btn-xs" href={admin.logsExportUrl()} download>
            Audit log CSV
          </a>
        </div>
      </section>

      <div className="grid grid-2">
        <section className="card">
          <h2>Submissions by tick</h2>
          <StackedBars data={data.submissions_chart} />
        </section>
        <section className="card">
          <h2>Checker status · tick {t.current_tick}</h2>
          <Donut data={data.checkers_chart} />
        </section>
      </div>
    </>
  );
}

function MiniStat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="mini-stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function Stat({
  value,
  label,
  tone,
}: {
  value: number | string;
  label: string;
  tone?: "warn" | "ok";
}) {
  return (
    <div className={`card stat-card ${tone ?? ""}`}>
      <div className="stat">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
