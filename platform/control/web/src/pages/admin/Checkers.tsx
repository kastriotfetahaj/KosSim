import { useMemo, useState } from "react";
import { admin, type CheckerJobLogs } from "../../api";
import { Badge } from "../../components/Badge";
import SearchInput from "../../components/SearchInput";
import { useDebounced, usePoll, useQueryParam } from "../../hooks";

export default function Checkers() {
  const [logs, setLogs] = useState<CheckerJobLogs | null>(null);
  const [q, setQ] = useQueryParam("q");
  const [tick, setTick] = useQueryParam("tick");
  const [team, setTeam] = useQueryParam("team");
  const [service, setService] = useQueryParam("service");
  const [status, setStatus] = useQueryParam("status");
  const dq = useDebounced(q, 200);
  const params = useMemo(
    () => ({ q: dq, tick, team, service, status, limit: 300 }),
    [dq, tick, team, service, status],
  );
  const { data, error, loading } = usePoll(
    () => admin.checkers(params),
    5000,
    [JSON.stringify(params)],
  );

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Checkers</h1>
          <p className="subtitle">Distributed worker health, attempts, and step logs</p>
        </div>
      </header>

      <div className="filters">
        <SearchInput value={q} onChange={setQ} placeholder="Search team, service, message…" autoFocus />
        <Select label="Tick" value={tick} onChange={setTick} options={(data?.filters.ticks ?? []).map(String)} />
        <Select label="Team" value={team} onChange={setTeam} options={data?.filters.teams ?? []} />
        <Select label="Service" value={service} onChange={setService} options={data?.filters.services ?? []} />
        <Select
          label="Status"
          value={status}
          onChange={setStatus}
          options={["SUCCESS", "RECOVERING", "MUMBLE", "OFFLINE", "CRASHED"]}
        />
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="card no-pad">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Tick</th>
                <th>Team</th>
                <th>Service</th>
                <th>Status</th>
                <th>Message</th>
                <th>Runtime</th>
                <th>Job</th>
                <th>Checked</th>
                <th>Logs</th>
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r, i) => (
                <tr key={i}>
                  <td className="num">{r.tick}</td>
                  <td>{r.team}</td>
                  <td>{r.service}</td>
                  <td>
                    <Badge>{r.status}</Badge>
                  </td>
                  <td className="truncate" title={r.message}>
                    {r.message.slice(0, 200)}
                  </td>
                  <td className="num">{r.runtime_seconds ?? "—"}</td>
                  <td>
                    {r.job_status ? (
                      <span>
                        {r.job_status} · {r.attempts}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="muted">{fmtTime(r.checked_at)}</td>
                  <td>
                    {r.job_id ? (
                      <button
                        className="btn btn-xs"
                        onClick={async () => setLogs(await admin.checkerLogs(r.job_id as number))}
                      >
                        View
                      </button>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {!data?.rows.length && (
                <tr>
                  <td colSpan={9} className="muted center">
                    {loading ? "Loading…" : "No rows"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {logs && (
        <section className="card mt-1">
          <div className="card-header">
            <h2>Checker step logs</h2>
            <button className="btn btn-xs" onClick={() => setLogs(null)}>
              Close
            </button>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Tick</th>
                  <th>Payload</th>
                  <th>Status</th>
                  <th>Runtime</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {logs.rows.map((row, i) => (
                  <tr key={i}>
                    <td>{row.method}</td>
                    <td className="num">{row.related_tick ?? "—"}</td>
                    <td className="num">{row.payload ?? "—"}</td>
                    <td>
                      <Badge>{row.status}</Badge>
                    </td>
                    <td className="num">{row.runtime_seconds ?? "—"}</td>
                    <td className="truncate" title={row.trace ?? row.message}>
                      {row.message.slice(0, 260)}
                    </td>
                  </tr>
                ))}
                {!logs.rows.length && (
                  <tr>
                    <td colSpan={6} className="muted center">
                      No step logs.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="field-inline">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString();
}
