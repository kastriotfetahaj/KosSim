use std::sync::Arc;

use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{delete, get, post},
    Json, Router,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use rand::RngCore;
use rusqlite::params;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{accounts, audit_log, db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

const VALID_SCOPES: &[&str] = &[
    "settlements:read",
    "settlements:write",
    "treasury:read",
    "policies:read",
    "audit:read",
];

#[derive(Deserialize)]
struct Mint {
    scopes: Vec<String>,
    label: Option<String>,
    ttl: Option<i64>,
}

fn random_token() -> String {
    let mut buf = [0u8; 24];
    rand::thread_rng().fill_bytes(&mut buf);
    format!("lftok_{}", URL_SAFE_NO_PAD.encode(buf))
}

async fn mint(State(state): State<Shared>, headers: HeaderMap, Json(body): Json<Mint>) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    let scopes: Vec<&str> = body
        .scopes
        .iter()
        .filter_map(|s| VALID_SCOPES.iter().copied().find(|v| *v == s.as_str()))
        .collect();
    if scopes.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(json!({"error": "no_scopes"})));
    }
    let token = random_token();
    let now = db::now_ms();
    let ttl_ms = body.ttl.unwrap_or(86_400).clamp(60, 7 * 86_400) * 1000;
    let label = body.label.unwrap_or_default();
    if state
        .db
        .execute(
            "INSERT INTO api_tokens (token, user_id, scopes, label, created_at, expires_at, revoked) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0)",
            params![token, user.id, scopes.join(","), label, now, now + ttl_ms],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "insert_failed"})));
    }
    audit_log::record(&state.db, &user.username, "apitoken.mint", &token[..12], &label);
    (
        StatusCode::OK,
        Json(json!({
            "token": token,
            "scopes": scopes,
            "expires_at": now + ttl_ms,
        })),
    )
}

async fn list(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    let mut stmt = match state.db.prepare(
        "SELECT token, scopes, label, created_at, expires_at, revoked FROM api_tokens WHERE user_id = ?1 ORDER BY created_at DESC LIMIT 50",
    ) {
        Ok(s) => s,
        Err(_) => return (StatusCode::OK, Json(json!({"tokens": []}))),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map(params![user.id], |row| {
            let token: String = row.get(0)?;
            Ok(json!({
                "token": format!("{}…", &token[..token.len().min(12)]),
                "scopes": row.get::<_, String>(1)?.split(',').map(|s| s.to_string()).collect::<Vec<_>>(),
                "label": row.get::<_, String>(2)?,
                "created_at": row.get::<_, i64>(3)?,
                "expires_at": row.get::<_, i64>(4)?,
                "revoked": row.get::<_, i64>(5)? == 1,
            }))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    (StatusCode::OK, Json(json!({"tokens": rows})))
}

async fn revoke(Path(prefix): Path<String>, State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    let pattern = format!("{prefix}%");
    let row: rusqlite::Result<String> = state.db.query_row(
        "SELECT token FROM api_tokens WHERE user_id = ?1 AND token LIKE ?2 LIMIT 1",
        params![user.id, pattern],
        |r| r.get(0),
    );
    let token = match row {
        Ok(t) => t,
        Err(_) => return (StatusCode::NOT_FOUND, Json(json!({"error": "not_found"}))),
    };
    let _ = state.db.execute("UPDATE api_tokens SET revoked = 1 WHERE token = ?1", params![token]);
    audit_log::record(&state.db, &user.username, "apitoken.revoke", &prefix, "");
    (StatusCode::OK, Json(json!({"ok": true})))
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/tokens", post(mint).get(list))
        .route("/api/tokens/:prefix", delete(revoke))
        .with_state(state)
}
