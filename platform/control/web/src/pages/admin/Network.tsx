import { admin } from "../../api";
import { usePoll } from "../../hooks";

export default function Network() {
  const { data, error, loading } = usePoll(() => admin.network(), 10000, []);

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Network</h1>
          <p className="subtitle">WireGuard routing artifacts and ACL policy</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => admin.networkSync().then(() => location.reload())}>
            Sync
          </button>
          <a className="btn btn-primary" href={admin.networkExportUrl()}>
            Export bundle
          </a>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {!data && loading && <div className="msg">Loading network state...</div>}
      {data && (
        <>
          <div className="grid grid-4 mb-1">
            <Stat label="Checker CIDR" value={data.settings.checker_cidr ?? "-"} />
            <Stat label="Control CIDR" value={data.settings.control_public_cidr ?? "-"} />
            <Stat label="Router endpoint" value={data.settings.router_endpoint ?? "-"} />
            <Stat label="Teams" value={data.teams.length} />
          </div>

          <div className="grid grid-2">
            <section className="card no-pad">
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Team</th>
                      <th>Network</th>
                      <th>Gateway</th>
                      <th>Vulnbox</th>
                      <th>Player</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.teams.map((team) => (
                      <tr key={team.team_id}>
                        <td>{team.team}</td>
                        <td className="mono">{team.team_cidr}</td>
                        <td className="mono">{team.gateway_ip}</td>
                        <td className="mono">{team.vulnbox_ip}</td>
                        <td className="mono">{team.player_ip}</td>
                      </tr>
                    ))}
                    {!data.teams.length && (
                      <tr>
                        <td colSpan={5} className="muted center">
                          No team networks generated.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="card">
              <div className="card-header">
                <h2>ACL policy</h2>
              </div>
              <ul className="compact-list">
                {data.acl_policy.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card stat-card">
      <div className="stat stat-tight">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
