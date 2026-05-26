use std::sync::Arc;

use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::get,
    Json, Router,
};
use rusqlite::params;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{accounts, audit_log, db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

#[derive(Deserialize)]
struct UpdateReq {
    max_body_bytes: Option<i64>,
    retention_ticks: Option<i64>,
    allowed_signers: Option<String>,
}

fn serialise_row(class: &str, max_bytes: i64, retention: i64, signers: &str, updated: i64) -> serde_json::Value {
    json!({
        "class": class,
        "max_body_bytes": max_bytes,
        "retention_ticks": retention,
        "allowed_signers": signers.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()).collect::<Vec<_>>(),
        "updated_at": updated,
    })
}

async fn list(State(state): State<Shared>) -> impl IntoResponse {
    let state = state.lock().await;
    let mut stmt = match state.db.prepare(
        "SELECT class, max_body_bytes, retention_ticks, allowed_signers, updated_at FROM policies ORDER BY class ASC",
    ) {
        Ok(s) => s,
        Err(_) => return Json(json!({"policies": []})),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map([], |row| {
            Ok(serialise_row(
                &row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
                &row.get::<_, String>(3)?,
                row.get::<_, i64>(4)?,
            ))
        })
        .map(|iter| iter.flatten().collect())
        .unwrap_or_default();
    Json(json!({"policies": rows}))
}

async fn show(Path(class): Path<String>, State(state): State<Shared>) -> impl IntoResponse {
    let state = state.lock().await;
    let row = state.db.query_row(
        "SELECT class, max_body_bytes, retention_ticks, allowed_signers, updated_at FROM policies WHERE class = ?1",
        params![class],
        |row| {
            Ok(serialise_row(
                &row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
                &row.get::<_, String>(3)?,
                row.get::<_, i64>(4)?,
            ))
        },
    );
    match row {
        Ok(v) => (StatusCode::OK, Json(v)),
        Err(_) => (StatusCode::NOT_FOUND, Json(json!({"error": "not_found"}))),
    }
}

async fn update(
    Path(class): Path<String>,
    State(state): State<Shared>,
    headers: HeaderMap,
    Json(body): Json<UpdateReq>,
) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match accounts::current_user(&state, &headers) {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    };
    if user.role != "admin" {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "admin_only"})));
    }
    let existing: rusqlite::Result<(i64, i64, String)> = state.db.query_row(
        "SELECT max_body_bytes, retention_ticks, allowed_signers FROM policies WHERE class = ?1",
        params![class],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    );
    let (mut max_bytes, mut retention, mut signers) = match existing {
        Ok(v) => v,
        Err(_) => return (StatusCode::NOT_FOUND, Json(json!({"error": "not_found"}))),
    };
    if let Some(v) = body.max_body_bytes {
        max_bytes = v.clamp(64, 1_048_576);
    }
    if let Some(v) = body.retention_ticks {
        retention = v.clamp(1, 256);
    }
    if let Some(v) = body.allowed_signers {
        signers = v
            .split(',')
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(",");
    }
    let now = db::now_ms();
    if state
        .db
        .execute(
            "UPDATE policies SET max_body_bytes = ?1, retention_ticks = ?2, allowed_signers = ?3, updated_at = ?4 WHERE class = ?5",
            params![max_bytes, retention, signers, now, class],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "update_failed"})));
    }
    audit_log::record(&state.db, &user.username, "policy.update", &class, "");
    (StatusCode::OK, Json(serialise_row(&class, max_bytes, retention, &signers, now)))
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/policies", get(list))
        .route("/api/policies/:class", get(show).patch(update))
        .with_state(state)
}
