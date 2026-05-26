import type { Database } from "bun:sqlite";
import type { FastifyInstance, FastifyRequest } from "fastify";
import { randomBytes } from "node:crypto";
import type { ApiTokenRow, UserRow } from "./db";
import { findUserById } from "./accounts";
import { requireUser } from "./accounts";
import { record as auditRecord } from "./audit";

const VALID_SCOPES = new Set([
  "briefs:read",
  "briefs:write",
  "cases:read",
  "cases:write",
  "attachments:read",
  "audit:read",
]);

export function mintApiToken(
  db: Database,
  user: UserRow,
  scopes: string[],
  label: string,
  ttlSeconds: number,
): ApiTokenRow {
  const cleanScopes = scopes
    .map((s) => s.trim())
    .filter((s) => VALID_SCOPES.has(s));
  if (cleanScopes.length === 0) throw new Error("no_scopes");
  const token = `sltok_${randomBytes(24).toString("base64url")}`;
  const now = Date.now();
  db.run(
    "INSERT INTO api_tokens (token, user_id, scopes, label, created_at, expires_at, revoked) VALUES (?, ?, ?, ?, ?, ?, 0)",
    [token, user.id, cleanScopes.join(","), label.slice(0, 80), now, now + ttlSeconds * 1000],
  );
  return db.query(
    "SELECT token, user_id, scopes, label, created_at, expires_at, revoked FROM api_tokens WHERE token = ?",
  ).get(token) as ApiTokenRow;
}

export function readBearer(req: FastifyRequest): string | null {
  const raw = req.headers["authorization"];
  if (typeof raw !== "string") return null;
  const m = raw.match(/^Bearer\s+(.+)$/);
  return m ? m[1].trim() : null;
}

export function findApiToken(db: Database, token: string): ApiTokenRow | null {
  return db.query(
    "SELECT token, user_id, scopes, label, created_at, expires_at, revoked FROM api_tokens WHERE token = ?",
  ).get(token) as ApiTokenRow | null;
}

export function resolveTokenUser(
  db: Database,
  req: FastifyRequest,
  requiredScope: string,
): UserRow | null {
  const token = readBearer(req);
  if (!token || !token.startsWith("sltok_")) return null;
  const row = findApiToken(db, token);
  if (!row || row.revoked === 1) return null;
  if (row.expires_at < Date.now()) return null;
  const scopes = row.scopes.split(",");
  if (!scopes.includes(requiredScope)) return null;
  return findUserById(db, row.user_id);
}

function serialise(row: ApiTokenRow, revealToken: boolean): Record<string, unknown> {
  return {
    token: revealToken ? row.token : `${row.token.slice(0, 12)}…`,
    label: row.label,
    scopes: row.scopes.split(","),
    created_at: row.created_at,
    expires_at: row.expires_at,
    revoked: row.revoked === 1,
  };
}

export function apiTokenRoutes(
  app: FastifyInstance,
  db: Database,
  secret: string,
): void {
  app.post("/api/tokens", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const body = (req.body ?? {}) as {
      scopes?: string[];
      label?: string;
      ttl?: number;
    };
    const scopes = Array.isArray(body.scopes) ? body.scopes : [];
    const label = String(body.label ?? "");
    const ttl = Math.max(60, Math.min(Number(body.ttl ?? 86400), 7 * 86400));
    try {
      const row = mintApiToken(db, user, scopes, label, ttl);
      auditRecord(db, user.username, "apitoken.mint", `token:${row.token.slice(0, 12)}`);
      return serialise(row, true);
    } catch (err) {
      const code = err instanceof Error ? err.message : "error";
      return reply.code(400).send({ error: code });
    }
  });

  app.get("/api/tokens", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const rows = db.query(
      "SELECT token, user_id, scopes, label, created_at, expires_at, revoked FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
    ).all(user.id) as ApiTokenRow[];
    return { tokens: rows.map((r) => serialise(r, false)) };
  });

  app.delete("/api/tokens/:prefix", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const prefix = (req.params as { prefix: string }).prefix;
    const row = db.query(
      "SELECT token FROM api_tokens WHERE user_id = ? AND token LIKE ?",
    ).get(user.id, `${prefix}%`) as { token: string } | null;
    if (!row) return reply.code(404).send({ error: "not_found" });
    db.run("UPDATE api_tokens SET revoked = 1 WHERE token = ?", [row.token]);
    auditRecord(db, user.username, "apitoken.revoke", `token:${prefix}`);
    return { ok: true };
  });
}
