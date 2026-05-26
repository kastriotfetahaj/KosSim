import { useState } from "react";
import { admin, type VulnboxRow } from "../../api";
import { Badge } from "../../components/Badge";
import { usePoll } from "../../hooks";

const ACTIONS = ["start", "stop", "restart", "reset", "rebuild"];

export default function Vulnboxes() {
  const [busy, setBusy] = useState<string | null>(null);
  const { data, error, loading } = usePoll(() => admin.vulnboxes(), 5000, [busy ?? ""]);

  async function run(row: VulnboxRow, action: string) {
    setBusy(`${row.id}:${action}`);
    try {
      await admin.vulnboxAction(row.id, action);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Vulnboxes</h1>
          <p className="subtitle">Desired state and lifecycle actions</p>
        </div>
        <button className="btn" onClick={() => admin.vulnboxesSync().then(() => location.reload())}>
          Sync
        </button>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {!data && loading && <div className="msg">Loading vulnboxes...</div>}
      {data && (
        <div className="grid grid-2">
          <section className="card no-pad analytics-wide">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Team</th>
                    <th>Backend</th>
                    <th>Desired</th>
                    <th>Observed</th>
                    <th>Host</th>
                    <th>IP</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.team}</td>
                      <td>{row.backend}</td>
                      <td>
                        <Badge>{row.desired_status}</Badge>
                      </td>
                      <td>
                        <Badge>{row.observed_status}</Badge>
                      </td>
                      <td className="mono">{row.host ?? "-"}</td>
                      <td className="mono">{row.ip_address ?? "-"}</td>
                      <td>
                        <div className="button-row">
                          {ACTIONS.map((action) => (
                            <button
                              key={action}
                              className="btn btn-xs"
                              disabled={busy === `${row.id}:${action}`}
                              onClick={() => run(row, action)}
                            >
                              {action}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!data.rows.length && (
                    <tr>
                      <td colSpan={7} className="muted center">
                        No vulnboxes.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card analytics-wide">
            <div className="card-header">
              <h2>Recent events</h2>
            </div>
            <div className="event-list">
              {data.events.map((event, i) => (
                <div className="event-row" key={i}>
                  <time>{event.created_at ? new Date(event.created_at).toLocaleTimeString() : "-"}</time>
                  <strong>{event.team ?? "unknown"}</strong>
                  <Badge>{event.status}</Badge>
                  <span>{event.action}</span>
                  <span className="truncate">{event.message}</span>
                </div>
              ))}
              {!data.events.length && <div className="msg compact">No events yet.</div>}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
