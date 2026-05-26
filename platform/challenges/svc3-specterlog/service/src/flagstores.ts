import type { Database } from "bun:sqlite";
import { randomBytes } from "node:crypto";
import type { Store } from "./state";
import type { UserRow, CaseRow, BriefRow, AttachmentRow } from "./db";
import { createUser, findUser } from "./accounts";
import { createBrief, getBrief } from "./briefs";
import { getCase } from "./cases";
import { createAttachment, mintShare, readBlob } from "./attachments";
import { newId } from "./tokens";

const SYSTEM_USERNAME = "specterlog";
const SYSTEM_PASSWORD_LEN = 32;

function ensureSystemUser(db: Database): UserRow {
  const existing = findUser(db, SYSTEM_USERNAME);
  if (existing) return existing;
  const pw = randomBytes(SYSTEM_PASSWORD_LEN).toString("base64url");
  return createUser(db, SYSTEM_USERNAME, pw, "admin");
}

function ensureSystemCase(db: Database, owner: UserRow, slot: string): CaseRow {
  const slug = `system_${slot}`;
  const row = db.query(
    "SELECT id, owner_id, title, summary, public, created_at FROM cases WHERE id = ?",
  ).get(slug) as CaseRow | null;
  if (row) return row;
  db.run(
    "INSERT INTO cases (id, owner_id, title, summary, public, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    [slug, owner.id, `internal:${slot}`, "system bookkeeping", 0, Date.now()],
  );
  const created = getCase(db, slug);
  if (!created) throw new Error("system_case_create_failed");
  return created;
}

function indexFlag(
  db: Database,
  tick: number,
  variant: number,
  flag: string,
  ref: Record<string, unknown>,
): void {
  db.run(
    "INSERT OR REPLACE INTO flag_index (tick, variant, flag, ref) VALUES (?, ?, ?, ?)",
    [tick, variant, flag, JSON.stringify(ref)],
  );
}

function indexed(
  db: Database,
  tick: number,
  variant: number,
): { flag: string; ref: string } | null {
  return db.query(
    "SELECT flag, ref FROM flag_index WHERE tick = ? AND variant = ?",
  ).get(tick, variant) as { flag: string; ref: string } | null;
}

export type AttackInfo = Record<string, unknown>;

export function putFlag(
  db: Database,
  store: Store,
  secret: string,
  dataDir: string,
  tick: number,
  variant: number,
  flag: string,
): AttackInfo {
  if (variant === 0) {
    const { event_id, archive } = store.putIncident(tick, flag);
    indexFlag(db, tick, 0, flag, { event_id, archive });
    return { a: event_id, b: archive, p: 0 };
  }
  if (variant === 1) {
    const system = ensureSystemUser(db);
    const caseRow = ensureSystemCase(db, system, "evidence");
    const row = createAttachment(db, dataDir, {
      case_id: caseRow.id,
      filename: `evidence-${tick}.bin`,
      content_type: "application/octet-stream",
      body: Buffer.from(flag, "utf8"),
      tick,
    });
    const share = mintShare(secret, row);
    indexFlag(db, tick, 1, flag, {
      case_id: row.case_id,
      handle: row.handle,
    });
    return {
      a: row.case_id,
      b: row.handle,
      p: 1,
      exp: share.exp,
      sig: share.sig,
      actor: "public",
    };
  }
  if (variant === 2) {
    const system = ensureSystemUser(db);
    const caseRow = ensureSystemCase(db, system, "directives");
    const brief = createBrief(db, {
      case_id: caseRow.id,
      author_id: system.id,
      title: `directive ${tick}`,
      body: flag,
      public: false,
      tick,
    });
    indexFlag(db, tick, 2, flag, {
      brief_id: brief.id,
      case_id: brief.case_id,
    });
    return { a: brief.id, b: brief.case_id, p: 2 };
  }
  throw new Error(`unknown_variant:${variant}`);
}

export function getFlag(
  db: Database,
  store: Store,
  dataDir: string,
  tick: number,
  variant: number,
  expected: string,
): boolean {
  const row = indexed(db, tick, variant);
  if (!row) return false;
  if (row.flag !== expected) return false;
  let ref: Record<string, unknown>;
  try {
    ref = JSON.parse(row.ref) as Record<string, unknown>;
  } catch {
    return false;
  }
  if (variant === 0) {
    return store.getIncident(tick, expected);
  }
  if (variant === 1) {
    const handle = String(ref.handle ?? "");
    if (!handle) return false;
    const buf = readBlob(dataDir, handle);
    if (!buf) return false;
    return buf.toString("utf8") === expected;
  }
  if (variant === 2) {
    const briefId = String(ref.brief_id ?? "");
    if (!briefId) return false;
    const brief = getBrief(db, briefId) as BriefRow | null;
    return !!brief && brief.body === expected;
  }
  return false;
}

export function putNoise(
  db: Database,
  store: Store,
  dataDir: string,
  tick: number,
  variant: number,
): boolean {
  if (variant === 0) {
    store.putNoiseEvent(tick, variant);
    return true;
  }
  if (variant === 1) {
    const system = ensureSystemUser(db);
    const caseRow = ensureSystemCase(db, system, "noise-public");
    if (!caseRow.public) {
      db.run("UPDATE cases SET public = 1 WHERE id = ?", [caseRow.id]);
    }
    createAttachment(db, dataDir, {
      case_id: caseRow.id,
      filename: `noise-${tick}.txt`,
      content_type: "text/plain",
      body: Buffer.from(`noise:${tick}:${variant}`, "utf8"),
      tick,
    });
    return true;
  }
  if (variant === 2) {
    const system = ensureSystemUser(db);
    const caseRow = ensureSystemCase(db, system, "noise-public");
    if (!caseRow.public) {
      db.run("UPDATE cases SET public = 1 WHERE id = ?", [caseRow.id]);
    }
    createBrief(db, {
      case_id: caseRow.id,
      author_id: system.id,
      title: `public note ${tick}`,
      body: `noise:${tick}:${variant}`,
      public: true,
      tick,
    });
    return true;
  }
  return false;
}

export function getNoise(
  db: Database,
  store: Store,
  dataDir: string,
  tick: number,
  variant: number,
): boolean {
  if (variant === 0) {
    return store.hasNoiseEvent(tick, variant);
  }
  if (variant === 1) {
    const row = db.query(
      "SELECT handle FROM attachments WHERE case_id = ? AND tick = ? AND filename = ?",
    ).get(`system_noise-public`, tick, `noise-${tick}.txt`) as { handle: string } | null;
    if (!row) return false;
    const buf = readBlob(dataDir, row.handle);
    return !!buf && buf.toString("utf8") === `noise:${tick}:${variant}`;
  }
  if (variant === 2) {
    const row = db.query(
      "SELECT id, body FROM briefs WHERE case_id = ? AND tick = ? AND public = 1 ORDER BY id DESC LIMIT 1",
    ).get(`system_noise-public`, tick) as { id: string; body: string } | null;
    return !!row && row.body === `noise:${tick}:${variant}`;
  }
  return false;
}

export function havoc(
  db: Database,
  store: Store,
  tick: number,
  variant: number,
): boolean {
  store.havocWalk(tick, variant);
  return store.countEvents() > 0;
}
