use std::sync::Arc;
use std::time::Duration;

use rusqlite::params;
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;

use crate::{audit_log, db, ledger, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

const NOISE_RETENTION_MS: i64 = 30 * 60_000;
const SESSION_GC_INTERVAL: Duration = Duration::from_secs(60);
const AUDIT_KEEP: i64 = 5_000;

#[derive(Default, Clone, Serialize, Deserialize)]
pub struct Stats {
    pub cycles: i64,
    pub noise_pruned: i64,
    pub sessions_collected: i64,
    pub last_root: String,
    pub last_cycle_ms: i64,
    pub last_cycle_at: i64,
}

pub fn spawn(state: Shared) {
    tokio::spawn(async move {
        let mut stats = Stats::default();
        loop {
            cycle(&state, &mut stats).await;
            tokio::time::sleep(SESSION_GC_INTERVAL).await;
        }
    });
}

async fn cycle(state: &Shared, stats: &mut Stats) {
    let start = db::now_ms();
    let mut guard = state.lock().await;
    let pruned = guard.prune_noise(NOISE_RETENTION_MS);
    stats.noise_pruned += pruned as i64;
    let now_secs = chrono::Utc::now().timestamp();
    let dropped: rusqlite::Result<usize> =
        guard.db.execute("DELETE FROM sessions WHERE expires_at < ?1", params![now_secs]);
    if let Ok(n) = dropped {
        stats.sessions_collected += n as i64;
    }
    audit_log::trim(&guard.db, AUDIT_KEEP);
    stats.last_root = ledger::merkle_root(&guard.docs);
    stats.cycles += 1;
    stats.last_cycle_ms = db::now_ms() - start;
    stats.last_cycle_at = db::now_ms();
    let stats_json = serde_json::to_string(stats).unwrap_or_else(|_| "{}".to_string());
    let _ = guard.db.execute(
        "INSERT OR REPLACE INTO kv (k, v) VALUES (?1, ?2)",
        params!["indexer_stats", stats_json],
    );
}

pub fn read_stats(state: &AppState) -> Stats {
    let row: rusqlite::Result<String> = state
        .db
        .query_row("SELECT v FROM kv WHERE k = ?1", params!["indexer_stats"], |r| r.get(0));
    row.ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}
