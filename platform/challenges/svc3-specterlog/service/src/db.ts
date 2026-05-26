import { Database } from "bun:sqlite";
import { existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  public INTEGER NOT NULL DEFAULT 0,
  archive TEXT NOT NULL,
  payload INTEGER NOT NULL DEFAULT 0,
  tick INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_stream ON events (stream, id);
CREATE INDEX IF NOT EXISTS idx_events_archive ON events (archive);
CREATE INDEX IF NOT EXISTS idx_events_public ON events (public, id);

CREATE TABLE IF NOT EXISTS flag_index (
  tick INTEGER NOT NULL,
  variant INTEGER NOT NULL,
  flag TEXT NOT NULL,
  ref TEXT NOT NULL,
  PRIMARY KEY (tick, variant)
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'analyst',
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  owner_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  public INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_cases_owner ON cases (owner_id);
CREATE INDEX IF NOT EXISTS idx_cases_public ON cases (public);

CREATE TABLE IF NOT EXISTS briefs (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  author_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  public INTEGER NOT NULL DEFAULT 0,
  tick INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (case_id) REFERENCES cases (id),
  FOREIGN KEY (author_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_briefs_case ON briefs (case_id);
CREATE INDEX IF NOT EXISTS idx_briefs_author ON briefs (author_id);

CREATE TABLE IF NOT EXISTS brief_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brief_id TEXT NOT NULL,
  author_id INTEGER NOT NULL,
  body TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (brief_id) REFERENCES briefs (id),
  FOREIGN KEY (author_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_brief_comments_brief ON brief_comments (brief_id, id);

CREATE TABLE IF NOT EXISTS attachments (
  handle TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  tick INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (case_id) REFERENCES cases (id)
);

CREATE INDEX IF NOT EXISTS idx_attachments_case ON attachments (case_id);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts);

CREATE TABLE IF NOT EXISTS api_tokens (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  scopes TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens (user_id);

CREATE TABLE IF NOT EXISTS rate_buckets (
  key TEXT PRIMARY KEY,
  tokens REAL NOT NULL,
  refilled_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
`;

export type EventRow = {
  id: number;
  stream: string;
  kind: string;
  body: string;
  public: number;
  archive: string;
  payload: number;
  tick: number;
  created_at: number;
};

export type UserRow = {
  id: number;
  username: string;
  password_hash: string;
  role: string;
  created_at: number;
};

export type SessionRow = {
  token: string;
  user_id: number;
  expires_at: number;
};

export type CaseRow = {
  id: string;
  owner_id: number;
  title: string;
  summary: string;
  public: number;
  created_at: number;
};

export type BriefRow = {
  id: string;
  case_id: string;
  author_id: number;
  title: string;
  body: string;
  public: number;
  tick: number;
  created_at: number;
};

export type AttachmentRow = {
  handle: string;
  case_id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  tick: number;
  created_at: number;
};

export type ApiTokenRow = {
  token: string;
  user_id: number;
  scopes: string;
  label: string;
  created_at: number;
  expires_at: number;
  revoked: number;
};

export type AuditRow = {
  id: number;
  actor: string;
  action: string;
  target: string;
  detail: string;
  ts: number;
};

export function openDatabase(path: string): Database {
  mkdirSync(dirname(path), { recursive: true });
  const created = !existsSync(path);
  const db = new Database(path, { create: true });
  db.exec("PRAGMA journal_mode=WAL;");
  db.exec("PRAGMA synchronous=NORMAL;");
  db.exec("PRAGMA foreign_keys=ON;");
  db.exec("PRAGMA busy_timeout=5000;");
  db.exec(SCHEMA);
  if (created) {
    db.run(
      "INSERT INTO kv (k, v) VALUES (?, ?)",
      ["schema_version", "1"],
    );
  }
  return db;
}

export function kvGet(db: Database, key: string): string | null {
  const row = db.query("SELECT v FROM kv WHERE k = ?").get(key) as { v: string } | null;
  return row ? row.v : null;
}

export function kvPut(db: Database, key: string, value: string): void {
  db.run("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", [key, value]);
}

export function closeDatabase(db: Database): void {
  try {
    db.exec("PRAGMA wal_checkpoint(TRUNCATE);");
  } finally {
    db.close();
  }
}
