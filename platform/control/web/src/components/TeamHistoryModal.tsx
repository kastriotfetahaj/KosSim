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

  const serviceRows = Object.values(team.service_cells).sort(
    (a, b) => b.service_total - a.service_total,
  );
  const avgSla = serviceRows.length
    ? serviceRows.reduce((sum, svc) => sum + svc.sla_pct, 0) / serviceRows.length
    : 0;

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

        <section className="th-summary-grid" aria-label="Team summary">
          <SummaryTile
            icon={<TrophyIcon size={15} />}
            label="Total"
            value={fmt(team.total)}
            delta={<Delta value={team.total_delta} />}
          />
          <SummaryTile
            icon={<SwordIcon size={15} />}
            label="Attack"
            value={fmt(team.totals.attack_points)}
            detail={`${team.totals.flags_captured} captures`}
          />
          <SummaryTile
            icon={<ShieldIcon size={15} />}
            label="Defense"
            value={fmt(team.totals.defense_points)}
            detail={`${team.totals.victims_count} victims`}
          />
          <SummaryTile
            icon={<WrenchIcon size={15} />}
            label="Average SLA"
            value={`${avgSla.toFixed(2)}%`}
            detail={`${serviceRows.filter((svc) => svc.is_up).length}/${serviceRows.length} up`}
          />
        </section>

        <section className="th-service-breakdown">
          <div className="th-section-title">
            <h3>Service breakdown</h3>
            <span>(attack + defense) x SLA</span>
          </div>
          <div className="th-service-grid">
            {serviceRows.map((svc) => (
              <div
                key={svc.service_name}
                className={`th-service-card ${svc.is_up ? "up" : "down"}`}
              >
                <div className="th-service-card-head">
                  <strong>{svc.service_display_name || svc.service_name}</strong>
                  <span>{fmt(svc.service_total)}</span>
                </div>
                <div className="th-service-card-meta">
                  <span>
                    <SwordIcon size={11} /> {fmt(svc.attack_points)}
                  </span>
                  <span>
                    <ShieldIcon size={11} /> {fmt(svc.defense_points)}
                  </span>
                  <span>
                    <WrenchIcon size={11} /> {svc.sla_pct.toFixed(1)}%
                  </span>
                </div>
                <div className="th-service-card-meta muted">
                  <span>{svc.attackers_count} attackers</span>
                  <span>{svc.victims_count} victims</span>
                  <span>{svc.checker_status}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

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

function SummaryTile({
  icon,
  label,
  value,
  delta,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  delta?: React.ReactNode;
  detail?: string;
}) {
  return (
    <div className="th-summary-tile">
      <span className="th-summary-icon">{icon}</span>
      <span className="th-summary-label">{label}</span>
      <strong>
        {value} {delta}
      </strong>
      {detail && <span className="th-summary-detail">{detail}</span>}
    </div>
  );
}
