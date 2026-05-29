import { useState } from "react";
import { admin, type WikiPage } from "../../api";
import { useConfirmDialog } from "../../components/ConfirmDialog";
import { emitToast } from "../../components/ToastProvider";
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
  const { confirm, dialog } = useConfirmDialog();

  const pages: WikiPage[] = data?.rows ?? [];
  const publishedCount = pages.filter((page) => page.is_published).length;
  const draftCount = pages.length - publishedCount;
  const selectedPage = selected === "new" ? null : pages.find((page) => page.slug === selected);
  const bodyStats = getBodyStats(draft.body_md);

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
      emitToast("Slug and title are required", "warning");
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
      emitToast(`Saved ${out.title}`, "success");
      refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setMsg(message);
      emitToast(message, "danger");
    } finally {
      setBusy(false);
    }
  };

  const del = async () => {
    if (selected === null || selected === "new") return;
    confirm({
      title: `Delete ${selected}`,
      body: "The public wiki page will be removed immediately.",
      requiredText: selected,
      confirmLabel: "Delete page",
      tone: "danger",
      action: async () => {
        setBusy(true);
        try {
          await admin.wikiDelete(selected);
          emitToast(`Deleted ${selected}`, "success");
          setSelected(null);
          setDraft(EMPTY);
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
          <h1>Wiki</h1>
          <p className="subtitle">
            Manage public Markdown pages served at <code>/wiki</code>.
          </p>
        </div>
      </header>

      <div className="admin-metric-row">
        <MetricCard label="Pages" value={pages.length} />
        <MetricCard label="Published" value={publishedCount} />
        <MetricCard label="Drafts" value={draftCount} />
        <MetricCard label="Last updated" value={formatPageDate(getLatestUpdatedAt(pages))} />
      </div>

      {error && <p className="error">Failed to load: {error}</p>}

      <div className="wiki-admin-layout">
        <aside className="admin-panel wiki-page-list">
          <div className="admin-panel-head">
            <div>
              <h2>Pages</h2>
              <p>{pages.length ? "Sorted by public order" : "No pages yet"}</p>
            </div>
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

          <div className="wiki-admin-pages">
            {pages.map((p) => (
              <button
                key={p.slug}
                className={`wiki-admin-page ${selected === p.slug ? "active" : ""}`}
                type="button"
                onClick={() => selectPage(p.slug)}
              >
                <span>
                  <strong>{p.title}</strong>
                  <small>{p.slug}</small>
                </span>
                <em className={p.is_published ? "status-live" : "status-draft"}>
                  {p.is_published ? "Live" : "Draft"}
                </em>
              </button>
            ))}
            {pages.length === 0 && (
              <div className="admin-empty compact">
                <h2>No wiki pages</h2>
                <p>Create the first public rulebook page.</p>
              </div>
            )}
          </div>
        </aside>

        <section className="admin-panel wiki-editor-panel">
          {selected === null ? (
            <div className="wiki-editor-empty">
              <h2>Select a page to edit</h2>
              <p>Pick an existing public page, or create a new Markdown document.</p>
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => {
                  setSelected("new");
                  setDraft(EMPTY);
                  setMsg(null);
                }}
              >
                Create page
              </button>
            </div>
          ) : (
            <>
              <div className="admin-panel-head wiki-editor-head">
                <div>
                  <h2>{selected === "new" ? "New wiki page" : draft.title || "Untitled page"}</h2>
                  <p>
                    {selected === "new"
                      ? "Create a public page"
                      : `Editing /wiki/${selected}`}
                  </p>
                </div>
                <div className="wiki-editor-actions">
                  {selectedPage && selectedPage.is_published && (
                    <a
                      className="btn btn-ghost btn-xs"
                      href={`/wiki/${encodeURIComponent(selectedPage.slug)}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View public
                    </a>
                  )}
                  {selected !== "new" && (
                    <button className="btn btn-ghost btn-xs" onClick={del} disabled={busy}>
                      Delete
                    </button>
                  )}
                </div>
              </div>

              <div className="wiki-editor-grid">
                <label className="field">
                  <span>Slug</span>
                  <input
                    value={draft.slug}
                    onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
                    disabled={selected !== "new"}
                    placeholder="team-api-reference"
                  />
                </label>
                <label className="field">
                  <span>Title</span>
                  <input
                    value={draft.title}
                    onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                    placeholder="Team API Reference"
                  />
                </label>
                <label className="field">
                  <span>Sort order</span>
                  <input
                    type="number"
                    value={draft.sort_order}
                    onChange={(e) =>
                      setDraft({ ...draft, sort_order: Number(e.target.value) || 0 })
                    }
                  />
                </label>
                <label className="wiki-publish-toggle">
                  <input
                    type="checkbox"
                    checked={draft.is_published}
                    onChange={(e) => setDraft({ ...draft, is_published: e.target.checked })}
                  />
                  <span>
                    <strong>{draft.is_published ? "Published" : "Draft"}</strong>
                    <small>Visible in the public wiki</small>
                  </span>
                </label>
              </div>

              <label className="field wiki-body-editor">
                <span>Body markdown</span>
                <textarea
                  value={draft.body_md}
                  onChange={(e) => setDraft({ ...draft, body_md: e.target.value })}
                  rows={20}
                  placeholder="# Page heading&#10;&#10;Write the rules, API notes, and examples here."
                />
              </label>

              <div className="wiki-editor-meta">
                <span>{bodyStats.words} words</span>
                <span>{bodyStats.headings} headings</span>
                <span>{bodyStats.codeBlocks} code blocks</span>
                <span>{selectedPage ? `Updated ${formatPageDate(selectedPage.updated_at)}` : "New page"}</span>
              </div>

              <div className="admin-panel-actions">
                <button className="btn btn-primary" onClick={save} disabled={busy}>
                  {busy ? "Saving…" : "Save"}
                </button>
                {msg && <span className="inline-status">{msg}</span>}
              </div>
            </>
          )}
        </section>
      </div>
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

function getBodyStats(body: string) {
  const words = body.trim() ? body.trim().split(/\s+/).length : 0;
  return {
    words,
    headings: (body.match(/^#{1,6}\s+/gm) ?? []).length,
    codeBlocks: Math.floor((body.match(/```/g) ?? []).length / 2),
  };
}

function getLatestUpdatedAt(pages: WikiPage[]): string | null {
  return (
    pages
      .map((page) => page.updated_at)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null
  );
}

function formatPageDate(value?: string | null): string {
  if (!value) return "None";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value.replace("T", " ").slice(0, 10);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
