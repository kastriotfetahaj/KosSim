import { useMemo } from "react";
import { admin } from "../../api";
import { Badge } from "../../components/Badge";
import SearchInput from "../../components/SearchInput";
import { useDebounced, usePoll, useQueryParam } from "../../hooks";

export default function Logs() {
  const [q, setQ] = useQueryParam("q");
  const [level, setLevel] = useQueryParam("level");
  const [component, setComponent] = useQueryParam("component");
  const dq = useDebounced(q, 200);
  const params = useMemo(
    () => ({
      q: dq || undefined,
      level: level ? Number(level) : undefined,
      component: component || undefined,
      limit: 400,
    }),
    [dq, level, component],
  );
  const { data, error, loading } = usePoll(
    () => admin.logs(params),
    5000,
    [JSON.stringify(params)],
  );

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Event log</h1>
          <p className="subtitle">War-room timeline</p>
        </div>
      </header>

      <div className="filters">
        <SearchInput value={q} onChange={setQ} placeholder="Search title and body…" />
        <label className="field-inline">
          <span>Min level</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">All</option>
            {data?.levels.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label} ({l.value})
              </option>
            ))}
          </select>
        </label>
        <label className="field-inline">
          <span>Component</span>
          <select value={component} onChange={(e) => setComponent(e.target.value)}>
            <option value="">All</option>
            {data?.components.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="card no-pad">
        <ul className="timeline">
          {data?.rows.map((r, i) => (
            <li key={i}>
              <time>{fmt(r.created_at)}</time>
              <Badge>{r.level_label}</Badge>
              <div>
                <strong>{r.title}</strong>
                <div className="muted small">{r.component}</div>
                {r.text && <div className="log-body">{r.text}</div>}
              </div>
            </li>
          ))}
          {!data?.rows.length && (
            <li className="muted center" style={{ padding: 20 }}>
              {loading ? "Loading…" : "No events"}
            </li>
          )}
        </ul>
      </div>
    </>
  );
}

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}
