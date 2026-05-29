import { useMemo, useRef, useState } from "react";
import { admin, patchDownloadUrl, type PatchRow } from "../../api";
import { useConfirmDialog } from "../../components/ConfirmDialog";
import { emitToast } from "../../components/ToastProvider";
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
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const { confirm, dialog } = useConfirmDialog();

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
  const servicesCovered = new Set(rows.map((row) => row.service_name)).size;
  const totalBytes = rows.reduce((sum, row) => sum + row.size_bytes, 0);
  const latestUpload = rows
    .map((row) => row.created_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setMsg("Choose a file first");
      emitToast("Choose a file first", "warning");
      return;
    }
    if (!serviceName.trim()) {
      setMsg("Service name is required");
      emitToast("Service name is required", "warning");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await admin.patchesUpload(serviceName.trim(), file, notes);
      if (fileRef.current) fileRef.current.value = "";
      setFileName("");
      setNotes("");
      setMsg(`Uploaded ${file.name}`);
      emitToast(`Uploaded ${file.name}`, "success");
      refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setMsg(message);
      emitToast(message, "danger");
    } finally {
      setBusy(false);
    }
  };

  const del = async (id: number, filename: string) => {
    confirm({
      title: `Delete ${filename}`,
      body: "Teams will no longer be able to download this patch bundle.",
      requiredText: filename,
      confirmLabel: "Delete patch",
      tone: "danger",
      action: async () => {
        setBusy(true);
        try {
          await admin.patchesDelete(id);
          emitToast(`Deleted ${filename}`, "success");
          refresh();
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          setMsg(message);
          emitToast(message, "danger");
        } finally {
          setBusy(false);
        }
      },
    });
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Patches</h1>
          <p className="subtitle">
            Publish patch bundles for team download at <code>/api/v1/patches</code>.
          </p>
        </div>
      </header>

      <div className="admin-metric-row">
        <MetricCard label="Bundles" value={rows.length} />
        <MetricCard label="Services covered" value={servicesCovered} />
        <MetricCard label="Stored size" value={humanBytes(totalBytes)} />
        <MetricCard label="Latest upload" value={formatDate(latestUpload)} />
      </div>

      {error && <p className="error">Failed to load: {error}</p>}

      <section className="admin-panel patch-upload-panel">
        <div className="admin-panel-head">
          <div>
            <h2>Upload patch</h2>
            <p>Attach a tarball, playbook, script, or bundle to one service.</p>
          </div>
          <span className="badge-neutral">Team download API</span>
        </div>

        <div className="patch-upload-grid">
          <label className="field">
            <span>Service</span>
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

          <label className="patch-file-field">
            <span>Patch file</span>
            <input
              type="file"
              ref={fileRef}
              onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")}
            />
            <strong>{fileName || "Choose file"}</strong>
            <small>{fileName ? "Ready to upload" : "No file selected"}</small>
          </label>

          <label className="field patch-notes-field">
            <span>Release notes</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              placeholder="What does this patch fix? Any operator instructions?"
            />
          </label>
        </div>

        {services.length > 0 && (
          <div className="patch-service-strip" aria-label="Known services">
            {services.map((service) => (
              <button
                key={service.id}
                className={service.name === serviceName ? "chip active" : "chip"}
                type="button"
                onClick={() => setServiceName(service.name)}
              >
                {service.name}
              </button>
            ))}
          </div>
        )}

        <div className="admin-panel-actions">
          <button className="btn btn-primary" onClick={upload} disabled={busy}>
            {busy ? "Uploading…" : "Upload"}
          </button>
          {msg && <span className="inline-status">{msg}</span>}
        </div>
      </section>

      {grouped.length === 0 ? (
        <section className="admin-empty">
          <h2>No patches uploaded yet.</h2>
          <p>Uploaded bundles will appear here grouped by service.</p>
        </section>
      ) : (
        <div className="patch-service-list">
          {grouped.map(([svc, list]) => {
            const size = list.reduce((sum, row) => sum + row.size_bytes, 0);
            return (
              <section key={svc} className="admin-panel patch-service-card">
                <div className="patch-service-head">
                  <div>
                    <h2>{svc}</h2>
                    <p>
                      {list.length} bundle{list.length === 1 ? "" : "s"} · {humanBytes(size)}
                    </p>
                  </div>
                  <button
                    className="btn btn-ghost btn-xs"
                    type="button"
                    onClick={() => setServiceName(svc)}
                  >
                    Upload to service
                  </button>
                </div>

                <div className="table-scroll patch-table-wrap">
                  <table>
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
                            <a className="patch-file-link" href={patchDownloadUrl(r.id)} download>
                              {r.filename}
                            </a>
                            <small>{r.content_type || "application/octet-stream"}</small>
                          </td>
                          <td>{humanBytes(r.size_bytes)}</td>
                          <td>
                            <code className="patch-hash">{r.sha256.slice(0, 16)}...</code>
                          </td>
                          <td>
                            <span className="patch-notes-cell">
                              {r.notes?.trim() || "No release notes."}
                            </span>
                          </td>
                          <td>{formatDateTime(r.created_at)}</td>
                          <td className="right">
                            <a
                              className="btn btn-ghost btn-xs"
                              href={patchDownloadUrl(r.id)}
                              download
                            >
                              Download
                            </a>{" "}
                            <button
                              className="btn btn-danger btn-xs"
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
                </div>
              </section>
            );
          })}
        </div>
      )}
      {dialog}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="admin-metric-card">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function formatDate(value?: string | null): string {
  if (!value) return "None";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Uploaded";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value.replace("T", " ").slice(0, 19);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
