import { useState } from "react";
import { admin, type TeamRow } from "../../api";
import CopyButton from "../../components/CopyButton";
import { usePoll } from "../../hooks";

type EditDraft = {
  name: string;
  nat_alias: string;
  country_code: string;
  is_nop: boolean;
};

const EMPTY_DRAFT: EditDraft = {
  name: "",
  nat_alias: "",
  country_code: "XK",
  is_nop: false,
};

function flagEmoji(cc: string): string {
  const code = (cc || "").trim().toUpperCase();
  if (code.length !== 2 || !/^[A-Z]{2}$/.test(code)) return "🏳";
  const base = 0x1f1e6 - "A".charCodeAt(0);
  return String.fromCodePoint(base + code.charCodeAt(0), base + code.charCodeAt(1));
}

export default function Teams() {
  const { data, error, refresh } = usePoll(() => admin.teams(), 10000, []);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<EditDraft>(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const startEdit = (t: TeamRow) => {
    setEditing(t.id);
    setDraft({
      name: t.name,
      nat_alias: t.nat_alias,
      country_code: t.country_code,
      is_nop: t.is_nop,
    });
    setMsg(null);
  };

  const startCreate = () => {
    setEditing("new");
    setDraft(EMPTY_DRAFT);
    setMsg(null);
  };

  const cancel = () => {
    setEditing(null);
    setDraft(EMPTY_DRAFT);
    setMsg(null);
  };

  const save = async () => {
    if (!draft.name.trim()) {
      setMsg("Name is required");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      if (editing === "new") {
        await admin.teamCreate({
          name: draft.name.trim(),
          nat_alias: draft.nat_alias.trim() || undefined,
          country_code: draft.country_code.trim().toUpperCase(),
          is_nop: draft.is_nop,
        });
      } else if (typeof editing === "number") {
        await admin.teamUpdate(editing, {
          name: draft.name.trim(),
          nat_alias: draft.nat_alias.trim(),
          country_code: draft.country_code.trim().toUpperCase(),
          is_nop: draft.is_nop,
        });
      }
      cancel();
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: TeamRow) => {
    const warn =
      `Delete team "${t.name}"?\n\n` +
      `This cascades and removes all of this team's flags, submissions, ` +
      `service health, and score history. This cannot be undone.`;
    if (!window.confirm(warn)) return;
    setBusy(true);
    try {
      await admin.teamDelete(t.id);
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const rotate = async (t: TeamRow) => {
    if (!window.confirm(`Rotate submit token for "${t.name}"?\n\nThe current token will stop working immediately.`)) return;
    setBusy(true);
    try {
      await admin.teamRotateToken(t.id);
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Rotate failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Teams</h1>
          <p className="subtitle">
            Manage participating teams: name, country, NAT alias, NOP flag,
            and submit tokens.
          </p>
        </div>
        <div>
          <button
            className="btn btn-primary"
            onClick={startCreate}
            disabled={editing === "new"}
          >
            + New team
          </button>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}

      {editing !== null && (
        <div className="card team-edit">
          <h3 style={{ marginTop: 0 }}>
            {editing === "new" ? "Create team" : `Edit team #${editing}`}
          </h3>
          <div className="team-edit-grid">
            <label>
              <span>Name</span>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="team3"
                disabled={busy}
                autoFocus
              />
            </label>
            <label>
              <span>NAT alias</span>
              <input
                value={draft.nat_alias}
                onChange={(e) => setDraft({ ...draft, nat_alias: e.target.value })}
                placeholder={`${draft.name || "team"}-nat`}
                disabled={busy}
              />
            </label>
            <label>
              <span>Country (ISO 2)</span>
              <input
                value={draft.country_code}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    country_code: e.target.value.toUpperCase().slice(0, 2),
                  })
                }
                placeholder="XK"
                maxLength={2}
                disabled={busy}
                style={{ textTransform: "uppercase" }}
              />
              <span className="hint">
                Preview: <span className="flag-preview">{flagEmoji(draft.country_code)}</span>
              </span>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.is_nop}
                onChange={(e) => setDraft({ ...draft, is_nop: e.target.checked })}
                disabled={busy}
              />
              <span>NOP team (excluded from scoring)</span>
            </label>
          </div>
          {msg && <div className="alert alert-danger">{msg}</div>}
          <div className="team-edit-actions">
            <button className="btn btn-ghost" onClick={cancel} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}

      <div className="card no-pad">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>ID</th>
                <th style={{ width: 70 }}>Flag</th>
                <th>Name</th>
                <th>NAT alias</th>
                <th>Country</th>
                <th>NOP</th>
                <th>Submit token</th>
                <th style={{ width: 240 }}></th>
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((t) => (
                <tr key={t.id} className={t.is_nop ? "team-nop" : ""}>
                  <td className="muted">#{t.id}</td>
                  <td>
                    <span className="flag-mini" title={t.country_code}>
                      <span aria-hidden>{flagEmoji(t.country_code)}</span>
                    </span>
                  </td>
                  <td>
                    <strong>{t.name}</strong>
                  </td>
                  <td>
                    <code className="mono">{t.nat_alias}</code>
                  </td>
                  <td>{t.country_code}</td>
                  <td>{t.is_nop ? <span className="badge-warn">NOP</span> : "—"}</td>
                  <td>
                    <code className="mono token-cell">{t.submit_token}</code>{" "}
                    <CopyButton text={t.submit_token} label="token" />
                  </td>
                  <td className="right">
                    <button
                      className="btn btn-xs btn-ghost"
                      onClick={() => startEdit(t)}
                      disabled={busy}
                    >
                      Edit
                    </button>{" "}
                    <button
                      className="btn btn-xs btn-ghost"
                      onClick={() => rotate(t)}
                      disabled={busy}
                      title="Generate a new submit token"
                    >
                      Rotate token
                    </button>{" "}
                    <button
                      className="btn btn-xs btn-danger"
                      onClick={() => remove(t)}
                      disabled={busy}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {!data?.rows.length && (
                <tr>
                  <td colSpan={8} className="muted center">
                    No teams.
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
