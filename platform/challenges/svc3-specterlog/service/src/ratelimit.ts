import type { Database } from "bun:sqlite";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

export type Bucket = {
  capacity: number;
  refillPerSecond: number;
};

const DEFAULTS: Record<string, Bucket> = {
  default: { capacity: 60, refillPerSecond: 1.0 },
  auth: { capacity: 10, refillPerSecond: 0.2 },
  upload: { capacity: 12, refillPerSecond: 0.5 },
};

function clientKey(req: FastifyRequest, route: string): string {
  const forwarded = req.headers["x-forwarded-for"];
  const ip = Array.isArray(forwarded)
    ? forwarded[0]
    : (typeof forwarded === "string" ? forwarded.split(",")[0].trim() : null)
      ?? (req.ip ?? "unknown");
  return `${ip}|${route}`;
}

export function consume(
  db: Database,
  key: string,
  bucket: Bucket,
): { ok: boolean; remaining: number; retry_after: number } {
  const now = Date.now();
  const row = db.query(
    "SELECT tokens, refilled_at FROM rate_buckets WHERE key = ?",
  ).get(key) as { tokens: number; refilled_at: number } | null;
  let tokens = row ? row.tokens : bucket.capacity;
  const last = row ? row.refilled_at : now;
  const elapsed = Math.max(0, now - last) / 1000;
  tokens = Math.min(bucket.capacity, tokens + elapsed * bucket.refillPerSecond);
  if (tokens < 1) {
    db.run(
      "INSERT OR REPLACE INTO rate_buckets (key, tokens, refilled_at) VALUES (?, ?, ?)",
      [key, tokens, now],
    );
    const deficit = 1 - tokens;
    const retry = bucket.refillPerSecond > 0 ? Math.ceil(deficit / bucket.refillPerSecond) : 60;
    return { ok: false, remaining: 0, retry_after: retry };
  }
  tokens -= 1;
  db.run(
    "INSERT OR REPLACE INTO rate_buckets (key, tokens, refilled_at) VALUES (?, ?, ?)",
    [key, tokens, now],
  );
  return { ok: true, remaining: Math.floor(tokens), retry_after: 0 };
}

export function enforce(
  db: Database,
  req: FastifyRequest,
  reply: FastifyReply,
  route: string,
  bucketName: string = "default",
): boolean {
  const bucket = DEFAULTS[bucketName] ?? DEFAULTS.default;
  const result = consume(db, clientKey(req, route), bucket);
  if (!result.ok) {
    reply.code(429).header("retry-after", String(result.retry_after)).send({
      error: "rate_limited",
      retry_after: result.retry_after,
    });
    return false;
  }
  reply.header("x-ratelimit-remaining", String(result.remaining));
  return true;
}

export function rateRoutes(app: FastifyInstance, db: Database): void {
  app.get("/api/rate-limit/status", async (req) => {
    const key = clientKey(req, "status");
    const row = db.query(
      "SELECT tokens, refilled_at FROM rate_buckets WHERE key = ?",
    ).get(key) as { tokens: number; refilled_at: number } | null;
    const bucket = DEFAULTS.default;
    const now = Date.now();
    const tokens = row
      ? Math.min(bucket.capacity, row.tokens + Math.max(0, now - row.refilled_at) / 1000 * bucket.refillPerSecond)
      : bucket.capacity;
    return {
      bucket: "default",
      capacity: bucket.capacity,
      remaining: Math.floor(tokens),
      refill_per_second: bucket.refillPerSecond,
    };
  });

  app.addHook("onRequest", async (req, reply) => {
    const url = req.url ?? "";
    if (url.startsWith("/api/accounts/register") || url.startsWith("/api/accounts/login")) {
      if (!enforce(db, req, reply, "auth", "auth")) return;
    } else if (url.includes("/attachments") && req.method === "POST") {
      if (!enforce(db, req, reply, "upload", "upload")) return;
    } else if (url === "/" && req.method === "POST") {
      // checker RPC; auth is the secret header
      return;
    } else if (url.startsWith("/api/")) {
      if (!enforce(db, req, reply, "default", "default")) return;
    }
  });
}
