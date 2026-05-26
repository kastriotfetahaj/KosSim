use std::sync::Arc;

use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{delete, get, post},
    Json, Router,
};
use rusqlite::params;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{accounts, audit_log, db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

#[derive(Deserialize)]
struct CreateReceipt {
    body: String,
    scope: String,
}

#[derive(Deserialize)]
struct CreateViewer {
    key: String,
    scopes: Vec<String>,
}

struct Receipt {
    id: i64,
    body: String,
    scope: String,
    tick: i64,
    created_at: i64,
}

fn load_receipt(state: &AppState, id: i64) -> Option<Receipt> {
    state
        .db
        .query_row(
            "SELECT id, body, scope, tick, created_at FROM treasury_receipts WHERE id = ?1",
            params![id],
            |row| {
                Ok(Receipt {
                    id: row.get(0)?,
                    body: row.get(1)?,
                    scope: row.get(2)?,
                    tick: row.get(3)?,
                    created_at: row.get(4)?,
                })
            },
        )
        .ok()
}

fn viewer_scopes(state: &AppState, key: &str) -> Option<Vec<String>> {
    let raw: rusqlite::Result<String> = state.db.query_row(
        "SELECT scopes FROM treasury_viewers WHERE key = ?1",
        params![key],
        |row| row.get(0),
    );
    let raw = raw.ok()?;
    serde_json::from_str(&raw).ok()
}

fn check_scope(viewer_scopes: &[String], receipt: &Receipt) -> bool {
    if viewer_scopes.is_empty() {
        return true;
    }
    viewer_scopes.iter().any(|s| *s == receipt.scope)
}

async fn create_receipt(
    State(state): State<Shared>,
    headers: HeaderMap,
    Json(body): Json<CreateReceipt>,
) -> impl IntoResponse {
    let mut state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" && user.role != "analyst" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "forbidden"})));
    }
    let now = db::now_ms();
    if state
        .db
        .execute(
            "INSERT INTO treasury_receipts (body, scope, tick, created_at) VALUES (?1, ?2, 0, ?3)",
            params![body.body, body.scope, now],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "insert_failed"})));
    }
    let id = state.db.last_insert_rowid();
    audit_log::record(&state.db, &user.username, "treasury.create", &format!("receipt:{id}"), &body.scope);
    (StatusCode::OK, Json(json!({"id": id, "scope": body.scope})))
}

async fn read_receipt(
    Path(id): Path<i64>,
    State(state): State<Shared>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let state = state.lock().await;
    let key = headers
        .get("x-viewer-key")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if key.is_empty() {
        return (StatusCode::UNAUTHORIZED, Json(json!({"error": "missing_viewer_key"})));
    }
    let scopes = match viewer_scopes(&state, key) {
        Some(s) => s,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "unknown_viewer"}))),
    };
    let receipt = match load_receipt(&state, id) {
        Some(r) => r,
        None => return (StatusCode::NOT_FOUND, Json(json!({"error": "not_found"}))),
    };
    if !check_scope(&scopes, &receipt) {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "scope_denied"})));
    }
    (
        StatusCode::OK,
        Json(json!({
            "id": receipt.id,
            "body": receipt.body,
            "scope": receipt.scope,
            "tick": receipt.tick,
            "created_at": receipt.created_at,
        })),
    )
}

async fn list_viewers(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
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
        .prepare("SELECT key, scopes, created_at FROM treasury_viewers ORDER BY created_at DESC LIMIT 100")
    {
        Ok(s) => s,
        Err(_) => return (StatusCode::OK, Json(json!({"viewers": []}))),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map([], |row| {
            Ok(json!({
                "key": row.get::<_, String>(0)?,
                "scopes": serde_json::from_str::<Vec<String>>(&row.get::<_, String>(1)?).unwrap_or_default(),
                "created_at": row.get::<_, i64>(2)?,
            }))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    (StatusCode::OK, Json(json!({"viewers": rows})))
}

async fn create_viewer(
    State(state): State<Shared>,
    headers: HeaderMap,
    Json(body): Json<CreateViewer>,
) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    let now = db::now_ms();
    let scopes_json = serde_json::to_string(&body.scopes).unwrap_or_else(|_| "[]".to_string());
    if state
        .db
        .execute(
            "INSERT OR REPLACE INTO treasury_viewers (key, scopes, created_at) VALUES (?1, ?2, ?3)",
            params![body.key, scopes_json, now],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "insert_failed"})));
    }
    audit_log::record(&state.db, &user.username, "treasury.viewer.create", &body.key, "");
    (StatusCode::OK, Json(json!({"key": body.key, "scopes": body.scopes})))
}

async fn delete_viewer(Path(key): Path<String>, State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    if state
        .db
        .execute("DELETE FROM treasury_viewers WHERE key = ?1", params![key])
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "delete_failed"})));
    }
    audit_log::record(&state.db, &user.username, "treasury.viewer.delete", &key, "");
    (StatusCode::OK, Json(json!({"ok": true})))
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/treasury/receipts", post(create_receipt))
        .route("/api/treasury/receipts/:id", get(read_receipt))
        .route("/api/treasury/viewers", get(list_viewers).post(create_viewer))
        .route("/api/treasury/viewers/:key", delete(delete_viewer))
        .with_state(state)
}
