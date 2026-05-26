use std::path::{Path, PathBuf};
use std::sync::Arc;

use rusqlite::{Connection, params};
use tokio::sync::Mutex;

pub type Pool = Arc<Mutex<Connection>>;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    class_name TEXT NOT NULL,
    owner TEXT NOT NULL,
    body TEXT NOT NULL,
    public INTEGER NOT NULL DEFAULT 0,
    snapshot TEXT NOT NULL,
    tick INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_path ON docs (path);
CREATE INDEX IF NOT EXISTS idx_docs_public ON docs (public);
CREATE INDEX IF NOT EXISTS idx_docs_class ON docs (class_name);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    public_label TEXT NOT NULL,
    doc_ids TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

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

CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    branch TEXT NOT NULL,
    body TEXT NOT NULL,
    public_scope TEXT NOT NULL DEFAULT 'public',
    public_token TEXT NOT NULL,
    tick INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settlements_branch ON settlements (branch);

CREATE TABLE IF NOT EXISTS treasury_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    body TEXT NOT NULL,
    scope TEXT NOT NULL,
    tick INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS treasury_viewers (
    key TEXT PRIMARY KEY,
    scopes TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    class TEXT PRIMARY KEY,
    max_body_bytes INTEGER NOT NULL DEFAULT 16384,
    retention_ticks INTEGER NOT NULL DEFAULT 16,
    allowed_signers TEXT NOT NULL DEFAULT 'cli,analyst',
    updated_at INTEGER NOT NULL
);

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

CREATE TABLE IF NOT EXISTS replicas (
    peer TEXT PRIMARY KEY,
    last_seen_at INTEGER NOT NULL,
    cursor TEXT NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts);

CREATE TABLE IF NOT EXISTS rate_buckets (
    key TEXT PRIMARY KEY,
    tokens REAL NOT NULL,
    refilled_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"#;

pub fn data_dir() -> PathBuf {
    std::env::var("LEDGERFORGE_DATA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/var/lib/ledgerforge"))
}

pub fn open_at(path: &Path) -> rusqlite::Result<Connection> {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let conn = Connection::open(path)?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.pragma_update(None, "busy_timeout", 5000)?;
    conn.execute_batch(SCHEMA)?;
    seed(&conn)?;
    Ok(conn)
}

pub fn open() -> rusqlite::Result<Connection> {
    open_at(&data_dir().join("state.db"))
}

fn seed(conn: &Connection) -> rusqlite::Result<()> {
    let exists: i64 = conn
        .query_row("SELECT COUNT(*) FROM docs WHERE id = ?1", params!["welcome-ledger"], |row| row.get(0))
        .unwrap_or(0);
    if exists == 0 {
        let now = now_ms();
        conn.execute(
            "INSERT INTO docs (id, path, class_name, owner, body, public, snapshot, tick, created_at) VALUES (?1, ?2, ?3, ?4, ?5, 1, ?6, 0, ?7)",
            params![
                "welcome-ledger",
                "/public/welcome",
                "public",
                "guest",
                "LedgerForge mirror online. Query window: 32 records.",
                "boot",
                now,
            ],
        )?;
        conn.execute(
            "INSERT INTO snapshots (id, public_label, doc_ids, created_at) VALUES (?1, ?2, ?3, ?4)",
            params!["boot", "boot-public", "[\"welcome-ledger\"]", now],
        )?;
        conn.execute(
            "INSERT OR IGNORE INTO treasury_viewers (key, scopes, created_at) VALUES (?1, ?2, ?3)",
            params!["public-viewer", "[]", now],
        )?;
        for (class, max_bytes, retention) in &[
            ("public", 65_536_i64, 16_i64),
            ("vault", 16_384_i64, 32_i64),
            ("settlement", 32_768_i64, 24_i64),
            ("treasury", 8_192_i64, 64_i64),
        ] {
            conn.execute(
                "INSERT OR IGNORE INTO policies (class, max_body_bytes, retention_ticks, allowed_signers, updated_at) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![class, max_bytes, retention, "cli,analyst", now],
            )?;
        }
    }
    Ok(())
}

pub fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

pub fn migrate_legacy_state(conn: &Connection, dir: &Path) -> rusqlite::Result<bool> {
    let legacy = dir.join("state.json");
    if !legacy.exists() {
        return Ok(false);
    }
    let raw = match std::fs::read_to_string(&legacy) {
        Ok(r) => r,
        Err(_) => return Ok(false),
    };
    #[derive(serde::Deserialize)]
    struct LegacyDoc {
        id: String,
        path: String,
        class_name: String,
        owner: String,
        body: String,
        public: bool,
        snapshot: String,
    }
    #[derive(serde::Deserialize)]
    struct LegacySnap {
        id: String,
        public_label: String,
        doc_ids: Vec<String>,
    }
    #[derive(serde::Deserialize)]
    struct LegacyFlag {
        tick: i64,
        payload: u8,
        value: String,
    }
    #[derive(serde::Deserialize)]
    struct Legacy {
        #[serde(default)]
        flags: Vec<LegacyFlag>,
        #[serde(default)]
        docs: std::collections::HashMap<String, LegacyDoc>,
        #[serde(default)]
        snapshots: std::collections::HashMap<String, LegacySnap>,
    }
    let parsed: Legacy = match serde_json::from_str(&raw) {
        Ok(p) => p,
        Err(_) => return Ok(false),
    };
    let now = now_ms();
    for (_, doc) in parsed.docs {
        conn.execute(
            "INSERT OR REPLACE INTO docs (id, path, class_name, owner, body, public, snapshot, tick, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 0, ?8)",
            params![doc.id, doc.path, doc.class_name, doc.owner, doc.body, doc.public as i64, doc.snapshot, now],
        )?;
    }
    for (_, snap) in parsed.snapshots {
        let ids = serde_json::to_string(&snap.doc_ids).unwrap_or_else(|_| "[]".to_string());
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (id, public_label, doc_ids, created_at) VALUES (?1, ?2, ?3, ?4)",
            params![snap.id, snap.public_label, ids, now],
        )?;
    }
    for f in parsed.flags {
        conn.execute(
            "INSERT OR REPLACE INTO flag_index (tick, variant, flag, ref) VALUES (?1, ?2, ?3, ?4)",
            params![f.tick, f.payload, f.value, "legacy"],
        )?;
    }
    let _ = std::fs::rename(&legacy, legacy.with_extension("json.bak"));
    Ok(true)
}

pub fn checkpoint(conn: &Connection) {
    let _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);", []);
}
