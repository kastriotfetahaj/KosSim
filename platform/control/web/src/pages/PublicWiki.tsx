import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchPublicWikiIndex,
  fetchPublicWikiPage,
  type WikiPage,
} from "../api";

// Tiny safe markdown → HTML for an internal trusted-author wiki.
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

function WikiSidebar({ active }: { active?: string }) {
  const [pages, setPages] = useState<WikiPage[] | null>(null);
  useEffect(() => {
    fetchPublicWikiIndex().then((r) => setPages(r.rows)).catch(() => setPages([]));
  }, []);
  return (
    <nav style={{ minWidth: 220 }}>
      <h3 style={{ marginTop: 0 }}>Wiki</h3>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {pages === null && <li className="muted">Loading…</li>}
        {pages && pages.length === 0 && <li className="muted">No pages yet.</li>}
        {pages?.map((p) => (
          <li key={p.slug} style={{ margin: "4px 0" }}>
            <Link
              to={`/wiki/${p.slug}`}
              style={{
                fontWeight: p.slug === active ? 600 : 400,
                textDecoration: "none",
              }}
            >
              {p.title}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function WikiIndex() {
  return (
    <div style={{ display: "flex", gap: 24, padding: 24 }}>
      <WikiSidebar />
      <main style={{ flex: 1 }}>
        <h1>Wiki</h1>
        <p className="muted">Pick a page on the left.</p>
      </main>
    </div>
  );
}

export function WikiPageView() {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<WikiPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPage(null);
    setError(null);
    if (!slug) return;
    fetchPublicWikiPage(slug)
      .then(setPage)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [slug]);

  return (
    <div style={{ display: "flex", gap: 24, padding: 24 }}>
      <WikiSidebar active={slug} />
      <main style={{ flex: 1, maxWidth: 880 }}>
        {error && <p className="error">{error}</p>}
        {page === null && !error && <p className="muted">Loading…</p>}
        {page && (
          <article>
            <h1>{page.title}</h1>
            <div
              className="wiki-body"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(page.body_md ?? "") }}
            />
          </article>
        )}
      </main>
    </div>
  );
}
