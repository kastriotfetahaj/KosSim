import { admin } from "../../api";
import SearchInput from "../../components/SearchInput";
import { useDebounced, usePoll, useQueryParam } from "../../hooks";

export default function Services() {
  const [q, setQ] = useQueryParam("q");
  const [only, setOnly] = useQueryParam("only");
  const dq = useDebounced(q, 200);
  const { data, error, refresh } = usePoll(
    () =>
      admin.services({
        q: dq || undefined,
        only: only === "on" || only === "off" ? (only as "on" | "off") : undefined,
      }),
    5000,
    [dq, only],
  );

  const toggle = async (id: number, enabled: boolean) => {
    try {
      await admin.servicesToggle(id, enabled);
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Service targets</h1>
          <p className="subtitle">Enable or disable checker targets mid-game</p>
        </div>
      </header>

      <div className="filters">
        <SearchInput value={q} onChange={setQ} placeholder="Filter by team, service, host…" />
        <div className="seg">
          <button className={!only ? "active" : ""} onClick={() => setOnly("")}>All</button>
          <button className={only === "on" ? "active" : ""} onClick={() => setOnly("on")}>Enabled</button>
          <button className={only === "off" ? "active" : ""} onClick={() => setOnly("off")}>Disabled</button>
        </div>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="card no-pad">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Team</th>
                <th>Service</th>
                <th>Target</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.team}</td>
                  <td>{r.service}</td>
                  <td>
                    <code className="mono">
                      {r.host}:{r.port}
                    </code>
                  </td>
                  <td className={r.enabled ? "ok" : "danger"}>
                    {r.enabled ? "ON" : "OFF"}
                  </td>
                  <td className="right">
                    <button
                      className={`btn btn-xs ${r.enabled ? "btn-ghost" : "btn-success"}`}
                      onClick={() => toggle(r.id, !r.enabled)}
                    >
                      {r.enabled ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
              {!data?.rows.length && (
                <tr>
                  <td colSpan={5} className="muted center">
                    No targets
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
