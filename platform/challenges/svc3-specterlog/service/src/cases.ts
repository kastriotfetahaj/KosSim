import type { Database } from "bun:sqlite";
import type { FastifyInstance } from "fastify";
import type { CaseRow } from "./db";
import { newId } from "./tokens";
import { record as auditRecord } from "./audit";
import { currentUser, requireUser } from "./accounts";

const TITLE_MAX = 120;
const SUMMARY_MAX = 2_000;

export function getCase(db: Database, id: string): CaseRow | null {
  return db.query(
    "SELECT id, owner_id, title, summary, public, created_at FROM cases WHERE id = ?",
  ).get(id) as CaseRow | null;
}

export function listCases(db: Database, opts: { mine?: number; publicOnly?: boolean; limit?: number }): CaseRow[] {
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
  if (opts.mine !== undefined && !opts.publicOnly) {
    return db.query(
      "SELECT id, owner_id, title, summary, public, created_at FROM cases WHERE owner_id = ? OR public = 1 ORDER BY created_at DESC LIMIT ?",
    ).all(opts.mine, limit) as CaseRow[];
  }
  return db.query(
    "SELECT id, owner_id, title, summary, public, created_at FROM cases WHERE public = 1 ORDER BY created_at DESC LIMIT ?",
  ).all(limit) as CaseRow[];
}

export function caseRoutes(
  app: FastifyInstance,
  db: Database,
  secret: string,
): void {
  app.get("/api/cases", async (req) => {
    const q = req.query as Record<string, string>;
    const user = currentUser(db, req, secret);
    const publicOnly = q.scope !== "mine";
    return {
      cases: listCases(db, {
        mine: user?.id,
        publicOnly,
        limit: Number(q.limit ?? 50),
      }).map(serialise),
    };
  });

  app.post("/api/cases", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const body = (req.body ?? {}) as { title?: string; summary?: string; public?: boolean };
    const title = String(body.title ?? "").slice(0, TITLE_MAX).trim();
    const summary = String(body.summary ?? "").slice(0, SUMMARY_MAX);
    if (!title) return reply.code(400).send({ error: "missing_title" });
    const id = newId("case");
    db.run(
      "INSERT INTO cases (id, owner_id, title, summary, public, created_at) VALUES (?, ?, ?, ?, ?, ?)",
      [id, user.id, title, summary, body.public ? 1 : 0, Date.now()],
    );
    auditRecord(db, user.username, "case.create", `case:${id}`);
    const created = getCase(db, id);
    if (!created) return reply.code(500).send({ error: "create_failed" });
    return serialise(created);
  });

  app.get("/api/cases/:id", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const row = getCase(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.public !== 1) {
      const user = requireUser(db, req, reply, secret);
      if (!user) return;
      if (row.owner_id !== user.id && user.role !== "admin") {
        return reply.code(403).send({ error: "forbidden" });
      }
    }
    return serialise(row);
  });

  app.patch("/api/cases/:id", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const id = (req.params as { id: string }).id;
    const row = getCase(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const body = (req.body ?? {}) as { title?: string; summary?: string };
    const title = body.title !== undefined ? String(body.title).slice(0, TITLE_MAX).trim() : row.title;
    const summary = body.summary !== undefined ? String(body.summary).slice(0, SUMMARY_MAX) : row.summary;
    db.run("UPDATE cases SET title = ?, summary = ? WHERE id = ?", [title, summary, id]);
    auditRecord(db, user.username, "case.update", `case:${id}`);
    const updated = getCase(db, id);
    if (!updated) return reply.code(500).send({ error: "update_failed" });
    return serialise(updated);
  });

  app.post("/api/cases/:id/publish", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const id = (req.params as { id: string }).id;
    const row = getCase(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    db.run("UPDATE cases SET public = 1 WHERE id = ?", [id]);
    auditRecord(db, user.username, "case.publish", `case:${id}`);
    return { ok: true };
  });

  app.post("/api/cases/:id/unpublish", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const id = (req.params as { id: string }).id;
    const row = getCase(db, id);
    if (!row) return reply.code(404).send({ error: "not_found" });
    if (row.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    db.run("UPDATE cases SET public = 0 WHERE id = ?", [id]);
    auditRecord(db, user.username, "case.unpublish", `case:${id}`);
    return { ok: true };
  });
}

function serialise(row: CaseRow): Record<string, unknown> {
  return {
    id: row.id,
    owner: row.owner_id,
    title: row.title,
    summary: row.summary,
    public: row.public === 1,
    created_at: row.created_at,
  };
}
