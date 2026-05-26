import { admin } from "../../api";
import { Donut, StackedBars } from "../../components/Charts";
import { usePoll } from "../../hooks";

export default function Dashboard() {
  const { data, error } = usePoll(() => admin.dashboard(), 5000, []);
  if (error) return <div className="msg error">{error}</div>;
  if (!data) return <div className="msg">Loading…</div>;
  const t = data.summary.timer;
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
