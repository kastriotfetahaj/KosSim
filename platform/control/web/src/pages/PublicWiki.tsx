import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchPublicWikiIndex,
  fetchPublicWikiPage,
  type WikiPage,
} from "../api";

// Tiny safe markdown -> HTML for an internal trusted-author wiki.
// Supports: headings (#..######), fenced code blocks, inline code,
// **bold**, *italic*, links, lists (-), paragraphs. Everything is
// HTML-escaped first, so writing literal HTML in pages renders as text.
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderInline(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_m, label, href) =>
      `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${label}</a>`,
  );
  return out;
}

function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let inCode = false;
  let codeBuf: string[] = [];
  let listBuf: string[] = [];
  let paraBuf: string[] = [];

  const flushPara = () => {
    if (paraBuf.length) {
      out.push(`<p>${renderInline(paraBuf.join(" "))}</p>`);
      paraBuf = [];
    }
  };
  const flushList = () => {
    if (listBuf.length) {
      out.push(`<ul>${listBuf.map((l) => `<li>${renderInline(l)}</li>`).join("")}</ul>`);
      listBuf = [];
    }
  };

  for (const raw of lines) {
    const line = raw;
    if (inCode) {
      if (line.startsWith("```")) {
        out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
        codeBuf = [];
        inCode = false;
      } else {
        codeBuf.push(line);
      }
      continue;
    }
    if (line.startsWith("```")) {
      flushPara();
      flushList();
      inCode = true;
      continue;
    }
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      flushPara();
      flushList();
      const level = heading[1].length;
      out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }
    const li = /^[-*]\s+(.+)$/.exec(line);
    if (li) {
      flushPara();
      listBuf.push(li[1]);
      continue;
    }
    flushList();
    paraBuf.push(line);
  }
  if (inCode) out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
  flushPara();
  flushList();
  return out.join("\n");
}

function useWikiPages() {
  const [pages, setPages] = useState<WikiPage[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicWikiIndex()
      .then((r) => {
        if (!cancelled) setPages(r.rows);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setPages([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { pages, error };
}

function formatUpdated(value?: string | null): string {
  if (!value) return "Not updated yet";
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return "Updated";
  return `Updated ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

function WikiShell({
  active,
  children,
}: {
  active?: string;
  children: (pages: WikiPage[] | null, error: string | null) => JSX.Element;
}) {
  const { pages, error } = useWikiPages();
  const activePage = pages?.find((p) => p.slug === active);

  return (
    <div className="wiki-site">
      <header className="wiki-topbar">
        <Link className="wiki-brand" to="/wiki" aria-label="KosSim Wiki home">
          <span className="wiki-brand-mark">
            <img src="/static/kct-logo.png" alt="" />
          </span>
          <span>
            <strong>KosSim Wiki</strong>
            <small>Player rulebook</small>
          </span>
        </Link>
        <nav className="wiki-toplinks" aria-label="Primary wiki links">
          <Link to="/public/scoreboard">Scoreboard</Link>
          <Link to="/admin">Admin</Link>
        </nav>
      </header>

      <div className="wiki-layout">
        <aside className="wiki-sidebar" aria-label="Wiki pages">
          <div className="wiki-sidebar-head">
            <span>Contents</span>
            <small>{pages ? `${pages.length} pages` : "Loading"}</small>
          </div>
          <nav className="wiki-nav">
            <Link className={!active ? "active" : ""} to="/wiki">
              Overview
            </Link>
            {pages === null && <span className="wiki-nav-muted">Loading pages...</span>}
            {pages?.map((p) => (
              <Link
                key={p.slug}
                className={p.slug === active ? "active" : ""}
                to={`/wiki/${p.slug}`}
              >
                {p.title}
              </Link>
            ))}
          </nav>
        </aside>

        <main className="wiki-main">
          <div className="wiki-page-kicker">
            <span>Attack/Defense Platform</span>
            <span>{activePage ? formatUpdated(activePage.updated_at) : "Live docs"}</span>
          </div>
          {children(pages, error)}
        </main>
      </div>
    </div>
  );
}

function summaryFor(page: WikiPage): string {
  const body = (page.body_md ?? "")
    .replace(/^#+\s+.+$/gm, "")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/[-*]\s+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return body.slice(0, 148) + (body.length > 148 ? "..." : "");
}

export function WikiIndex() {
  return (
    <WikiShell>
      {(pages, error) => {
        const firstPage = pages?.[0];
        return (
          <>
            <section className="wiki-hero">
              <div>
                <p className="wiki-eyebrow">Competition docs</p>
                <h1>Rules, scoring, submitter usage, and team API notes.</h1>
                <p>
                  A single public place for participants to check how the game works,
                  how points are calculated, and how automation should talk to KosSim.
                </p>
              </div>
              <img
                className="wiki-hero-logo"
                src="/static/kct-logo.png"
                alt="Kosova Cyber Team"
              />
              <div className="wiki-hero-actions">
                {firstPage ? (
                  <Link className="btn btn-primary" to={`/wiki/${firstPage.slug}`}>
                    Start reading
                  </Link>
                ) : (
                  <span className="muted">Loading pages...</span>
                )}
                <Link className="btn btn-ghost" to="/public/scoreboard">
                  Open scoreboard
                </Link>
              </div>
            </section>

            {error && <p className="error">Failed to load wiki: {error}</p>}

            <section className="wiki-card-grid" aria-label="Wiki page cards">
              {pages === null && (
                <>
                  <div className="wiki-page-card skeleton" />
                  <div className="wiki-page-card skeleton" />
                  <div className="wiki-page-card skeleton" />
                </>
              )}
              {pages?.map((p, idx) => (
                <Link className="wiki-page-card" key={p.slug} to={`/wiki/${p.slug}`}>
                  <span className="wiki-card-index">{String(idx + 1).padStart(2, "0")}</span>
                  <h2>{p.title}</h2>
                  <p>{summaryFor(p)}</p>
                  <small>{formatUpdated(p.updated_at)}</small>
                </Link>
              ))}
              {pages && pages.length === 0 && (
                <div className="wiki-empty">
                  <h2>No wiki pages published yet.</h2>
                  <p>Published pages from the admin wiki editor will appear here.</p>
                </div>
              )}
            </section>
          </>
        );
      }}
    </WikiShell>
  );
}

export function WikiPageView() {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<WikiPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPage(null);
    setError(null);
    if (!slug) return undefined;
    fetchPublicWikiPage(slug)
      .then((p) => {
        if (!cancelled) setPage(p);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const articleHtml = useMemo(
    () => (page ? renderMarkdown(page.body_md ?? "") : ""),
    [page],
  );

  return (
    <WikiShell active={slug}>
      {() => (
        <article className="wiki-article">
          {error && <p className="error">Failed to load page: {error}</p>}
          {page === null && !error && <p className="muted">Loading page...</p>}
          {page && (
            <>
              <header className="wiki-article-header">
                <Link to="/wiki" className="wiki-backlink">
                  Wiki overview
                </Link>
                <h1>{page.title}</h1>
                <p>{formatUpdated(page.updated_at)}</p>
              </header>
              <div
                className="wiki-body"
                dangerouslySetInnerHTML={{ __html: articleHtml }}
              />
            </>
          )}
        </article>
      )}
    </WikiShell>
  );
}
