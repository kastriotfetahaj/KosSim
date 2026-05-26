import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { admin, type TimerSnapshot } from "../api";

export default function GameStatusBar() {
  const [timer, setTimer] = useState<TimerSnapshot | null>(null);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const t = await admin.game();
        if (!cancelled) setTimer(t);
      } catch {
        /* swallow — banner just stays empty */
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    const id = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  if (!timer) return null;

  const stateClass = `state-${timer.state.toLowerCase()}`;
  const isRunning = timer.state === "RUNNING";
  const startsIn =
    timer.start_at && timer.start_at > now && !isRunning
      ? timer.start_at - now
      : null;

  return (
    <div className={`status-bar ${stateClass}`}>
      <span className={`pill ${stateClass}`}>{timer.state}</span>
      {isRunning && (
        <>
          <span className="status-item">Tick <strong>{timer.current_tick}</strong></span>
          <span className="status-item">
            Next in <strong>{fmtDur(timer.seconds_to_next_tick)}</strong>
          </span>
        </>
      )}
      {startsIn !== null && (
        <span className="status-item">
          Starts in <strong>{fmtCountdown(startsIn)}</strong>
        </span>
      )}
      {timer.desired_state !== timer.state && (
        <span className="status-item muted">
          → desired {timer.desired_state}
        </span>
      )}
      <span className="status-spacer" />
      <Link className="status-link" to="/admin/game">Game control →</Link>
    </div>
  );
}

function fmtDur(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function fmtCountdown(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  if (h > 0) return `${pad(h)}:${pad(m)}:${pad(s)}`;
  return `${pad(m)}:${pad(s)}`;
}
