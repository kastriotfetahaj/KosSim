use std::sync::Arc;

use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use rusqlite::params;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{accounts, audit_log, crypto, db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

#[derive(Deserialize)]
struct CreateReq {
    branch: String,
    body: String,
}

#[derive(Deserialize)]
struct ViewerParams {
    viewer: Option<String>,
    token: Option<String>,
}

#[derive(Deserialize)]
struct ListQuery {
    branch: Option<String>,
}

fn settlement_row(state: &AppState, id: &str) -> Option<serde_json::Value> {
    state
        .db
        .query_row(
            "SELECT id, branch, body, public_scope, public_token, tick, created_at FROM settlements WHERE id = ?1",
            params![id],
            |row| {
                Ok(json!({
                    "id": row.get::<_, String>(0)?,
                    "branch": row.get::<_, String>(1)?,
                    "body": row.get::<_, String>(2)?,
                    "public_scope": row.get::<_, String>(3)?,
                    "public_token": row.get::<_, String>(4)?,
                    "tick": row.get::<_, i64>(5)?,
                    "created_at": row.get::<_, i64>(6)?,
                }))
            },
        )
        .ok()
}

async fn create(State(state): State<Shared>, headers: HeaderMap, Json(body): Json<CreateReq>) -> impl IntoResponse {
    let mut state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    let id = crypto::random_id("stl");
    let viewer = "public";
    let token = crypto::sign_settlement_token(&state.settlement_secret(), &id, viewer.as_bytes());
    let now = db::now_ms();
    if state
        .db
        .execute(
            "INSERT INTO settlements (id, branch, body, public_scope, public_token, tick, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![id, body.branch, body.body, viewer, token, 0_i64, now],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "insert_failed"})));
    }
    audit_log::record(&state.db, &user.username, "settlement.create", &id, &body.branch);
    (
        StatusCode::OK,
        Json(json!({
            "id": id,
            "branch": body.branch,
            "viewer": viewer,
            "token": token,
        })),
    )
}

async fn list(State(state): State<Shared>, Query(q): Query<ListQuery>) -> impl IntoResponse {
    let state = state.lock().await;
    let branch = q.branch.unwrap_or_else(|| "public-noise".to_string());
    let mut stmt = match state.db.prepare(
        "SELECT id, branch, public_scope, tick, created_at FROM settlements WHERE branch = ?1 ORDER BY id DESC LIMIT 100",
    ) {
        Ok(s) => s,
        Err(_) => return Json(json!({"settlements": []})),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map(params![branch], |row| {
            Ok(json!({
                "id": row.get::<_, String>(0)?,
                "branch": row.get::<_, String>(1)?,
                "public_scope": row.get::<_, String>(2)?,
                "tick": row.get::<_, i64>(3)?,
                "created_at": row.get::<_, i64>(4)?,
            }))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    Json(json!({"settlements": rows, "branch": branch}))
}

async fn read(Path(id): Path<String>, State(state): State<Shared>, Query(q): Query<ViewerParams>) -> impl IntoResponse {
    let state = state.lock().await;
    let viewer_b64 = q.viewer.unwrap_or_default();
    let token = q.token.unwrap_or_default();
    if viewer_b64.is_empty() || token.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(json!({"error": "missing_params"})));
    }
    let viewer_bytes = match URL_SAFE_NO_PAD.decode(viewer_b64.as_bytes()) {
        Ok(b) => b,
        Err(_) => return (StatusCode::BAD_REQUEST, Json(json!({"error": "bad_viewer"}))),
    };
    if !crypto::verify_settlement_token(&state.settlement_secret(), &id, &viewer_bytes, &token) {
        return (StatusCode::UNAUTHORIZED, Json(json!({"error": "bad_token"})));
    }
    let row = match settlement_row(&state, &id) {
        Some(r) => r,
        None => return (StatusCode::NOT_FOUND, Json(json!({"error": "not_found"}))),
    };
    let viewer_text = String::from_utf8_lossy(&viewer_bytes);
    let scopes: Vec<&str> = viewer_text.split(',').map(|s| s.trim()).collect();
    if scopes.iter().any(|s| *s == "admin") {
        return (StatusCode::OK, Json(json!({
            "id": row["id"],
            "branch": row["branch"],
            "body": row["body"],
            "viewer": viewer_text,
        })));
    }
    (
        StatusCode::OK,
        Json(json!({
            "id": row["id"],
            "branch": row["branch"],
            "viewer": viewer_text,
            "tick": row["tick"],
        })),
    )
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/settlements", post(create).get(list))
        .route("/api/settlements/:id", get(read))
        .with_state(state)
}
