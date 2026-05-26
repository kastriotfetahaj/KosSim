use std::sync::Arc;

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use rusqlite::params;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

#[derive(Deserialize)]
struct Heartbeat {
    cursor: Option<String>,
}

async fn list(State(state): State<Shared>) -> impl IntoResponse {
    let state = state.lock().await;
    let mut stmt = match state
        .db
        .prepare("SELECT peer, last_seen_at, cursor FROM replicas ORDER BY peer ASC LIMIT 100")
    {
        Ok(s) => s,
        Err(_) => return Json(json!({"replicas": []})),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map([], |row| {
            Ok(json!({
                "peer": row.get::<_, String>(0)?,
                "last_seen_at": row.get::<_, i64>(1)?,
                "cursor": row.get::<_, String>(2)?,
            }))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    Json(json!({"replicas": rows}))
}

async fn heartbeat(
    Path(peer): Path<String>,
    State(state): State<Shared>,
    Json(body): Json<Heartbeat>,
) -> impl IntoResponse {
    let state = state.lock().await;
    let now = db::now_ms();
    let cursor = body.cursor.unwrap_or_else(|| "0".to_string());
    if state
        .db
        .execute(
            "INSERT OR REPLACE INTO replicas (peer, last_seen_at, cursor) VALUES (?1, ?2, ?3)",
            params![peer, now, cursor],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "insert_failed"})));
    }
    (StatusCode::OK, Json(json!({"peer": peer, "cursor": cursor, "ts": now})))
}

async fn since(Path((peer, cursor)): Path<(String, String)>, State(state): State<Shared>) -> impl IntoResponse {
    let state = state.lock().await;
    let _ = state.db.execute(
        "UPDATE replicas SET last_seen_at = ?1, cursor = ?2 WHERE peer = ?3",
        params![db::now_ms(), cursor, peer],
    );
    let mut stmt = match state.db.prepare(
        "SELECT id, path, class_name, snapshot FROM docs WHERE public = 1 ORDER BY id ASC LIMIT 64",
    ) {
        Ok(s) => s,
        Err(_) => return (StatusCode::OK, Json(json!({"peer": peer, "rows": []}))),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map([], |row| {
            Ok(json!({
                "id": row.get::<_, String>(0)?,
                "path": row.get::<_, String>(1)?,
                "class": row.get::<_, String>(2)?,
                "snapshot": row.get::<_, String>(3)?,
            }))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    (
        StatusCode::OK,
        Json(json!({"peer": peer, "rows": rows, "next_cursor": db::now_ms().to_string()})),
    )
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/v1/replicas", get(list))
        .route("/api/v1/replicas/:peer/heartbeat", post(heartbeat))
        .route("/api/v1/replicas/:peer/since/:cursor", get(since))
        .with_state(state)
}
