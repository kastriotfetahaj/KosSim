use std::sync::Arc;

use argon2::password_hash::{rand_core::OsRng, PasswordHasher, SaltString};
use argon2::{Argon2, PasswordHash, PasswordVerifier};
use axum::{
    extract::State,
    http::{HeaderMap, HeaderValue, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use rusqlite::{params, Connection};
use serde::Deserialize;
use serde_json::json;
use tokio::sync::Mutex;

use crate::{audit_log, crypto, db, state::AppState};

pub type Shared = Arc<Mutex<AppState>>;
const SESSION_COOKIE: &str = "lf_session";
const SESSION_TTL_SECONDS: i64 = 4 * 3600;
const USERNAME_PATTERN: &[char] = &[];

pub struct UserRow {
    pub id: i64,
    pub username: String,
    pub role: String,
}

fn valid_username(name: &str) -> bool {
    if name.len() < 3 || name.len() > 32 {
        return false;
    }
    name.chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.' || c == '-')
        && !USERNAME_PATTERN.contains(&name.chars().next().unwrap_or('_'))
}

fn hash_password(password: &str) -> argon2::password_hash::Result<String> {
    let salt = SaltString::generate(&mut OsRng);
    Ok(Argon2::default().hash_password(password.as_bytes(), &salt)?.to_string())
}

fn verify_password(stored: &str, password: &str) -> bool {
    let parsed = match PasswordHash::new(stored) {
        Ok(p) => p,
        Err(_) => return false,
    };
    Argon2::default().verify_password(password.as_bytes(), &parsed).is_ok()
}

pub fn find_user_by_id(conn: &Connection, id: i64) -> Option<UserRow> {
    conn.query_row(
        "SELECT id, username, role FROM users WHERE id = ?1",
        params![id],
        |row| {
            Ok(UserRow {
                id: row.get(0)?,
                username: row.get(1)?,
                role: row.get(2)?,
            })
        },
    )
    .ok()
}

pub fn find_user_by_name(conn: &Connection, name: &str) -> Option<UserRow> {
    conn.query_row(
        "SELECT id, username, role FROM users WHERE username = ?1",
        params![name],
        |row| {
            Ok(UserRow {
                id: row.get(0)?,
                username: row.get(1)?,
                role: row.get(2)?,
            })
        },
    )
    .ok()
}

pub fn read_cookie(headers: &HeaderMap, name: &str) -> Option<String> {
    let raw = headers.get("cookie")?.to_str().ok()?;
    for part in raw.split(';') {
        let trimmed = part.trim();
        if let Some(rest) = trimmed.strip_prefix(&format!("{name}=")) {
            return Some(urlencoding::decode(rest).map(|s| s.into_owned()).unwrap_or(rest.to_string()));
        }
    }
    None
}

pub fn current_user(state: &AppState, headers: &HeaderMap) -> Option<UserRow> {
    let cookie = read_cookie(headers, SESSION_COOKIE)?;
    let (uid, exp) = crypto::verify_session(&state.session_key(), &cookie)?;
    let now = chrono::Utc::now().timestamp();
    if exp < now {
        return None;
    }
    let row: rusqlite::Result<i64> = state.db.query_row(
        "SELECT expires_at FROM sessions WHERE token = ?1",
        params![cookie],
        |r| r.get(0),
    );
    if let Ok(expires_at) = row {
        if expires_at < now {
            return None;
        }
    } else {
        return None;
    }
    find_user_by_id(&state.db, uid)
}

fn issue_session(state: &AppState, user: &UserRow) -> (String, i64) {
    let exp = chrono::Utc::now().timestamp() + SESSION_TTL_SECONDS;
    let cookie = crypto::sign_session(&state.session_key(), user.id, exp);
    let _ = state.db.execute(
        "INSERT OR REPLACE INTO sessions (token, user_id, expires_at) VALUES (?1, ?2, ?3)",
        params![cookie, user.id, exp],
    );
    (cookie, exp)
}

fn cookie_header(token: &str, max_age: i64) -> HeaderValue {
    let value = format!(
        "{SESSION_COOKIE}={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}",
        urlencoding::encode(token),
        max_age
    );
    HeaderValue::from_str(&value).unwrap_or_else(|_| HeaderValue::from_static(""))
}

#[derive(Deserialize)]
struct Credentials {
    username: String,
    password: String,
}

async fn register(State(state): State<Shared>, Json(body): Json<Credentials>) -> impl IntoResponse {
    let mut state = state.lock().await;
    if !valid_username(&body.username) {
        return (StatusCode::BAD_REQUEST, [("set-cookie", HeaderValue::from_static(""))], Json(json!({"error": "invalid_username"})));
    }
    if body.password.len() < 8 {
        return (StatusCode::BAD_REQUEST, [("set-cookie", HeaderValue::from_static(""))], Json(json!({"error": "weak_password"})));
    }
    if find_user_by_name(&state.db, &body.username).is_some() {
        return (StatusCode::CONFLICT, [("set-cookie", HeaderValue::from_static(""))], Json(json!({"error": "duplicate"})));
    }
    let hash = match hash_password(&body.password) {
        Ok(h) => h,
        Err(_) => {
            return (StatusCode::INTERNAL_SERVER_ERROR, [("set-cookie", HeaderValue::from_static(""))], Json(json!({"error": "hash_failed"})));
        }
    };
    let now = db::now_ms();
    if state.db.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?1, ?2, ?3, ?4)",
        params![body.username, hash, "analyst", now],
    ).is_err() {
        return (StatusCode::INTERNAL_SERVER_ERROR, [("set-cookie", HeaderValue::from_static(""))], Json(json!({"error": "insert_failed"})));
    }
    let user = match find_user_by_name(&state.db, &body.username) {
        Some(u) => u,
        None => {
            return (StatusCode::INTERNAL_SERVER_ERROR, [("set-cookie", HeaderValue::from_static(""))], Json(json!({"error": "lookup_failed"})));
        }
    };
    audit_log::record(&state.db, &user.username, "user.register", &format!("user:{}", user.id), "");
    let (cookie, _) = issue_session(&state, &user);
    (
        StatusCode::OK,
        [("set-cookie", cookie_header(&cookie, SESSION_TTL_SECONDS))],
        Json(json!({"id": user.id, "username": user.username, "role": user.role})),
    )
}

async fn login(State(state): State<Shared>, Json(body): Json<Credentials>) -> impl IntoResponse {
    let state = state.lock().await;
    let user = match find_user_by_name(&state.db, &body.username) {
        Some(u) => u,
        None => {
            audit_log::record(&state.db, &body.username, "user.login_failed", &body.username, "");
            return (
                StatusCode::UNAUTHORIZED,
                [("set-cookie", HeaderValue::from_static(""))],
                Json(json!({"error": "bad_credentials"})),
            );
        }
    };
    let stored: rusqlite::Result<String> = state.db.query_row(
        "SELECT password_hash FROM users WHERE id = ?1",
        params![user.id],
        |r| r.get(0),
    );
    let ok = match stored {
        Ok(hash) => verify_password(&hash, &body.password),
        Err(_) => false,
    };
    if !ok {
        audit_log::record(&state.db, &user.username, "user.login_failed", &user.username, "");
        return (
            StatusCode::UNAUTHORIZED,
            [("set-cookie", HeaderValue::from_static(""))],
            Json(json!({"error": "bad_credentials"})),
        );
    }
    let (cookie, _) = issue_session(&state, &user);
    audit_log::record(&state.db, &user.username, "user.login", &format!("user:{}", user.id), "");
    (
        StatusCode::OK,
        [("set-cookie", cookie_header(&cookie, SESSION_TTL_SECONDS))],
        Json(json!({"id": user.id, "username": user.username, "role": user.role})),
    )
}

async fn me(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    match current_user(&state, &headers) {
        Some(u) => (StatusCode::OK, Json(json!({"id": u.id, "username": u.username, "role": u.role}))),
        None => (StatusCode::UNAUTHORIZED, Json(json!({"error": "auth_required"}))),
    }
}

async fn logout(State(state): State<Shared>, headers: HeaderMap) -> impl IntoResponse {
    let state = state.lock().await;
    if let Some(cookie) = read_cookie(&headers, SESSION_COOKIE) {
        let _ = state.db.execute("DELETE FROM sessions WHERE token = ?1", params![cookie]);
    }
    (
        StatusCode::OK,
        [("set-cookie", cookie_header("", 0))],
        Json(json!({"ok": true})),
    )
}

pub fn router(state: Shared) -> Router {
    Router::new()
        .route("/api/accounts/register", post(register))
        .route("/api/accounts/login", post(login))
        .route("/api/accounts/me", get(me))
        .route("/api/accounts/logout", post(logout))
        .with_state(state)
}
