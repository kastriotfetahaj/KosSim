import { useState } from "react";
import { admin, type WikiPage } from "../../api";
import { usePoll } from "../../hooks";

type Draft = {
  slug: string;
  title: string;
  body_md: string;
  is_published: boolean;
  sort_order: number;
};

const EMPTY: Draft = {
  slug: "",
  title: "",
  body_md: "",
  is_published: true,
  sort_order: 100,
};

export default function Wiki() {
  const { data, error, refresh } = usePoll(() => admin.wikiList(), 30000, []);
  const [selected, setSelected] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const pages: WikiPage[] = data?.rows ?? [];

  // Load a page into the draft when it is selected from the list. Doing this
  // on the click (instead of in an effect keyed on `pages`) means the 30s
  // list poll no longer clobbers in-progress edits.
  const selectPage = (slug: string) => {
    const p = pages.find((x) => x.slug === slug);
    setSelected(slug);
    setMsg(null);
    if (p) {
      setDraft({
        slug: p.slug,
        title: p.title,
        body_md: p.body_md ?? "",
        is_published: p.is_published,
        sort_order: p.sort_order,
      });
    }
  };

  const save = async () => {
    if (!draft.slug.trim() || !draft.title.trim()) {
      setMsg("slug and title required");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const out = await admin.wikiUpsert({
        slug: draft.slug,
        title: draft.title,
        body_md: draft.body_md,
        is_published: draft.is_published,
        sort_order: draft.sort_order,
      });
      setSelected(out.slug);
      setMsg("Saved.");
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const del = async () => {
    if (selected === null || selected === "new") return;
    if (!confirm(`Delete page "${selected}"?`)) return;
    setBusy(true);
    try {
      await admin.wikiDelete(selected);
      setSelected(null);
      setDraft(EMPTY);
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
        <h1>Wiki</h1>
        <p className="muted">
          Markdown pages served at <code>/wiki</code> and via{" "}
          <code>/api/v1/wiki</code>.
        </p>
      </header>
      {error && <p className="error">Failed to load: {error}</p>}
      <div style={{ display: "grid", gap: 16, gridTemplateColumns: "260px 1fr" }}>
        <aside className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Pages</strong>
            <button
              className="btn btn-ghost btn-xs"
              onClick={() => {
                setSelected("new");
                setDraft(EMPTY);
                setMsg(null);
              }}
            >
              + New
            </button>
          </div>
          <ul style={{ listStyle: "none", padding: 0, marginTop: 8 }}>
            {pages.map((p) => (
              <li key={p.slug}>
                <button
                  className={`nav-item ${selected === p.slug ? "active" : ""}`}
                  style={{ width: "100%", textAlign: "left" }}
                  onClick={() => selectPage(p.slug)}
                >
                  {p.title}
                  {!p.is_published && (
                    <span className="muted" style={{ marginLeft: 6 }}>
                      (draft)
                    </span>
                  )}
                </button>
              </li>
            ))}
            {pages.length === 0 && <li className="muted">No pages yet.</li>}
          </ul>
        </aside>
        <section className="card">
          {selected === null ? (
            <p className="muted">Pick a page on the left, or click + New.</p>
          ) : (
            <>
              <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }}>
                <label>
                  Slug
                  <input
                    value={draft.slug}
                    onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
                    disabled={selected !== "new"}
                  />
                </label>
                <label>
                  Title
                  <input
                    value={draft.title}
                    onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                  />
                </label>
                <label>
                  Sort order
                  <input
                    type="number"
                    value={draft.sort_order}
                    onChange={(e) =>
                      setDraft({ ...draft, sort_order: Number(e.target.value) || 0 })
                    }
                  />
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={draft.is_published}
                    onChange={(e) => setDraft({ ...draft, is_published: e.target.checked })}
                  />
                  Published
                </label>
              </div>
              <label style={{ display: "block", marginTop: 12 }}>
                Body (markdown)
                <textarea
                  value={draft.body_md}
                  onChange={(e) => setDraft({ ...draft, body_md: e.target.value })}
                  rows={18}
                  style={{ width: "100%", fontFamily: "monospace" }}
                />
              </label>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="btn btn-primary" onClick={save} disabled={busy}>
                  {busy ? "Saving…" : "Save"}
                </button>
                {selected !== "new" && (
                  <button className="btn btn-ghost" onClick={del} disabled={busy}>
                    Delete
                  </button>
                )}
                {msg && <span className="muted" style={{ alignSelf: "center" }}>{msg}</span>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
