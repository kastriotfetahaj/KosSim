use std::sync::Arc;

use axum::{extract::State, Json};
use serde_json::{json, Value};
use tokio::sync::Mutex;

use crate::{indexer, ledger, state::AppState};

type Shared = Arc<Mutex<AppState>>;

pub async fn merkle_debug(State(state): State<Shared>) -> Json<Value> {
    let state = state.lock().await;
    Json(json!({
        "root": ledger::merkle_root(&state.docs),
        "leaves": state.docs.len(),
        "note": "debug roots are salted in production",
    }))
}

pub async fn indexer_stats(State(state): State<Shared>) -> Json<Value> {
    let state = state.lock().await;
    let stats = indexer::read_stats(&state);
    Json(json!({
        "cycles": stats.cycles,
        "noise_pruned": stats.noise_pruned,
        "sessions_collected": stats.sessions_collected,
        "last_cycle_ms": stats.last_cycle_ms,
        "last_cycle_at": stats.last_cycle_at,
        "merkle_root": stats.last_root,
    }))
}

pub async fn health_db(State(state): State<Shared>) -> Json<Value> {
    let state = state.lock().await;
    let ok: rusqlite::Result<i64> = state.db.query_row("SELECT 1", [], |r| r.get(0));
    Json(json!({"status": if ok.is_ok() { "up" } else { "down" }}))
}
