import { useMemo, useState } from "react";
import { admin, type SubmissionRow } from "../../api";
import { Badge } from "../../components/Badge";
import { StackedBars } from "../../components/Charts";
import CopyButton from "../../components/CopyButton";
import SearchInput from "../../components/SearchInput";
import { useDebounced, usePoll, useQueryParam } from "../../hooks";

const RESULTS = ["accepted", "duplicate", "expired", "invalid", "own_flag"];

export default function Submissions() {
  const [q, setQ] = useQueryParam("q");
  const [result, setResult] = useQueryParam("result");
  const [team, setTeam] = useQueryParam("team");
  const dq = useDebounced(q, 200);
  const params = useMemo(
    () => ({ q: dq, result, team, limit: 300 }),
    [dq, result, team],
  );
  const { data, error, loading } = usePoll(
    () => admin.submissions(params),
    5000,
    [JSON.stringify(params)],
  );

  // Counts by result for quick glance
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of data?.rows ?? []) c[r.result] = (c[r.result] ?? 0) + 1;
    return c;
  }, [data]);

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Submissions</h1>
          <p className="subtitle">All flag submit attempts</p>
        </div>
        <div className="chip-row">
          {RESULTS.map((r) => (
            <button
              key={r}
              className={`chip ${result === r ? "active" : ""}`}
              onClick={() => setResult(result === r ? "" : r)}
            >
              {r} <em>{counts[r] ?? 0}</em>
            </button>
          ))}
        </div>
      </header>

      <section className="card mb-1">
        <h2>By tick</h2>
        {data && <StackedBars data={data.chart} />}
      </section>

      <div className="filters">
        <SearchInput value={q} onChange={setQ} placeholder="Search submitter, target, service, flag…" />
        <label className="field-inline">
          <span>Submitter</span>
          <input value={team} onChange={(e) => setTeam(e.target.value)} placeholder="team name" />
        </label>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="card no-pad">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th style={{ width: 24 }}></th>
                <th>Time</th>
                <th>Submitter</th>
                <th>Target</th>
                <th>Service</th>
                <th>Result</th>
                <th>Tick</th>
                <th>FB</th>
                <th>+pts</th>
                <th>Flag</th>
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r, i) => (
                <SubmissionRowView key={i} row={r} />
              ))}
              {!data?.rows.length && (
                <tr>
                  <td colSpan={10} className="muted center">
                    {loading ? "Loading…" : "No submissions"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function SubmissionRowView({ row }: { row: SubmissionRow }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className={row.is_firstblood ? "row-firstblood" : ""}>
        <td>
          <button className="row-toggle" onClick={() => setOpen((o) => !o)}>
            {open ? "▾" : "▸"}
          </button>
        </td>
        <td className="muted">{fmtTime(row.submitted_at)}</td>
        <td>{row.submitter}</td>
        <td>{row.target ?? "—"}</td>
        <td>{row.service ?? "—"}</td>
        <td><Badge>{row.result}</Badge></td>
        <td className="num">{row.tick_issued ?? "—"}</td>
        <td>{row.is_firstblood ? "★" : ""}</td>
        <td className="num">{row.points_awarded ? fmtPoints(row.points_awarded) : "—"}</td>
        <td>
          <code className="mono truncate" title={row.flag_short}>
            {row.flag_short}
          </code>
        </td>
      </tr>
      {open && (
        <tr className="row-expand">
          <td></td>
          <td colSpan={9}>
            <div className="expand-grid">
              <div>
                <div className="ex-label">Full timestamp</div>
                <div className="mono">{row.submitted_at ?? "—"}</div>
              </div>
              <div>
                <div className="ex-label">Flag</div>
                <div className="flag-cell">
                  <code className="mono">{row.flag_short}</code>
                  <CopyButton text={row.flag_short} label="flag" />
                </div>
              </div>
              <div>
                <div className="ex-label">Points awarded</div>
                <div className="mono">{row.points_awarded}</div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString();
}

function fmtPoints(n: number): string {
  return Number(n.toFixed(2)).toString();
}
