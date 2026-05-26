import { useState } from "react";
import { admin, type DecodeReport } from "../../api";
import CopyButton from "../../components/CopyButton";
import SearchInput from "../../components/SearchInput";
import { useDebounced, usePoll, useQueryParam } from "../../hooks";

export default function Flags() {
  const [q, setQ] = useQueryParam("q");
  const dq = useDebounced(q, 200);
  const { data, error } = usePoll(() => admin.flagsRecent(dq), 10000, [dq]);
  const [flagInput, setFlagInput] = useState("");
  const [report, setReport] = useState<DecodeReport | null>(null);
  const [decoding, setDecoding] = useState(false);

  const decode = async () => {
    if (!flagInput.trim()) return;
    setDecoding(true);
    try {
      setReport(await admin.decodeFlag(flagInput.trim()));
    } catch (e: unknown) {
      setReport({
        valid: false,
        error: e instanceof Error ? e.message : "Decode failed",
      });
    } finally {
      setDecoding(false);
    }
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Flag inspector</h1>
          <p className="subtitle">HMAC decode · pattern <code>{data?.pattern ?? "…"}</code></p>
        </div>
      </header>

      <section className="card">
        <h2>Decode flag</h2>
        <div className="flag-decode">
          <textarea
            rows={2}
            value={flagInput}
            onChange={(e) => setFlagInput(e.target.value)}
            placeholder="Paste a flag, e.g. SSH{...}"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) decode();
            }}
          />
          <button className="btn btn-primary" onClick={decode} disabled={decoding}>
            {decoding ? "Decoding…" : "Decode"}
          </button>
        </div>
        {report && <DecodeBox report={report} />}
      </section>

      <section className="card mt-1">
        <div className="card-header">
          <h2>Recent stored flags</h2>
          <SearchInput value={q} onChange={setQ} placeholder="Filter by team / service / flag…" />
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Flag</th>
                <th>Team</th>
                <th>Service</th>
                <th>Tick</th>
                <th>Payload</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <div className="flag-cell">
                      <code className="mono truncate" title={r.flag}>
                        {r.flag.slice(0, 48)}…
                      </code>
                      <CopyButton text={r.flag} label="flag" />
                    </div>
                  </td>
                  <td>{r.team}</td>
                  <td>{r.service}</td>
                  <td className="num">{r.tick}</td>
                  <td className="num">{r.payload}</td>
                  <td className="muted">{fmt(r.created_at)}</td>
                </tr>
              ))}
              {!data?.rows.length && (
                <tr>
                  <td colSpan={6} className="muted center">
                    No flags yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function DecodeBox({ report }: { report: DecodeReport }) {
  if (!report.valid) {
    return <div className="alert alert-danger mt-1">{report.error}</div>;
  }
  return (
    <dl className="decode-grid mt-1">
      <dt>HMAC</dt>
      <dd className="ok">Valid</dd>
      <dt>Tick issued</dt>
      <dd>{report.tick}</dd>
      <dt>Target team</dt>
      <dd>{report.team}</dd>
      <dt>Service</dt>
      <dd>{report.service}</dd>
      <dt>Payload</dt>
      <dd>{report.payload}</dd>
      <dt>Submit verdict</dt>
      <dd>{report.verdict}</dd>
      {report.is_firstblood && (
        <>
          <dt>First blood</dt>
          <dd>★</dd>
        </>
      )}
    </dl>
  );
}

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}
