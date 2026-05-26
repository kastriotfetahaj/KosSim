import type { Database } from "bun:sqlite";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import type { UserRow } from "./db";
import { signSession, verifySession } from "./tokens";
import { record as auditRecord } from "./audit";

const SESSION_COOKIE = "sl_session";
const SESSION_TTL_SECONDS = 4 * 3600;
const USERNAME_RE = /^[a-zA-Z0-9_.-]{3,32}$/;

function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const key = scryptSync(password, salt, 32, { N: 16384, r: 8, p: 1 });
  return `scrypt$16384$8$1$${salt.toString("hex")}$${key.toString("hex")}`;
}

function verifyPassword(stored: string, password: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 6 || parts[0] !== "scrypt") return false;
  const N = Number(parts[1]);
  const r = Number(parts[2]);
  const p = Number(parts[3]);
  const salt = Buffer.from(parts[4], "hex");
  const want = Buffer.from(parts[5], "hex");
  const got = scryptSync(password, salt, want.length, { N, r, p });
  if (got.length !== want.length) return false;
  return timingSafeEqual(got, want);
}

export function createUser(
  db: Database,
  username: string,
  password: string,
  role: string = "analyst",
): UserRow {
  if (!USERNAME_RE.test(username)) {
    throw new Error("invalid_username");
  }
  if (password.length < 8) {
    throw new Error("weak_password");
  }
  const existing = db.query("SELECT id FROM users WHERE username = ?").get(username);
  if (existing) throw new Error("duplicate");
  db.run(
    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
    [username, hashPassword(password), role, Date.now()],
  );
  const row = db.query(
    "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?",
  ).get(username) as UserRow;
  auditRecord(db, username, "user.register", `user:${row.id}`);
  return row;
}

export function findUser(db: Database, username: string): UserRow | null {
  return db.query(
    "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?",
  ).get(username) as UserRow | null;
}

export function findUserById(db: Database, id: number): UserRow | null {
  return db.query(
    "SELECT id, username, password_hash, role, created_at FROM users WHERE id = ?",
  ).get(id) as UserRow | null;
}

export function authenticate(
  db: Database,
  username: string,
  password: string,
): UserRow | null {
  const user = findUser(db, username);
  if (!user) return null;
  if (!verifyPassword(user.password_hash, password)) return null;
  return user;
}

function issueSession(db: Database, user: UserRow, secret: string): {
  cookie: string;
  expires: number;
} {
  const expires = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const cookie = signSession(secret, { uid: user.id, exp: expires });
  db.run(
    "INSERT OR REPLACE INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
    [cookie, user.id, expires],
  );
  return { cookie, expires };
}

function readCookie(req: FastifyRequest, name: string): string | null {
  const raw = req.headers["cookie"];
  if (typeof raw !== "string") return null;
  for (const part of raw.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(`${name}=`)) {
      return decodeURIComponent(trimmed.slice(name.length + 1));
    }
  }
  return null;
}

export function currentUser(
  db: Database,
  req: FastifyRequest,
  secret: string,
): UserRow | null {
  const cookie = readCookie(req, SESSION_COOKIE);
  if (!cookie) return null;
  const claim = verifySession(secret, cookie);
  if (!claim) return null;
  const row = db.query(
    "SELECT token FROM sessions WHERE token = ? AND expires_at > ?",
  ).get(cookie, Math.floor(Date.now() / 1000));
  if (!row) return null;
  return findUserById(db, claim.uid);
}

export function requireUser(
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
  return user;
}

export function accountRoutes(
  app: FastifyInstance,
  db: Database,
  secret: string,
): void {
  app.post("/api/accounts/register", async (req, reply) => {
    const body = (req.body ?? {}) as { username?: string; password?: string };
    const username = String(body.username ?? "").trim();
    const password = String(body.password ?? "");
    if (!username || !password) {
      return reply.code(400).send({ error: "missing_fields" });
    }
    try {
      const user = createUser(db, username, password);
      const session = issueSession(db, user, secret);
      reply.header(
        "set-cookie",
        `${SESSION_COOKIE}=${encodeURIComponent(session.cookie)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${SESSION_TTL_SECONDS}`,
      );
      return { id: user.id, username: user.username, role: user.role };
    } catch (err) {
      const code = err instanceof Error ? err.message : "error";
      const status = code === "duplicate" ? 409 : 400;
      return reply.code(status).send({ error: code });
    }
  });

  app.post("/api/accounts/login", async (req, reply) => {
    const body = (req.body ?? {}) as { username?: string; password?: string };
    const username = String(body.username ?? "").trim();
    const password = String(body.password ?? "");
    const user = authenticate(db, username, password);
    if (!user) {
      auditRecord(db, username || "unknown", "user.login_failed", `user:${username}`);
      return reply.code(401).send({ error: "bad_credentials" });
    }
    const session = issueSession(db, user, secret);
    reply.header(
      "set-cookie",
      `${SESSION_COOKIE}=${encodeURIComponent(session.cookie)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${SESSION_TTL_SECONDS}`,
    );
    auditRecord(db, user.username, "user.login", `user:${user.id}`);
    return { id: user.id, username: user.username, role: user.role };
  });

  app.get("/api/accounts/me", async (req, reply) => {
    const user = currentUser(db, req, secret);
    if (!user) return reply.code(401).send({ error: "auth_required" });
    return { id: user.id, username: user.username, role: user.role };
  });

  app.post("/api/accounts/logout", async (req, reply) => {
    const cookie = readCookie(req, SESSION_COOKIE);
    if (cookie) {
      db.run("DELETE FROM sessions WHERE token = ?", [cookie]);
    }
    reply.header(
      "set-cookie",
      `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`,
    );
    return { ok: true };
  });
}
