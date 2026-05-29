import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchPublicWikiIndex,
  fetchPublicWikiPage,
  type WikiPage,
} from "../api";

type WikiHeading = {
  id: string;
  level: number;
  text: string;
};

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

function plainText(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[`*_#]/g, "")
    .trim();
}

function slugBase(text: string): string {
  return (
    plainText(text)
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .slice(0, 80) || "section"
  );
}

function uniqueHeadingId(text: string, seen: Map<string, number>): string {
  const base = slugBase(text);
  const count = seen.get(base) ?? 0;
  seen.set(base, count + 1);
  return count === 0 ? base : `${base}-${count + 1}`;
}

function extractHeadings(src: string): WikiHeading[] {
  const seen = new Map<string, number>();
  return src
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => /^(#{1,6})\s+(.+)$/.exec(line))
    .filter((heading): heading is RegExpExecArray => Boolean(heading))
    .map((heading) => {
      const text = plainText(heading[2]);
      return {
        id: uniqueHeadingId(heading[2], seen),
        level: heading[1].length,
        text,
      };
    });
}

function filterWikiPages(pages: WikiPage[] | null, query: string): WikiPage[] | null {
  if (pages === null) return null;
  const q = query.trim().toLowerCase();
  if (!q) return pages;
  return pages.filter(
    (page) =>
      page.title.toLowerCase().includes(q) ||
      page.slug.toLowerCase().includes(q) ||
      (page.body_md ?? "").toLowerCase().includes(q),
  );
}

function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let inCode = false;
  let codeBuf: string[] = [];
  let listBuf: string[] = [];
  let paraBuf: string[] = [];
  const headingIds = new Map<string, number>();

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
        out.push(
          `<div class="wiki-code-block"><button type="button" class="wiki-copy">Copy</button><pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre></div>`,
        );
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
      const id = uniqueHeadingId(heading[2], headingIds);
      out.push(`<h${level} id="${id}">${renderInline(heading[2])}</h${level}>`);
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
  if (inCode) {
    out.push(
      `<div class="wiki-code-block"><button type="button" class="wiki-copy">Copy</button><pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre></div>`,
    );
  }
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
  const [query, setQuery] = useState("");
  const activePage = pages?.find((p) => p.slug === active);
  const filteredPages = useMemo(() => filterWikiPages(pages, query), [pages, query]);

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
            <small>
              {filteredPages
                ? `${filteredPages.length}/${pages?.length ?? 0} pages`
                : "Loading"}
            </small>
          </div>
          <label className="wiki-search">
            <span>Search docs</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rules, scoring, TCP..."
            />
          </label>
          <nav className="wiki-nav">
            <Link className={!active ? "active" : ""} to="/wiki">
              Overview
            </Link>
            {pages === null && <span className="wiki-nav-muted">Loading pages...</span>}
            {filteredPages?.map((p) => (
              <Link
                key={p.slug}
                className={p.slug === active ? "active" : ""}
                to={`/wiki/${p.slug}`}
              >
                {p.title}
              </Link>
            ))}
            {filteredPages && filteredPages.length === 0 && (
              <span className="wiki-nav-muted">No matches.</span>
            )}
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
  const [query, setQuery] = useState("");

  return (
    <WikiShell>
      {(pages, error) => {
        const firstPage = pages?.[0];
        const visiblePages = filterWikiPages(pages, query);
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

            <div className="wiki-index-tools">
              <label className="wiki-index-search">
                <span>Search all docs</span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Find TCP submitter, scoring, rules..."
                />
              </label>
            </div>

            <section className="wiki-card-grid" aria-label="Wiki page cards">
              {pages === null && (
                <>
                  <div className="wiki-page-card skeleton" />
                  <div className="wiki-page-card skeleton" />
                  <div className="wiki-page-card skeleton" />
                </>
              )}
              {visiblePages?.map((p, idx) => (
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
              {pages && pages.length > 0 && visiblePages?.length === 0 && (
                <div className="wiki-empty">
                  <h2>No matching pages.</h2>
                  <p>Try a different search term.</p>
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
  const articleRef = useRef<HTMLElement | null>(null);

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
  const headings = useMemo(
    () => (page ? extractHeadings(page.body_md ?? "") : []),
    [page],
  );

  useEffect(() => {
    const root = articleRef.current;
    if (!root) return undefined;

    const onClick = async (event: MouseEvent) => {
      const button = (event.target as Element | null)?.closest<HTMLButtonElement>(".wiki-copy");
      if (!button) return;
      const code = button.parentElement?.querySelector("code")?.textContent ?? "";
      const original = button.textContent ?? "Copy";
      try {
        await navigator.clipboard.writeText(code);
        button.textContent = "Copied";
        button.classList.add("copied");
      } catch {
        button.textContent = "Copy failed";
      }
      window.setTimeout(() => {
        button.textContent = original;
        button.classList.remove("copied");
      }, 1400);
    };

    root.addEventListener("click", onClick);
    return () => root.removeEventListener("click", onClick);
  }, [articleHtml]);

  return (
    <WikiShell active={slug}>
      {(pages) => {
        const pageIndex = pages?.findIndex((p) => p.slug === slug) ?? -1;
        const prevPage = pageIndex > 0 ? pages?.[pageIndex - 1] : undefined;
        const nextPage =
          pages && pageIndex >= 0 && pageIndex < pages.length - 1
            ? pages[pageIndex + 1]
            : undefined;

        return (
          <div className="wiki-article-grid">
            <article className="wiki-article" ref={articleRef}>
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
                  <nav className="wiki-doc-nav" aria-label="Adjacent wiki pages">
                    {prevPage ? (
                      <Link to={`/wiki/${prevPage.slug}`}>
                        <span>Previous</span>
                        <strong>{prevPage.title}</strong>
                      </Link>
                    ) : (
                      <span />
                    )}
                    {nextPage ? (
                      <Link to={`/wiki/${nextPage.slug}`}>
                        <span>Next</span>
                        <strong>{nextPage.title}</strong>
                      </Link>
                    ) : (
                      <span />
                    )}
                  </nav>
                </>
              )}
            </article>
            {headings.length > 0 && (
              <aside className="wiki-toc" aria-label="On this page">
                <strong>On this page</strong>
                <nav>
                  {headings.map((heading) => (
                    <a
                      key={heading.id}
                      className={`level-${heading.level}`}
                      href={`#${heading.id}`}
                    >
                      {heading.text}
                    </a>
                  ))}
                </nav>
              </aside>
            )}
          </div>
        );
      }}
    </WikiShell>
  );
}
