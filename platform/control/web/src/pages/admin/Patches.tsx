import { useMemo, useRef, useState } from "react";
import { admin, patchDownloadUrl, type PatchRow } from "../../api";
import { usePoll } from "../../hooks";

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export default function Patches() {
  const { data, error, refresh } = usePoll(() => admin.patchesList(), 15000, []);
  const [serviceName, setServiceName] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const services = data?.services ?? [];
  const rows: PatchRow[] = data?.rows ?? [];
  const grouped = useMemo(() => {
    const m = new Map<string, PatchRow[]>();
    for (const r of rows) {
      const list = m.get(r.service_name) ?? [];
      list.push(r);
      m.set(r.service_name, list);
    }
    return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [rows]);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setMsg("Choose a file first");
      return;
    }
    if (!serviceName.trim()) {
      setMsg("Service name is required");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await admin.patchesUpload(serviceName.trim(), file, notes);
      if (fileRef.current) fileRef.current.value = "";
      setNotes("");
      setMsg(`Uploaded ${file.name}`);
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const del = async (id: number, filename: string) => {
    if (!confirm(`Delete patch "${filename}"?`)) return;
    setBusy(true);
    try {
      await admin.patchesDelete(id);
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Patches</h1>
        <p className="muted">
          Upload patch bundles (tarballs, ansible playbooks, scripts). Teams
          download from <code>/api/v1/patches</code>.
        </p>
      </header>

      <section className="card" style={{ marginBottom: 16 }}>
        <h3>Upload new patch</h3>
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr", marginTop: 8 }}>
          <label>
            Service
            <input
              list="patches-svc-list"
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              placeholder="svc1"
            />
            <datalist id="patches-svc-list">
              {services.map((s) => (
                <option key={s.id} value={s.name} />
              ))}
            </datalist>
          </label>
          <label>
            File
            <input type="file" ref={fileRef} />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            Release notes (markdown, optional)
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="What does this patch fix? Any operator instructions?"
            />
          </label>
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn btn-primary" onClick={upload} disabled={busy}>
            {busy ? "Uploading…" : "Upload"}
          </button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </section>

      {error && <p className="error">Failed to load: {error}</p>}

      {grouped.length === 0 ? (
        <p className="muted">No patches uploaded yet.</p>
      ) : (
        grouped.map(([svc, list]) => (
          <section key={svc} className="card" style={{ marginBottom: 12 }}>
            <h3>{svc}</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Size</th>
                  <th>SHA-256</th>
                  <th>Notes</th>
                  <th>Uploaded</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <a href={patchDownloadUrl(r.id)} download>
                        {r.filename}
                      </a>
                    </td>
                    <td>{humanBytes(r.size_bytes)}</td>
                    <td>
                      <code style={{ fontSize: 11 }}>{r.sha256.slice(0, 16)}…</code>
                    </td>
                    <td style={{ maxWidth: 320, whiteSpace: "pre-wrap" }}>{r.notes}</td>
                    <td>{r.created_at?.replace("T", " ").slice(0, 19) ?? "—"}</td>
                    <td>
                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => del(r.id, r.filename)}
                        disabled={busy}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))
      )}
    </div>
  );
}
