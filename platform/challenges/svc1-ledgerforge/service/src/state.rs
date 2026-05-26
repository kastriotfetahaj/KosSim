use std::collections::HashMap;

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};

use crate::{crypto, db, ledger};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Doc {
    pub id: String,
    pub path: String,
    pub class_name: String,
    pub owner: String,
    pub body: String,
    pub public: bool,
    pub snapshot: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Snapshot {
    pub id: String,
    pub public_label: String,
    pub doc_ids: Vec<String>,
}

pub struct AppState {
    pub team: String,
    pub service: String,
    pub checker_secret: String,
    pub data_dir: std::path::PathBuf,
    pub db: Connection,
    pub docs: HashMap<String, Doc>,
    pub path_index: HashMap<String, String>,
    pub snapshots: HashMap<String, Snapshot>,
    pub audit: Vec<String>,
}

impl AppState {
    pub fn new(team: String, service: String, checker_secret: String) -> Self {
        let data_dir = db::data_dir();
        let db_path = data_dir.join("state.db");
        let conn = db::open_at(&db_path).expect("open ledgerforge db");
        let _ = db::migrate_legacy_state(&conn, &data_dir);
        let mut state = Self {
            team,
            service,
            checker_secret,
            data_dir,
            db: conn,
            docs: HashMap::new(),
            path_index: HashMap::new(),
            snapshots: HashMap::new(),
            audit: Vec::new(),
        };
        state.reload();
        state
    }

    pub fn grant_key(&self) -> Vec<u8> {
        crypto::grant_key(&self.checker_secret, &self.team, &self.service)
    }

    pub fn session_key(&self) -> Vec<u8> {
        crypto::session_key(&self.checker_secret, &self.team)
    }

    pub fn settlement_secret(&self) -> String {
        crypto::settlement_secret(&self.checker_secret)
    }

    fn reload(&mut self) {
        self.docs.clear();
        self.path_index.clear();
        self.snapshots.clear();
        {
            let mut stmt = self
                .db
                .prepare("SELECT id, path, class_name, owner, body, public, snapshot FROM docs")
                .expect("prepare docs");
            let rows = stmt
                .query_map([], |row| {
                    Ok(Doc {
                        id: row.get(0)?,
                        path: row.get(1)?,
                        class_name: row.get(2)?,
                        owner: row.get(3)?,
                        body: row.get(4)?,
                        public: row.get::<_, i64>(5)? == 1,
                        snapshot: row.get(6)?,
                    })
                })
                .expect("query docs");
            for row in rows.flatten() {
                self.path_index.insert(row.path.clone(), row.id.clone());
                self.docs.insert(row.id.clone(), row);
            }
        }
        {
            let mut stmt = self
                .db
                .prepare("SELECT id, public_label, doc_ids FROM snapshots")
                .expect("prepare snapshots");
            let rows = stmt
                .query_map([], |row| {
                    let ids: String = row.get(2)?;
                    let parsed: Vec<String> = serde_json::from_str(&ids).unwrap_or_default();
                    Ok(Snapshot {
                        id: row.get(0)?,
                        public_label: row.get(1)?,
                        doc_ids: parsed,
                    })
                })
                .expect("query snapshots");
            for snap in rows.flatten() {
                self.snapshots.insert(snap.id.clone(), snap);
            }
        }
    }

    pub fn upsert_doc_external(&mut self, doc: &Doc, tick: i64) {
        self.upsert_doc(doc, tick);
    }

    fn upsert_doc(&mut self, doc: &Doc, tick: i64) {
        let now = db::now_ms();
        self.db
            .execute(
                "INSERT OR REPLACE INTO docs (id, path, class_name, owner, body, public, snapshot, tick, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
                params![
                    doc.id,
                    doc.path,
                    doc.class_name,
                    doc.owner,
                    doc.body,
                    doc.public as i64,
                    doc.snapshot,
                    tick,
                    now,
                ],
            )
            .ok();
        self.path_index.insert(doc.path.clone(), doc.id.clone());
        self.docs.insert(doc.id.clone(), doc.clone());
    }

    fn upsert_snapshot(&mut self, snap: &Snapshot) {
        let ids = serde_json::to_string(&snap.doc_ids).unwrap_or_else(|_| "[]".to_string());
        let now = db::now_ms();
        self.db
            .execute(
                "INSERT OR REPLACE INTO snapshots (id, public_label, doc_ids, created_at) VALUES (?1, ?2, ?3, ?4)",
                params![snap.id, snap.public_label, ids, now],
            )
            .ok();
        self.snapshots.insert(snap.id.clone(), snap.clone());
    }

    fn index_flag(&mut self, tick: i64, variant: u8, flag: &str, reference: &str) {
        self.db
            .execute(
                "INSERT OR REPLACE INTO flag_index (tick, variant, flag, ref) VALUES (?1, ?2, ?3, ?4)",
                params![tick, variant as i64, flag, reference],
            )
            .ok();
    }

    pub fn put_flag(&mut self, tick: i64, payload: u8, flag: &str) -> String {
        match payload {
            0 => self.put_flag_vault(tick, flag),
            1 => self.put_flag_settlement(tick, flag),
            2 => self.put_flag_treasury(tick, flag),
            _ => self.put_flag_vault(tick, flag),
        }
    }

    fn put_flag_vault(&mut self, tick: i64, flag: &str) -> String {
        let doc_id = crypto::short_hash(&format!("vault:{}:{tick}:{flag}", self.team));
        let path = format!("/vault/{doc_id}");
        let snap_id = crypto::short_hash(&format!("snap:{}:{tick}:{flag}", self.team));
        let doc = Doc {
            id: doc_id.clone(),
            path: path.clone(),
            class_name: "wire-transfer".to_string(),
            owner: "checker".to_string(),
            body: flag.to_string(),
            public: false,
            snapshot: snap_id.clone(),
        };
        self.upsert_doc(&doc, tick);
        let snapshot = Snapshot {
            id: snap_id.clone(),
            public_label: "public-ledger-delta".to_string(),
            doc_ids: vec![doc_id.clone()],
        };
        self.upsert_snapshot(&snapshot);
        let reference = serde_json::json!({"doc_id": doc_id, "snap_id": snap_id}).to_string();
        self.index_flag(tick, 0, flag, &reference);
        self.audit.push(format!("put:0:{tick}:{doc_id}:{}", ledger::merkle_root(&self.docs)));
        serde_json::json!({
            "a": doc_id,
            "b": snap_id,
            "c": "wire-transfer",
            "d": "guest-mirror",
            "t": tick,
            "p": 0
        })
        .to_string()
    }

    fn put_flag_settlement(&mut self, tick: i64, flag: &str) -> String {
        let id = crypto::random_id("stl");
        let viewer = "public";
        let token = crypto::sign_settlement_token(&self.settlement_secret(), &id, viewer.as_bytes());
        let now = db::now_ms();
        self.db
            .execute(
                "INSERT INTO settlements (id, branch, body, public_scope, public_token, tick, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![id, "settlement-note", flag, viewer, token, tick, now],
            )
            .ok();
        let reference = serde_json::json!({"settlement_id": id, "viewer": viewer, "token": token}).to_string();
        self.index_flag(tick, 1, flag, &reference);
        self.audit.push(format!("put:1:{tick}:{id}"));
        serde_json::json!({
            "a": id,
            "b": viewer,
            "token": token,
            "t": tick,
            "p": 1
        })
        .to_string()
    }

    fn put_flag_treasury(&mut self, tick: i64, flag: &str) -> String {
        let now = db::now_ms();
        self.db
            .execute(
                "INSERT INTO treasury_receipts (body, scope, tick, created_at) VALUES (?1, ?2, ?3, ?4)",
                params![flag, "treasury", tick, now],
            )
            .ok();
        let id: i64 = self.db.last_insert_rowid();
        self.db
            .execute(
                "INSERT OR IGNORE INTO treasury_viewers (key, scopes, created_at) VALUES (?1, ?2, ?3)",
                params!["public-viewer", "[]", now],
            )
            .ok();
        let reference = serde_json::json!({"receipt_id": id, "viewer_key": "public-viewer"}).to_string();
        self.index_flag(tick, 2, flag, &reference);
        self.audit.push(format!("put:2:{tick}:{id}"));
        serde_json::json!({
            "a": id,
            "b": "public-viewer",
            "t": tick,
            "p": 2
        })
        .to_string()
    }

    pub fn get_flag(&self, tick: i64, payload: u8, expected: &str) -> bool {
        let row: rusqlite::Result<String> = self.db.query_row(
            "SELECT flag FROM flag_index WHERE tick = ?1 AND variant = ?2",
            params![tick, payload as i64],
            |r| r.get(0),
        );
        match row {
            Ok(stored) if stored == expected => match payload {
                0 => self.docs.values().any(|d| d.body == expected),
                1 => self
                    .db
                    .query_row::<i64, _, _>(
                        "SELECT COUNT(*) FROM settlements WHERE body = ?1",
                        params![expected],
                        |r| r.get(0),
                    )
                    .map(|n| n > 0)
                    .unwrap_or(false),
                2 => self
                    .db
                    .query_row::<i64, _, _>(
                        "SELECT COUNT(*) FROM treasury_receipts WHERE body = ?1",
                        params![expected],
                        |r| r.get(0),
                    )
                    .map(|n| n > 0)
                    .unwrap_or(false),
                _ => false,
            },
            _ => false,
        }
    }

    pub fn put_noise(&mut self, tick: i64, payload: u8) -> String {
        match payload {
            0 => self.put_noise_doc(tick, payload),
            1 => self.put_noise_settlement(tick),
            2 => self.put_noise_treasury(tick),
            _ => self.put_noise_doc(tick, payload),
        }
    }

    fn put_noise_doc(&mut self, tick: i64, payload: u8) -> String {
        let doc_id = crypto::short_hash(&format!("noise:{}:{tick}:{payload}", self.team));
        let body = format!(
            "sample:{}:{tick}:{payload}:{}",
            self.service,
            ledger::merkle_root(&self.docs)
        );
        let path = format!("/public/noise/{doc_id}");
        let doc = Doc {
            id: doc_id.clone(),
            path: path.clone(),
            class_name: "public".to_string(),
            owner: "noise".to_string(),
            body,
            public: true,
            snapshot: "noise".to_string(),
        };
        self.upsert_doc(&doc, tick);
        doc_id
    }

    fn put_noise_settlement(&mut self, tick: i64) -> String {
        let id = crypto::random_id("stlnoise");
        let body = format!("settlement-noise:{}:{tick}", self.service);
        let viewer = "public";
        let token = crypto::sign_settlement_token(&self.settlement_secret(), &id, viewer.as_bytes());
        let now = db::now_ms();
        self.db
            .execute(
                "INSERT INTO settlements (id, branch, body, public_scope, public_token, tick, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![id, "public-noise", body, viewer, token, tick, now],
            )
            .ok();
        id
    }

    fn put_noise_treasury(&mut self, tick: i64) -> String {
        let body = format!("treasury-noise:{}:{tick}", self.service);
        let scope = format!("noise:{tick}");
        let now = db::now_ms();
        self.db
            .execute(
                "INSERT INTO treasury_receipts (body, scope, tick, created_at) VALUES (?1, ?2, ?3, ?4)",
                params![body, scope, tick, now],
            )
            .ok();
        let id = self.db.last_insert_rowid();
        let scopes = serde_json::to_string(&vec![scope.clone()]).unwrap_or_else(|_| "[]".to_string());
        let viewer_key = format!("noise-viewer-{tick}");
        self.db
            .execute(
                "INSERT OR REPLACE INTO treasury_viewers (key, scopes, created_at) VALUES (?1, ?2, ?3)",
                params![viewer_key, scopes, now],
            )
            .ok();
        format!("{id}|{viewer_key}")
    }

    pub fn get_noise(&self, tick: i64, payload: u8) -> bool {
        match payload {
            0 => {
                let doc_id =
                    crypto::short_hash(&format!("noise:{}:{tick}:{payload}", self.team));
                self.docs.get(&doc_id).map(|d| d.owner == "noise").unwrap_or(false)
            }
            1 => self
                .db
                .query_row::<i64, _, _>(
                    "SELECT COUNT(*) FROM settlements WHERE tick = ?1 AND branch = 'public-noise'",
                    params![tick],
                    |r| r.get(0),
                )
                .map(|n| n > 0)
                .unwrap_or(false),
            2 => self
                .db
                .query_row::<i64, _, _>(
                    "SELECT COUNT(*) FROM treasury_receipts WHERE tick = ?1 AND scope = ?2",
                    params![tick, format!("noise:{tick}")],
                    |r| r.get(0),
                )
                .map(|n| n > 0)
                .unwrap_or(false),
            _ => false,
        }
    }

    pub fn havoc(&mut self, tick: i64, payload: u8) -> bool {
        let script = format!("LIST:public");
        let result = crate::query::execute(self, &script);
        self.audit
            .push(format!("walk:{tick}:{payload}:{}", result["rows"].as_array().map(|r| r.len()).unwrap_or(0)));
        !self.docs.is_empty() && !ledger::merkle_root(&self.docs).is_empty()
    }

    pub fn prune_noise(&mut self, retention_ms: i64) -> usize {
        let cutoff = db::now_ms() - retention_ms;
        let mut dropped = 0usize;
        let mut stmt = self
            .db
            .prepare("SELECT id, path FROM docs WHERE class_name = 'public' AND owner = 'noise' AND created_at < ?1")
            .ok();
        if let Some(ref mut stmt) = stmt {
            let rows: Vec<(String, String)> = stmt
                .query_map(params![cutoff], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))
                .map(|iter| iter.flatten().collect())
                .unwrap_or_default();
            for (id, path) in rows {
                if self.db.execute("DELETE FROM docs WHERE id = ?1", params![id]).is_ok() {
                    self.docs.remove(&id);
                    self.path_index.remove(&path);
                    dropped += 1;
                }
            }
        }
        dropped
    }

    pub fn checkpoint(&self) {
        db::checkpoint(&self.db);
    }
}
