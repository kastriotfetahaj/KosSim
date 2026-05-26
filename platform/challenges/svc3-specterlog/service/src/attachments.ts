import type { Database } from "bun:sqlite";
import type { FastifyInstance } from "fastify";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { AttachmentRow } from "./db";
import { signDownload, verifyDownload } from "./tokens";
import { record as auditRecord } from "./audit";
import { currentUser, requireUser } from "./accounts";
import { getCase } from "./cases";

const MAX_UPLOAD_BYTES = 256 * 1024;
const SHARE_TTL_SECONDS = 6 * 3600;
const ACTOR_VALUES = new Set(["public", "case-team", "admin"]);

export function blobPath(dataDir: string, handle: string): string {
  return join(dataDir, "blobs", handle.slice(0, 2), handle);
}

export function getAttachment(db: Database, handle: string): AttachmentRow | null {
  return db.query(
    "SELECT handle, case_id, filename, content_type, size, sha256, tick, created_at FROM attachments WHERE handle = ?",
  ).get(handle) as AttachmentRow | null;
}

export function createAttachment(
  db: Database,
  dataDir: string,
  opts: {
    case_id: string;
    filename: string;
    content_type: string;
    body: Buffer;
    tick: number;
  },
): AttachmentRow {
  if (opts.body.length > MAX_UPLOAD_BYTES) {
    throw new Error("too_large");
  }
  const handleSeed = randomBytes(8).toString("hex");
  const handle = createHash("sha256")
    .update(`attach:${opts.case_id}:${handleSeed}:${Date.now()}`)
    .digest("hex")
    .slice(0, 24);
  const sha = createHash("sha256").update(opts.body).digest("hex");
  const path = blobPath(dataDir, handle);
  mkdirSync(join(dataDir, "blobs", handle.slice(0, 2)), { recursive: true });
  writeFileSync(path, opts.body);
  db.run(
    "INSERT INTO attachments (handle, case_id, filename, content_type, size, sha256, tick, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    [handle, opts.case_id, opts.filename, opts.content_type, opts.body.length, sha, opts.tick, Date.now()],
  );
  const row = getAttachment(db, handle);
  if (!row) throw new Error("attachment_create_failed");
  return row;
}

export function readBlob(dataDir: string, handle: string): Buffer | null {
  const path = blobPath(dataDir, handle);
  if (!existsSync(path)) return null;
  return readFileSync(path);
}

export function deleteAttachment(
  db: Database,
  dataDir: string,
  handle: string,
): void {
  const path = blobPath(dataDir, handle);
  if (existsSync(path)) unlinkSync(path);
  db.run("DELETE FROM attachments WHERE handle = ?", [handle]);
}

function metadata(row: AttachmentRow): Record<string, unknown> {
  return {
    handle: row.handle,
    case_id: row.case_id,
    filename: row.filename,
    content_type: row.content_type,
    size: row.size,
    sha256: row.sha256,
    created_at: row.created_at,
  };
}

export function mintShare(
  secret: string,
  row: AttachmentRow,
  ttl: number = SHARE_TTL_SECONDS,
): { sig: string; exp: number } {
  const exp = Math.floor(Date.now() / 1000) + ttl;
  const sig = signDownload(secret, {
    case_id: row.case_id,
    handle: row.handle,
    exp,
  });
  return { sig, exp };
}

export function attachmentRoutes(
  app: FastifyInstance,
  db: Database,
  secret: string,
  dataDir: string,
): void {
  app.post("/api/cases/:case_id/attachments", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const caseId = (req.params as { case_id: string }).case_id;
    const caseRow = getCase(db, caseId);
    if (!caseRow) return reply.code(404).send({ error: "case_not_found" });
    if (caseRow.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const body = (req.body ?? {}) as {
      filename?: string;
      content_type?: string;
      data?: string;
    };
    const filename = String(body.filename ?? "blob").replace(/[^a-zA-Z0-9_.\- ]/g, "_").slice(0, 120);
    const contentType = String(body.content_type ?? "application/octet-stream").slice(0, 80);
    const raw = String(body.data ?? "");
    if (!raw) return reply.code(400).send({ error: "missing_data" });
    let buf: Buffer;
    try {
      buf = Buffer.from(raw, "base64");
    } catch {
      return reply.code(400).send({ error: "bad_base64" });
    }
    try {
      const row = createAttachment(db, dataDir, {
        case_id: caseRow.id,
        filename,
        content_type: contentType,
        body: buf,
        tick: 0,
      });
      auditRecord(db, user.username, "attachment.upload", `attach:${row.handle}`);
      return metadata(row);
    } catch (err) {
      const code = err instanceof Error ? err.message : "error";
      const status = code === "too_large" ? 413 : 400;
      return reply.code(status).send({ error: code });
    }
  });

  app.get("/api/cases/:case_id/attachments", async (req, reply) => {
    const caseId = (req.params as { case_id: string }).case_id;
    const caseRow = getCase(db, caseId);
    if (!caseRow) return reply.code(404).send({ error: "case_not_found" });
    if (caseRow.public !== 1) {
      const user = currentUser(db, req, secret);
      if (!user || (user.id !== caseRow.owner_id && user.role !== "admin")) {
        return reply.code(403).send({ error: "forbidden" });
      }
    }
    const rows = db.query(
      "SELECT handle, case_id, filename, content_type, size, sha256, tick, created_at FROM attachments WHERE case_id = ? ORDER BY created_at DESC LIMIT 200",
    ).all(caseRow.id) as AttachmentRow[];
    return { attachments: rows.map(metadata) };
  });

  app.get("/api/cases/:case_id/attachments/:handle/raw", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const params = req.params as { case_id: string; handle: string };
    const row = getAttachment(db, params.handle);
    if (!row || row.case_id !== params.case_id) {
      return reply.code(404).send({ error: "not_found" });
    }
    const caseRow = getCase(db, row.case_id);
    if (!caseRow) return reply.code(404).send({ error: "case_not_found" });
    if (caseRow.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const buf = readBlob(dataDir, row.handle);
    if (!buf) return reply.code(410).send({ error: "blob_missing" });
    return reply.type(row.content_type).send(buf);
  });

  app.post("/api/cases/:case_id/attachments/:handle/share", async (req, reply) => {
    const user = requireUser(db, req, reply, secret);
    if (!user) return;
    const params = req.params as { case_id: string; handle: string };
    const row = getAttachment(db, params.handle);
    if (!row || row.case_id !== params.case_id) {
      return reply.code(404).send({ error: "not_found" });
    }
    const caseRow = getCase(db, row.case_id);
    if (!caseRow) return reply.code(404).send({ error: "case_not_found" });
    if (caseRow.owner_id !== user.id && user.role !== "admin") {
      return reply.code(403).send({ error: "forbidden" });
    }
    const body = (req.body ?? {}) as { actor?: string; ttl?: number };
    const requestedActor = String(body.actor ?? "public");
    if (!ACTOR_VALUES.has(requestedActor)) {
      return reply.code(400).send({ error: "bad_actor" });
    }
    const ttl = Math.max(60, Math.min(Number(body.ttl ?? SHARE_TTL_SECONDS), SHARE_TTL_SECONDS));
    const { sig, exp } = mintShare(secret, row, ttl);
    auditRecord(db, user.username, "attachment.share", `attach:${row.handle}`, requestedActor);
    const path = `/api/cases/${row.case_id}/attach/${row.handle}`;
    const url = `${path}?actor=${encodeURIComponent(requestedActor)}&exp=${exp}&sig=${sig}`;
    return {
      url,
      handle: row.handle,
      case_id: row.case_id,
      actor: requestedActor,
      exp,
      sig,
    };
  });

  app.get("/api/cases/:case_id/attach/:handle", async (req, reply) => {
    const params = req.params as { case_id: string; handle: string };
    const q = req.query as Record<string, string>;
    const exp = Number(q.exp ?? 0);
    const sig = String(q.sig ?? "");
    const actor = String(q.actor ?? "public");
    if (!exp || !sig) return reply.code(400).send({ error: "missing_params" });
    if (exp < Math.floor(Date.now() / 1000)) return reply.code(401).send({ error: "expired" });
    const row = getAttachment(db, params.handle);
    if (!row || row.case_id !== params.case_id) {
      return reply.code(404).send({ error: "not_found" });
    }
    const ok = verifyDownload(secret, {
      case_id: row.case_id,
      handle: row.handle,
      exp,
    }, sig);
    if (!ok) return reply.code(401).send({ error: "bad_sig" });
    if (actor === "admin") {
      const buf = readBlob(dataDir, row.handle);
      if (!buf) return reply.code(410).send({ error: "blob_missing" });
      return reply.type(row.content_type).send(buf);
    }
    return metadata(row);
  });
}
