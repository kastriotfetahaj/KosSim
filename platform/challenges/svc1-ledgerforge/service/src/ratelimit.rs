use std::sync::Arc;

use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use rusqlite::params;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;

#[derive(Clone, Copy)]
struct Bucket {
    capacity: f64,
    refill_per_second: f64,
}

const DEFAULT: Bucket = Bucket { capacity: 60.0, refill_per_second: 1.0 };
const AUTH: Bucket = Bucket { capacity: 10.0, refill_per_second: 0.2 };
const WRITE: Bucket = Bucket { capacity: 12.0, refill_per_second: 0.5 };

fn pick(uri_path: &str, method: &str) -> Option<(Bucket, &'static str)> {
    if uri_path.starts_with("/api/accounts/register") || uri_path.starts_with("/api/accounts/login") {
        return Some((AUTH, "auth"));
    }
    if uri_path == "/" && method == "POST" {
        return None;
    }
    if uri_path.starts_with("/api/") && matches!(method, "POST" | "PATCH" | "PUT" | "DELETE") {
        return Some((WRITE, "write"));
    }
    None
}

fn consume(state: &AppState, key: &str, bucket: Bucket) -> Option<i64> {
    let now = db::now_ms();
    let row: rusqlite::Result<(f64, i64)> = state.db.query_row(
        "SELECT tokens, refilled_at FROM rate_buckets WHERE key = ?1",
        params![key],
        |r| Ok((r.get(0)?, r.get(1)?)),
    );
    let (mut tokens, last) = row.unwrap_or((bucket.capacity, now));
    let elapsed_ms = (now - last).max(0) as f64;
    tokens = (tokens + (elapsed_ms / 1000.0) * bucket.refill_per_second).min(bucket.capacity);
    if tokens < 1.0 {
        let _ = state.db.execute(
            "INSERT OR REPLACE INTO rate_buckets (key, tokens, refilled_at) VALUES (?1, ?2, ?3)",
            params![key, tokens, now],
        );
        let deficit = 1.0 - tokens;
        let retry = if bucket.refill_per_second > 0.0 {
            (deficit / bucket.refill_per_second).ceil() as i64
        } else {
            60
        };
        return Some(retry);
    }
    tokens -= 1.0;
    let _ = state.db.execute(
        "INSERT OR REPLACE INTO rate_buckets (key, tokens, refilled_at) VALUES (?1, ?2, ?3)",
        params![key, tokens, now],
    );
    None
}

pub async fn middleware(State(state): State<Shared>, request: Request, next: Next) -> Response {
    let uri_path = request.uri().path().to_string();
    let method = request.method().as_str().to_string();
    if let Some((bucket, class)) = pick(&uri_path, &method) {
        let ip = request
            .headers()
            .get("x-forwarded-for")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.split(',').next())
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|| "unknown".to_string());
        let key = format!("{ip}|{class}");
        let guard = state.lock().await;
        if let Some(retry) = consume(&guard, &key, bucket) {
            drop(guard);
            return (
                StatusCode::TOO_MANY_REQUESTS,
                [("retry-after", retry.to_string())],
                Json(json!({"error": "rate_limited", "retry_after": retry})),
            )
                .into_response();
        }
    }
    next.run(request).await
}

pub async fn status(State(state): State<Shared>) -> impl IntoResponse {
    let state = state.lock().await;
    Json(json!({"bucket": "default", "capacity": DEFAULT.capacity, "refill_per_second": DEFAULT.refill_per_second, "ts": db::now_ms()}))
}
