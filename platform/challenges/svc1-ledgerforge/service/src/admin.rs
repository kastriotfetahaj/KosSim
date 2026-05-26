use std::sync::Arc;

use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use rusqlite::params;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{accounts, audit_log, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

#[derive(Deserialize)]
struct AuditQuery {
    limit: Option<i64>,
}

async fn queue(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    let docs: i64 = state.db.query_row("SELECT COUNT(*) FROM docs", [], |r| r.get(0)).unwrap_or(0);
    let settlements: i64 = state
        .db
        .query_row("SELECT COUNT(*) FROM settlements", [], |r| r.get(0))
        .unwrap_or(0);
    let receipts: i64 = state
        .db
        .query_row("SELECT COUNT(*) FROM treasury_receipts", [], |r| r.get(0))
        .unwrap_or(0);
    let users: i64 = state.db.query_row("SELECT COUNT(*) FROM users", [], |r| r.get(0)).unwrap_or(0);
    (
        StatusCode::OK,
        Json(json!({
            "docs": docs,
            "settlements": settlements,
            "receipts": receipts,
            "users": users,
            "ts": crate::db::now_ms(),
        })),
    )
}

async fn accounts_list(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    let mut stmt = match state
        .db
        .prepare("SELECT id, username, role, created_at FROM users ORDER BY id DESC LIMIT 200")
    {
        Ok(s) => s,
        Err(_) => return (StatusCode::OK, Json(json!({"accounts": []}))),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map([], |row| {
            Ok(json!({
                "id": row.get::<_, i64>(0)?,
                "username": row.get::<_, String>(1)?,
                "role": row.get::<_, String>(2)?,
                "created_at": row.get::<_, i64>(3)?,
            }))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    (StatusCode::OK, Json(json!({"accounts": rows})))
}

async fn audit(State(state): State<Shared>, headers: HeaderMap, Query(q): Query<AuditQuery>) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    let entries = audit_log::recent(&state.db, q.limit.unwrap_or(100));
    (StatusCode::OK, Json(json!({"entries": entries})))
}

async fn checkpoint(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    state.checkpoint();
    audit_log::record(&state.db, &user.username, "admin.checkpoint", "wal", "");
    (StatusCode::OK, Json(json!({"ok": true})))
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/admin/queue", get(queue))
        .route("/api/admin/accounts", get(accounts_list))
        .route("/api/admin/audit", get(audit))
        .route("/api/admin/checkpoint", post(checkpoint))
        .with_state(state)
}
