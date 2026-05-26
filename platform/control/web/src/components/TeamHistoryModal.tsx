import { useEffect, useState } from "react";
import {
  fetchTeamHistory,
  type ScoreboardRow,
  type TeamHistoryResponse,
} from "../api";
import { ShieldIcon, SwordIcon, TrophyIcon, WrenchIcon } from "./Icons";

function flagEmoji(cc: string): string {
  const code = (cc || "").trim().toUpperCase();
  if (code.length !== 2 || !/^[A-Z]{2}$/.test(code)) return "🏳";
  const base = 0x1f1e6 - "A".charCodeAt(0);
  return String.fromCodePoint(base + code.charCodeAt(0), base + code.charCodeAt(1));
}

function fmt(n: number): string {
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString();
  return Number(n.toFixed(2)).toString();
}

function Delta({ value }: { value: number }) {
  if (!value) return null;
  const cls = value > 0 ? "th-up" : "th-down";
  return (
    <span className={cls}>
      {value > 0 ? "+" : ""}
      {fmt(value)}
    </span>
  );
}

export default function TeamHistoryModal({
  team,
  onClose,
}: {
  team: ScoreboardRow | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<TeamHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!team) return;
    let cancelled = false;
    setLoading(true);
    setData(null);
    setError(null);
    fetchTeamHistory(team.team_id, 60)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [team]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!team) return null;

  return (
    <div
      className="th-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="th-panel" role="dialog" aria-labelledby="th-title">
        <header className="th-header">
          <div className="th-title-row">
            <span className="th-flag" title={team.country_code}>
              {flagEmoji(team.country_code)}
            </span>
            <div>
              <h2 id="th-title">{team.team_name}</h2>
              <p className="th-sub">
                Rank #{team.rank} · {fmt(team.total)} pts
                {team.nat_alias ? (
                  <>
                    {" · "}
                    <code className="mono">{team.nat_alias}</code>
                  </>
                ) : null}
              </p>
            </div>
          </div>
          <div className="th-actions">
            <button className="th-close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
        </header>

        {loading && <div className="th-msg">Loading history…</div>}
        {error && <div className="th-msg th-error">Error: {error}</div>}
        {!loading && !error && data && data.ticks.length === 0 && (
          <div className="th-msg">No tick history recorded yet.</div>
        )}

        {data && data.ticks.length > 0 && (
          <div className="th-scroll">
            <table className="th-table">
              <thead>
                <tr>
                  <th className="th-rank">Tick</th>
                  <th>
                    <TrophyIcon size={11} /> Score
                  </th>
                  <th>
                    <SwordIcon size={11} /> Attack
                  </th>
                  <th>
                    <ShieldIcon size={11} /> Defense
                  </th>
                  <th>
                    <WrenchIcon size={11} /> SLA
                  </th>
                  <th title="Flags captured this tick">★ Caps</th>
                </tr>
              </thead>
              <tbody>
                {data.ticks.map((t) => {
                  const serviceCount = Math.max(data.services.length, 1);
                  const slaPct = (t.totals.uptime_points / serviceCount) * 100;
                  return (
                    <tr key={t.tick}>
                      <td className="th-rank mono">#{t.tick}</td>
                      <td>
                        <strong>{fmt(t.totals.score)}</strong>{" "}
                        <Delta value={t.totals.score_delta} />
                      </td>
                      <td>
                        {fmt(t.totals.attack_points)}{" "}
                        <Delta value={t.totals.attack_delta} />
                      </td>
                      <td>
                        {fmt(t.totals.defense_points)}{" "}
                        <Delta value={t.totals.defense_delta} />
                      </td>
                      <td>{slaPct.toFixed(2)}%</td>
                      <td className="th-count gold">
                        +{t.totals.flags_captured_delta}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <footer className="th-footer">
          {data && data.ticks.length > 0 && (
            <span className="th-meta">
              {data.ticks.length} tick{data.ticks.length === 1 ? "" : "s"} ·
              latest first
            </span>
          )}
          <button className="btn btn-ghost btn-xs" onClick={onClose}>
            Close (Esc)
          </button>
        </footer>
      </div>
    </div>
  );
}
