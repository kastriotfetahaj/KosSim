import { useEffect, useState } from "react";
import {
  fetchScoreboard,
  type ScoreboardResponse,
  type ScoreboardRow,
  type Service,
} from "../api";
import {
  BoltIcon,
  FlagInIcon,
  FlagOutIcon,
  ShieldIcon,
  StarIcon,
  SwordIcon,
  TargetIcon,
  TrophyIcon,
  WrenchIcon,
} from "../components/Icons";
import TeamHistoryModal from "../components/TeamHistoryModal";

type Variant = "internal" | "public";

const REFRESH_MS = 5000;

export default function Scoreboard({ variant }: { variant: Variant }) {
  const [data, setData] = useState<ScoreboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const [refreshing, setRefreshing] = useState(false);
  const [drilldown, setDrilldown] = useState<ScoreboardRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setRefreshing(true);
      try {
        const res = await fetchScoreboard({
          includeNop: variant === "internal",
          public: variant === "public",
        });
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setRefreshing(false);
      }
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [variant]);

  useEffect(() => {
    const id = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  if (error && !data) return <div className="msg error">Error: {error}</div>;
  if (!data) return <div className="msg">Loading scoreboard…</div>;

  const secondsLeft = Math.max(0, data.next_tick_at_epoch - now);
  const leader = data.rows[0];
  const title =
    variant === "public"
      ? data.frozen
        ? `KosSim Scoreboard (frozen @ tick ${data.freeze_tick})`
        : "KosSim Scoreboard"
      : "KosSim Scoreboard (internal)";

  const anyServiceActivity = Object.values(data.service_tops).some(Boolean);
  const showServiceTops = data.game_state === "RUNNING" || anyServiceActivity;

  return (
    <div className="scoreboard">
      <header className="sb-top">
        <div className="sb-title">
          <div className="sb-logo">
            <img src="/static/kct-logo.png" alt="Kosova Cyber Team" />
          </div>
          <div>
            <h1>{title}</h1>
            <p className="sb-subtitle">
              Kosova Cyber Team Attack/Defense ·{" "}
              <span className="muted">Updated {fmtFullTime(data.generated_at)}</span>
              <span className={`live-dot ${refreshing ? "live" : ""}`} />
            </p>
          </div>
        </div>
        <div className="sb-meta">
          <Metric label="Round" value={data.round_id} />
          <Metric label="Next tick" value={`${secondsLeft}s`} />
          <Metric
            label="Leader"
            value={
              leader ? (
                <span>
                  <span
                    className="flag-mini"
                    title={leader.country_code.toUpperCase()}
                  >
                    <span aria-hidden>{flagEmoji(leader.country_code)}</span>
                  </span>{" "}
                  <strong>{leader.team_name}</strong> · {fmtPoints(leader.total)}
                </span>
              ) : (
                "—"
              )
            }
          />
          <Metric label="Teams" value={data.rows.length} />
        </div>
      </header>

      <GameStateBanner data={data} now={now} />

      <div className="card no-pad sb-table-wrap">
        <table className="sb-table">
          <thead>
            {showServiceTops && (
              <tr className="sb-thead-top">
                <th colSpan={3} className="sb-thead-spacer" />
                {data.services.map((svc) => {
                  const top = data.service_tops[svc.id];
                  const firstBlood = top?.first_blood;
                  return (
                    <th key={svc.id} className="sb-svc-top">
                      {top ? (
                        <>
                          <div className="sb-svc-leader">
                            <span
                              className="flag-mini"
                              title={top.country_code.toUpperCase()}
                            >
                              <span aria-hidden>
                                {flagEmoji(top.country_code)}
                              </span>
                            </span>
                            <strong>{top.team_name}</strong>
                            <span className="sb-svc-leader-pts">
                              {fmtPoints(top.service_total)}
                              <span className="svc-score-unit">pts</span>
                            </span>
                          </div>
                          <div className="sb-svc-stats">
                            {firstBlood && (
                              <span className="sb-svc-firstblood">
                                <StarIcon size={11} /> first blood:{" "}
                                {firstBlood.attacker_team}
                                {firstBlood.victim_team
                                  ? ` -> ${firstBlood.victim_team}`
                                  : ""}
                              </span>
                            )}
                            <span>
                              <SwordIcon size={11} /> {top.attackers_count}{" "}
                              attackers
                            </span>
                            <span className="sb-svc-divider">·</span>
                            <span>
                              <TargetIcon size={11} /> {top.victims_count}{" "}
                              victims
                            </span>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="sb-svc-leader muted">
                            <span className="flag-mini">—</span>
                            <strong>No leader yet</strong>
                          </div>
                          <div className="sb-svc-stats muted">
                            Awaiting first capture
                          </div>
                        </>
                      )}
                    </th>
                  );
                })}
              </tr>
            )}
            <tr className="sb-thead-main">
              <th className="rank-h">#</th>
              <th>Team</th>
              <th>
                <TrophyIcon size={11} /> Score
              </th>
              {data.services.map((svc) => (
                <th key={svc.id} className="sb-svc-name">
                  <TrophyIcon size={11} /> {serviceLabel(svc)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <TeamRow
                key={row.team_id}
                row={row}
                services={data.services}
                onSelect={() => setDrilldown(row)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <footer className="sb-footer">
        Scoring: service score = (attack + defense) × SLA.
      </footer>
      <TeamHistoryModal team={drilldown} onClose={() => setDrilldown(null)} />
    </div>
  );
}

function TeamRow({
  row,
  services,
  onSelect,
}: {
  row: ScoreboardRow;
  services: Service[];
  onSelect: () => void;
}) {
  return (
    <tr className="team-row" onClick={onSelect} tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); }}}>
      <td className="rank">{row.rank}</td>
      <td className="team-cell">
        <div className="team">
          <span
            className="flag"
            aria-label={row.country_code.toUpperCase()}
            title={row.country_code.toUpperCase()}
          >
            <span className="flag-emoji" aria-hidden>
              {flagEmoji(row.country_code)}
            </span>
            <span className="flag-code" aria-hidden>
              {row.country_code.toUpperCase()}
            </span>
          </span>
          <div className="team-name">
            <div className="team-title-line">
              <strong>{row.team_name}</strong>
              <span className="team-place">#{row.rank}</span>
              {row.totals.flags_captured > 0 && (
                <span className="team-bloods" title="Total captured flags">
                  <StarIcon size={10} /> {row.totals.flags_captured}
                </span>
              )}
            </div>
            {row.nat_alias && (
              <span className="alias-chip" title="Team network alias">
                {row.nat_alias}
              </span>
            )}
          </div>
          <span className="team-chevron" aria-hidden>›</span>
        </div>
      </td>
      <td className="total-cell">
        <strong>{fmtPoints(row.total)}</strong>
        <Delta value={row.total_delta} />
      </td>
      {services.map((svc) => {
        const cell = row.service_cells[svc.id];
        if (!cell) return <td key={svc.id}>—</td>;
        const slaClamped = Math.max(0, Math.min(100, cell.sla_pct));
        const slaTone =
          cell.sla_pct >= 80 ? "ok" : cell.sla_pct >= 50 ? "warn" : "danger";
        return (
          <td key={svc.id} className={`svc-cell ${cell.is_up ? "up" : "down"}`}>
            <div className="svc-stat-stack">
              <ServiceMetricLine
                icon={<TrophyIcon size={12} />}
                label="TOT"
                kind="total"
                value={fmtPoints(cell.service_total)}
                tickPoints={cell.service_delta}
                title="Total service score"
              />
              <ServiceMetricLine
                icon={<SwordIcon size={12} />}
                label="ATK"
                kind="attack"
                value={fmtPoints(cell.attack_points)}
                tickPoints={cell.attack_delta}
                detail={cell.flags_captured ? `(+${cell.flags_captured})` : "—"}
                detailTone={cell.flags_captured ? "ok" : "muted"}
                title="Attack points and captured flags"
              />
              <ServiceMetricLine
                icon={<ShieldIcon size={12} />}
                label="DEF"
                kind="defense"
                value={fmtPoints(cell.defense_points)}
                tickPoints={cell.defense_delta}
                title="Defense points"
              />
              <ServiceMetricLine
                icon={<BoltIcon size={12} />}
                label="SLA"
                kind="sla"
                value={`${cell.sla_pct.toFixed(2)}%`}
                tickPoints={cell.uptime_delta}
                tone={slaTone}
                title="SLA multiplier"
              />
            </div>
            <div className="svc-checks" role="group" aria-label="Checker breakdown">
              <span className={`svc-checks-tool ${cell.is_up ? "ok" : "danger"}`}>
                <WrenchIcon size={11} />
              </span>
              <CheckChip
                label="IN"
                title={`Flag in (PUTFLAG): ${cell.put_status}`}
                status={cell.put_status}
                icon={<FlagInIcon size={11} />}
              />
              <CheckChip
                label="OUT"
                title={`Flag out (GETFLAG): ${cell.get_status}`}
                status={cell.get_status}
                icon={<FlagOutIcon size={11} />}
              />
              <CheckChip
                label="UP"
                title={`Uptime (HAVOC): ${cell.havoc_status}`}
                status={cell.havoc_status}
                icon={<BoltIcon size={11} />}
              />
            </div>
            <div
              className="sla-bar"
              aria-label={`SLA ${cell.sla_pct.toFixed(1)}%`}
            >
              <span
                className={`sla-fill ${slaTone}`}
                style={{ width: `${slaClamped}%` }}
              />
            </div>
          </td>
        );
      })}
    </tr>
  );
}

function ServiceMetricLine({
  icon,
  label,
  kind,
  value,
  tickPoints,
  detail,
  detailTone,
  tone,
  title,
}: {
  icon: React.ReactNode;
  label: string;
  kind: "total" | "attack" | "defense" | "sla";
  value: string;
  tickPoints: number;
  detail?: string;
  detailTone?: "ok" | "danger" | "muted";
  tone?: "ok" | "warn" | "danger" | "muted";
  title: string;
}) {
  return (
    <div className="svc-metric-line" title={title}>
      <span className={`svc-stat-key ${kind}`}>{icon}</span>
      <span className="svc-stat-label">{label}</span>
      <span className={`svc-stat-val ${tone ?? ""}`}>{value}</span>
      <span className={`svc-stat-sub ${detailTone ?? ""}`}>{detail ?? ""}</span>
      <TickPoints value={tickPoints} />
    </div>
  );
}

function GameStateBanner({ data, now }: { data: ScoreboardResponse; now: number }) {
  const { game_state, desired_state, start_at } = data;
  if (game_state === "RUNNING") {
    return (
      <div className="banner banner-ok">
        <div className="banner-dot live" />
        <strong>Game is live</strong>
        <ShieldIcon size={14} />
        <span className="banner-meta">
          Round {data.round_id} · rotation {data.rotation_seconds}s
        </span>
      </div>
    );
  }
  if (game_state === "SUSPENDED" || game_state === "PAUSED") {
    return (
      <div className="banner banner-warn">
        <strong>Game paused</strong>
        <span className="banner-meta">Scoring suspended; checkers idle.</span>
      </div>
    );
  }
  if (start_at && start_at > now) {
    return (
      <div className="banner banner-info">
        <strong>Game starts in</strong>
        <span className="banner-countdown">{fmtCountdown(start_at - now)}</span>
        <span className="banner-meta">
          starts {new Date(start_at * 1000).toLocaleString()}
          {desired_state === "RUNNING" ? " · armed" : ""}
        </span>
      </div>
    );
  }
  if (start_at && start_at <= now && desired_state !== "RUNNING") {
    return (
      <div className="banner banner-muted">
        <strong>Game ended</strong>
        <span className="banner-meta">Final standings.</span>
      </div>
    );
  }
  return (
    <div className="banner banner-muted">
      <strong>Game has not started</strong>
      <span className="banner-meta">Waiting for operator.</span>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
    </div>
  );
}

function CheckChip({
  label,
  title,
  status,
  icon,
}: {
  label: string;
  title: string;
  status: "OK" | "FAIL" | "IDLE";
  icon: React.ReactNode;
}) {
  const tone =
    status === "OK" ? "ok" : status === "FAIL" ? "danger" : "idle";
  return (
    <span className={`check-chip ${tone}`} title={title}>
      <span className="check-chip-icon">{icon}</span>
      <span className="check-chip-label">{label}</span>
      <span className="check-chip-dot" aria-hidden />
    </span>
  );
}

function Delta({ value, compact }: { value: number; compact?: boolean }) {
  if (!value) return null;
  const positive = value > 0;
  return (
    <span className={`delta ${positive ? "up" : "down"} ${compact ? "compact" : ""}`}>
      {positive ? "+" : ""}
      {fmtPoints(value)}
      {positive ? " ↑" : " ↓"}
    </span>
  );
}

function TickPoints({ value }: { value: number }) {
  if (!value) return <span className="tick-points zero">0</span>;
  const positive = value > 0;
  return (
    <span className={`tick-points ${positive ? "up" : "down"}`}>
      {positive ? "+" : ""}
      {fmtPoints(value)}
      {positive ? " ↑" : " ↓"}
    </span>
  );
}

function flagEmoji(cc: string): string {
  const code = (cc || "").trim().toUpperCase();
  if (code.length !== 2 || !/^[A-Z]{2}$/.test(code)) return "🏳";
  const base = 0x1f1e6 - "A".charCodeAt(0);
  return String.fromCodePoint(base + code.charCodeAt(0), base + code.charCodeAt(1));
}

function serviceLabel(service: Service): string {
  return service.display_name || service.name;
}

function fmtPoints(n: number): string {
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString();
  return Number(n.toFixed(2)).toString();
}

function fmtFullTime(iso: string): string {
  const d = new Date(iso);
  return d.toISOString().slice(0, 19).replace("T", " ") + " UTC";
}

function fmtCountdown(sec: number): string {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (d > 0) return `${d}d ${pad(h)}:${pad(m)}:${pad(s)}`;
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}
