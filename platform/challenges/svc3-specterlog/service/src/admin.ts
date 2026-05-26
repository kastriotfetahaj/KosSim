import type { Database } from "bun:sqlite";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { Store } from "./state";
import { currentUser } from "./accounts";
import { recent } from "./audit";
import type { UserRow } from "./db";

function requireAdmin(
  db: Database,
  req: FastifyRequest,
  reply: FastifyReply,
  secret: string,
): UserRow | null {
  const user = currentUser(db, req, secret);
  if (!user) {
    reply.code(401).send({ error: "auth_required" });
    return null;
  }
  if (user.role !== "admin") {
    reply.code(403).send({ error: "admin_only" });
    return null;
  }
  return user;
}

export function adminRoutes(
  app: FastifyInstance,
  db: Database,
  store: Store,
  secret: string,
): void {
  app.get("/api/admin/queue", async (req, reply) => {
    const user = requireAdmin(db, req, reply, secret);
    if (!user) return;
    const counts = {
      events: store.countEvents(),
      cases: Number((db.query("SELECT COUNT(*) AS n FROM cases").get() as { n: number }).n ?? 0),
      briefs: Number((db.query("SELECT COUNT(*) AS n FROM briefs").get() as { n: number }).n ?? 0),
      attachments: Number((db.query("SELECT COUNT(*) AS n FROM attachments").get() as { n: number }).n ?? 0),
      users: Number((db.query("SELECT COUNT(*) AS n FROM users").get() as { n: number }).n ?? 0),
    };
    return { ...counts, ts: Date.now() };
  });

  app.get("/api/admin/accounts", async (req, reply) => {
    const user = requireAdmin(db, req, reply, secret);
    if (!user) return;
    const rows = db.query(
      "SELECT id, username, role, created_at FROM users ORDER BY id DESC LIMIT 200",
    ).all() as Array<{ id: number; username: string; role: string; created_at: number }>;
    return { accounts: rows };
  });

  app.get("/api/admin/audit", async (req, reply) => {
    const user = requireAdmin(db, req, reply, secret);
    if (!user) return;
    const q = req.query as Record<string, string>;
    return { entries: recent(db, Number(q.limit ?? 100)) };
  });

  app.post("/api/admin/rotate-cursor", async (req, reply) => {
    const user = requireAdmin(db, req, reply, secret);
    if (!user) return;
    store.rotateCursorSalt();
    return { ok: true, salt_bumped: true };
  });
}
