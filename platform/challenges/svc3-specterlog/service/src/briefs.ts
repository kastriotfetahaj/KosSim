import type { Database } from "bun:sqlite";
import type { FastifyInstance, FastifyRequest } from "fastify";
import type { BriefRow } from "./db";
import { newId, signView, verifyView } from "./tokens";
import { record as auditRecord } from "./audit";
import { currentUser, requireUser } from "./accounts";
import { getCase } from "./cases";

const TITLE_MAX = 160;
const BODY_MAX = 16_000;
const COMMENT_MAX = 2_000;
const VIEW_TTL_SECONDS = 4 * 3600;

export function getBrief(db: Database, id: string): BriefRow | null {
  return db.query(
    "SELECT id, case_id, author_id, title, body, public, tick, created_at FROM briefs WHERE id = ?",
  ).get(id) as BriefRow | null;
}

export function createBrief(
  db: Database,
  opts: {
    case_id: string;
    author_id: number;
    title: string;
    body: string;
    public: boolean;
    tick: number;
  },
): BriefRow {
  const id = newId("brf");
  db.run(
    "INSERT INTO briefs (id, case_id, author_id, title, body, public, tick, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    [
      id,
      opts.case_id,
      opts.author_id,
      opts.title.slice(0, TITLE_MAX),
      opts.body.slice(0, BODY_MAX),
      opts.public ? 1 : 0,
      opts.tick,
      Date.now(),
    ],
  );
  const created = getBrief(db, id);
  if (!created) throw new Error("brief_create_failed");
  return created;
}

function readBearer(req: FastifyRequest): string | null {
  const raw = req.headers["authorization"];
  if (typeof raw !== "string") return null;
  const m = raw.match(/^Bearer\s+(.+)$/);
  return m ? m[1].trim() : null;
}

function serialise(row: BriefRow, withBody: boolean): Record<string, unknown> {
  const base: Record<string, unknown> = {
    id: row.id,
    case_id: row.case_id,
    author: row.author_id,
    title: row.title,
    public: row.public === 1,
    tick: row.tick,
    created_at: row.created_at,
  };
  if (withBody) base.body = row.body;
  return base;
}

export function briefRoutes(
  app: FastifyInstance,
  db: Database,
  secret: string,
): void {
  app.get("/api/briefs", async (req) => {
    const q = req.query as Record<string, string>;
    const user = currentUser(db, req, secret);
    const limit = Math.min(Math.max(Number(q.limit ?? 50), 1), 200);
    if (q.case) {
      const target = getCase(db, q.case);
      if (!target) return { briefs: [] };
      if (target.public === 1) {
        return {
          briefs: (db.query(
            "SELECT id, case_id, author_id, title, body, public, tick, created_at FROM briefs WHERE case_id = ? AND public = 1 ORDER BY created_at DESC LIMIT ?",
          ).all(target.id, limit) as BriefRow[]).map((row) => serialise(row, false)),
        };
      }
      if (!user || (user.id !== target.owner_id && user.role !== "admin")) {
        return { briefs: [] };
      }
      return {
        briefs: (db.query(
          "SELECT id, case_id, author_id, title, body, public, tick, created_at FROM briefs WHERE case_id = ? ORDER BY created_at DESC LIMIT ?",
        ).all(target.id, limit) as BriefRow[]).map((row) => serialise(row, false)),
      };
    }
    return {
      briefs: (db.query(
        "SELECT id, case_id, author_id, title, body, public, tick, created_at FROM briefs WHERE public = 1 ORDER BY created_at DESC LIMIT ?",
      ).all(limit) as BriefRow[]).map((row) => serialise(row, false)),
    };
  });

  app.post("/api/briefs", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const body = (req.body ?? {}) as {
      case_id?: string;
      title?: string;
      body?: string;
      public?: boolean;
    };
    const caseRow = body.case_id ? getCase(db, body.case_id) : null;
    if (!caseRow) return reply.code(400).send({ error: "missing_case" });
    if (caseRow.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const title = String(body.title ?? "").trim();
    if (!title) return reply.code(400).send({ error: "missing_title" });
    const created = createBrief(db, {
      case_id: caseRow.id,
      author_id: user.id,
      title,
      body: String(body.body ?? ""),
      public: Boolean(body.public),
      tick: 0,
    });
    auditRecord(db, user.username, "brief.create", `brief:${created.id}`);
    return serialise(created, true);
  });

  app.get("/api/briefs/:id", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const row = getBrief(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.public === 1) {
      return serialise(row, true);
    }
    const user = currentUser(db, req, secret);
    if (user && (user.id === row.author_id || user.role === "admin")) {
      return serialise(row, true);
    }
    return serialise(row, false);
  });

  app.post("/api/briefs/:id/token", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const id = (req.params as { id: string }).id;
    const row = getBrief(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.author_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const exp = Math.floor(Date.now() / 1000) + VIEW_TTL_SECONDS;
    const token = signView(secret, {
      sub: String(user.id),
      scope: "briefs:read",
      brief_id: row.id,
      exp,
    });
    auditRecord(db, user.username, "brief.token_mint", `brief:${row.id}`);
    return { token, exp };
  });

  app.get("/api/briefs/:id/view", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const row = getBrief(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    const token = readBearer(req);
    if (!token) return reply.code(401).send({ error: "missing_token" });
    const result = verifyView(secret, token);
    if (!result.ok) return reply.code(401).send({ error: `bad_token:${result.reason}` });
    const claims = result.claims;
    if (!claims.scope.split(/[,\s]+/).includes("briefs:read")) {
      return reply.code(403).send({ error: "scope" });
    }
    if (claims.brief_id && claims.brief_id !== row.id) {
      return reply.code(403).send({ error: "scope_brief" });
    }
    return { brief: serialise(row, true), viewer: claims.sub };
  });

  app.get("/api/briefs/:id/comments", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const row = getBrief(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.public !== 1) {
      const user = currentUser(db, req, secret);
      if (!user || (user.id !== row.author_id && user.role !== "admin")) {
        return reply.code(403).send({ error: "forbidden" });
      }
    }
    const rows = db.query(
      "SELECT id, brief_id, author_id, body, created_at FROM brief_comments WHERE brief_id = ? ORDER BY id ASC LIMIT 200",
    ).all(row.id) as Array<{ id: number; brief_id: string; author_id: number; body: string; created_at: number }>;
    return { comments: rows };
  });

  app.post("/api/briefs/:id/comment", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const id = (req.params as { id: string }).id;
    const row = getBrief(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.public !== 1 && row.author_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const body = String(((req.body ?? {}) as { body?: string }).body ?? "").slice(0, COMMENT_MAX);
    if (!body.trim()) return reply.code(400).send({ error: "empty" });
    db.run(
      "INSERT INTO brief_comments (brief_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
      [row.id, user.id, body, Date.now()],
    );
    auditRecord(db, user.username, "brief.comment", `brief:${row.id}`);
    return { ok: true };
  });
}
