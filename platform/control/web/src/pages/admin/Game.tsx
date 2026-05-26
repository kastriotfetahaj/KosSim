import { useEffect, useState } from "react";
import { admin, type TimerSnapshot } from "../../api";
import { usePoll } from "../../hooks";

export default function Game() {
  const { data, error, refresh } = usePoll(() => admin.game(), 3000, []);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const act = async (
    fn: () => Promise<TimerSnapshot>,
    label: string,
  ) => {
    setBusy(true);
    try {
      await fn();
      setNotice(label);
      refresh();
    } catch (e: unknown) {
      setNotice(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  if (error && !data) return <div className="msg error">{error}</div>;
  if (!data) return <div className="msg">Loading…</div>;

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Game control</h1>
          <p className="subtitle">
            State <strong>{data.state}</strong> · desired <strong>{data.desired_state}</strong>
          </p>
        </div>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      <div className="grid grid-4 mb-1">
        <Stat value={data.current_tick} label="Tick" />
        <Stat value={`${data.seconds_to_next_tick}s`} label="Next tick" />
        <Stat value={`${data.rotation_seconds}s`} label="Rotation" />
        <Stat value={data.scoreboard_freeze_tick ?? "—"} label="Freeze tick" />
      </div>

      <div className="grid grid-2">
        <section className="card">
          <h2>Actions</h2>
          <div className="actions-row">
            <button
              className="btn btn-success"
              disabled={busy}
              onClick={() => act(admin.gameStart, "Start requested")}
            >
              Start
            </button>
            <button
              className="btn btn-warning"
              disabled={busy}
              onClick={() => act(admin.gamePause, "Pause after current tick")}
            >
              Pause
            </button>
            <button
              className="btn btn-danger"
              disabled={busy}
              onClick={() => {
                if (confirm("Stop the game now?")) act(admin.gameStop, "Stopped");
              }}
            >
              Stop
            </button>
          </div>
        </section>

        <ScheduleForm timer={data} onSaved={(msg) => { setNotice(msg); refresh(); }} />
      </div>
    </>
  );
}

function ScheduleForm({
  timer,
  onSaved,
}: {
  timer: TimerSnapshot;
  onSaved: (msg: string) => void;
}) {
  const [start, setStart] = useState<string>(unixToLocalInput(timer.start_at));
  const [stopT, setStopT] = useState<string>(timer.stop_after_tick?.toString() ?? "");
  const [freeze, setFreeze] = useState<string>(timer.scoreboard_freeze_tick?.toString() ?? "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setStart(unixToLocalInput(timer.start_at));
    setStopT(timer.stop_after_tick?.toString() ?? "");
    setFreeze(timer.scoreboard_freeze_tick?.toString() ?? "");
  }, [timer.start_at, timer.stop_after_tick, timer.scoreboard_freeze_tick]);

  const parse = (s: string): number | null => {
    const t = s.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await admin.gameSchedule({
        start_at: localInputToUnix(start),
        stop_after_tick: parse(stopT),
        scoreboard_freeze_tick: parse(freeze),
      });
      onSaved("Schedule saved");
    } catch (e: unknown) {
      onSaved(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Schedule</h2>
      <form onSubmit={submit}>
        <label className="field">
          <span>Start at</span>
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <small className="field-hint">
            {start
              ? `Local time · ${localInputToUnix(start)} (unix ts)`
              : "Leave empty to clear the scheduled start."}
          </small>
        </label>
        <label className="field">
          <span>Stop after tick</span>
          <input type="number" value={stopT} onChange={(e) => setStopT(e.target.value)} />
        </label>
        <label className="field">
          <span>Scoreboard freeze tick</span>
          <input type="number" value={freeze} onChange={(e) => setFreeze(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Saving…" : "Save schedule"}
        </button>
      </form>
    </section>
  );
}

// The API stores `start_at` as a unix timestamp in seconds. The
// <input type="datetime-local"> works with a local "YYYY-MM-DDTHH:mm"
// string, so convert between the two at the form boundary.
function unixToLocalInput(secs: number | null | undefined): string {
  if (secs == null) return "";
  const d = new Date(secs * 1000);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function localInputToUnix(value: string): number | null {
  const t = value.trim();
  if (!t) return null;
  const ms = new Date(t).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="card stat-card">
      <div className="stat">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
