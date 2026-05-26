// VaultGrid crypt sidecar.
//
// Stores encrypted manifest entries (AES-128-CBC + PKCS#7) under a tenant
// key derived from SERVICE_PUSH_SECRET. The /decrypt endpoint validates that
// the recovered plaintext parses as JSON after padding removal. The
// distinguishable padding/JSON error responses are the padding-oracle surface
// used by flagstore 1.

use std::{env, net::SocketAddr, path::PathBuf, sync::Arc};

use aes::cipher::{generic_array::GenericArray, BlockDecrypt, BlockEncrypt, KeyInit};
use aes::Aes128;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use base64::{engine::general_purpose::STANDARD as B64, Engine};
use hmac::{Hmac, Mac};
use rand::RngCore;
use rusqlite::{params, Connection};
use serde::Deserialize;
use serde_json::json;
use sha2::Sha256;
use tokio::sync::Mutex;

struct App {
    db: Mutex<Connection>,
    secret: String,
}

impl App {
    fn new() -> Arc<Self> {
        let secret = env::var("SERVICE_PUSH_SECRET").unwrap_or_else(|_| "rotate-secret".into());
        let dir = env::var("VAULTGRID_CRYPT_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("/var/lib/vaultgrid-crypt"));
        std::fs::create_dir_all(&dir).expect("crypt data dir");
        let db = Connection::open(dir.join("crypt.db")).expect("open crypt db");
        db.pragma_update(None, "journal_mode", "WAL").ok();
        db.pragma_update(None, "synchronous", "NORMAL").ok();
        db.pragma_update(None, "busy_timeout", 5000).ok();
        db.execute_batch(
            "CREATE TABLE IF NOT EXISTS manifests (
                id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                iv BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
             CREATE INDEX IF NOT EXISTS idx_manifests_tenant ON manifests (tenant);
             CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                ts INTEGER NOT NULL
            );",
        )
        .expect("crypt schema");
        Arc::new(Self {
            db: Mutex::new(db),
            secret,
        })
    }

    fn tenant_key(&self, tenant: &str) -> [u8; 16] {
        let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(self.secret.as_bytes()).unwrap();
        mac.update(b"vaultgrid-crypt:");
        mac.update(tenant.as_bytes());
        let out = mac.finalize().into_bytes();
        let mut key = [0u8; 16];
        key.copy_from_slice(&out[..16]);
        key
    }
}

fn record(conn: &Connection, actor: &str, action: &str, target: &str) {
    let _ = conn.execute(
        "INSERT INTO audit (actor, action, target, ts) VALUES (?1, ?2, ?3, ?4)",
        params![actor, action, target, now_ms()],
    );
}

fn now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn header_secret_ok(req_headers: &axum::http::HeaderMap, app: &App) -> bool {
    req_headers
        .get("x-checker-secret")
        .and_then(|v| v.to_str().ok())
        .map(|s| s == app.secret)
        .unwrap_or(false)
}

fn encrypt_cbc(key: &[u8; 16], iv: &[u8; 16], plaintext: &[u8]) -> Vec<u8> {
    let cipher = Aes128::new(GenericArray::from_slice(key));
    let pad_len = 16 - (plaintext.len() % 16);
    let mut padded: Vec<u8> = plaintext.to_vec();
    padded.extend(std::iter::repeat(pad_len as u8).take(pad_len));
    let mut out = Vec::with_capacity(padded.len());
    let mut prev = *iv;
    for chunk in padded.chunks(16) {
        let mut block = [0u8; 16];
        for i in 0..16 {
            block[i] = chunk[i] ^ prev[i];
        }
        let mut blk = GenericArray::clone_from_slice(&block);
        cipher.encrypt_block(&mut blk);
        out.extend_from_slice(blk.as_slice());
        prev.copy_from_slice(blk.as_slice());
    }
    out
}

#[derive(Debug)]
enum DecryptError {
    BadPadding,
    BadAlign,
}

fn decrypt_cbc(key: &[u8; 16], iv: &[u8; 16], ct: &[u8]) -> Result<Vec<u8>, DecryptError> {
    if ct.is_empty() || ct.len() % 16 != 0 {
        return Err(DecryptError::BadAlign);
    }
    let cipher = Aes128::new(GenericArray::from_slice(key));
    let mut out = Vec::with_capacity(ct.len());
    let mut prev: [u8; 16] = *iv;
    for chunk in ct.chunks(16) {
        let mut current = [0u8; 16];
        current.copy_from_slice(chunk);
        let mut blk = GenericArray::clone_from_slice(&current);
        cipher.decrypt_block(&mut blk);
        for (i, b) in blk.as_slice().iter().enumerate() {
            out.push(b ^ prev[i]);
        }
        prev = current;
    }
    let pad = *out.last().ok_or(DecryptError::BadPadding)? as usize;
    if pad == 0 || pad > 16 || out.len() < pad {
        return Err(DecryptError::BadPadding);
    }
    for i in 0..pad {
        if out[out.len() - 1 - i] != pad as u8 {
            return Err(DecryptError::BadPadding);
        }
    }
    out.truncate(out.len() - pad);
    Ok(out)
}

#[derive(Deserialize)]
struct StoreReq {
    id: String,
    tenant: String,
    plaintext: String,
}

async fn store(
    State(app): State<Arc<App>>,
    headers: axum::http::HeaderMap,
    Json(body): Json<StoreReq>,
) -> impl IntoResponse {
    if !header_secret_ok(&headers, &app) {
        return (StatusCode::FORBIDDEN, Json(json!({"error": "forbidden"})));
    }
    let key = app.tenant_key(&body.tenant);
    let mut iv = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut iv);
    let ct = encrypt_cbc(&key, &iv, body.plaintext.as_bytes());
    let db = app.db.lock().await;
    if db
        .execute(
            "INSERT OR REPLACE INTO manifests (id, tenant, iv, ciphertext, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![body.id, body.tenant, iv.to_vec(), ct.clone(), now_ms()],
        )
        .is_err()
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "insert"})));
    }
    record(&db, "checker", "manifest.store", &body.id);
    (
        StatusCode::OK,
        Json(json!({
            "id": body.id,
            "tenant": body.tenant,
            "iv": hex::encode(iv),
            "ciphertext": hex::encode(&ct),
        })),
    )
}

#[derive(Deserialize)]
struct ReadParams {
    tenant: Option<String>,
}

async fn show(
    Path(id): Path<String>,
    State(app): State<Arc<App>>,
    Query(q): Query<ReadParams>,
) -> impl IntoResponse {
    let db = app.db.lock().await;
    let row: rusqlite::Result<(String, Vec<u8>, Vec<u8>)> = db.query_row(
        "SELECT tenant, iv, ciphertext FROM manifests WHERE id = ?1",
        params![id],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    );
    let (tenant, iv, ct) = match row {
        Ok(v) => v,
        Err(_) => return (StatusCode::NOT_FOUND, Json(json!({"error": "not_found"}))),
    };
    if let Some(qt) = q.tenant {
        if qt != tenant {
            return (StatusCode::FORBIDDEN, Json(json!({"error": "wrong_tenant"})));
        }
    }
    (
        StatusCode::OK,
        Json(json!({
            "id": id,
            "tenant": tenant,
            "iv": hex::encode(&iv),
            "ciphertext": hex::encode(&ct),
            "ciphertext_b64": B64.encode(&ct),
        })),
    )
}

#[derive(Deserialize)]
struct DecryptParams {
    tenant: String,
    iv: String,
    ct: String,
}

async fn decrypt(
    State(app): State<Arc<App>>,
    Query(p): Query<DecryptParams>,
) -> impl IntoResponse {
    let iv = match hex::decode(&p.iv) {
        Ok(v) if v.len() == 16 => v,
        _ => return (StatusCode::BAD_REQUEST, Json(json!({"error": "bad_iv"}))),
    };
    let ct = match hex::decode(&p.ct) {
        Ok(v) if !v.is_empty() && v.len() % 16 == 0 => v,
        _ => return (StatusCode::BAD_REQUEST, Json(json!({"error": "bad_ct"}))),
    };
    let key = app.tenant_key(&p.tenant);
    let mut iv_arr = [0u8; 16];
    iv_arr.copy_from_slice(&iv);
    let pt = match decrypt_cbc(&key, &iv_arr, &ct) {
        Ok(p) => p,
        Err(_) => return (StatusCode::BAD_REQUEST, Json(json!({"error": "bad_padding"}))),
    };
    match serde_json::from_slice::<serde_json::Value>(&pt) {
        Ok(v) => (StatusCode::OK, Json(json!({"manifest": v, "tenant": p.tenant}))),
        Err(_) => (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({"error": "non_json_plaintext"})),
        ),
    }
}

async fn list(
    State(app): State<Arc<App>>,
    Query(q): Query<ReadParams>,
) -> impl IntoResponse {
    let db = app.db.lock().await;
    let tenant_filter = q.tenant.unwrap_or_else(|| "public".to_string());
    let mut stmt = match db.prepare(
        "SELECT id, tenant, created_at FROM manifests WHERE tenant = ?1 ORDER BY id LIMIT 100",
    ) {
        Ok(s) => s,
        Err(_) => return (StatusCode::OK, Json(json!({"manifests": []}))),
    };
    let rows: Vec<serde_json::Value> = stmt
        .query_map(params![tenant_filter], |row| {
            Ok(json!({
                "id": row.get::<_, String>(0)?,
                "tenant": row.get::<_, String>(1)?,
                "created_at": row.get::<_, i64>(2)?,
            }))
        })
        .map(|i| i.flatten().collect())
        .unwrap_or_default();
    (StatusCode::OK, Json(json!({"manifests": rows})))
}

async fn health() -> impl IntoResponse {
    Json(json!({"status": "up", "name": "vaultgrid-crypt"}))
}

#[tokio::main]
async fn main() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .try_init();
    let app = App::new();
    let router = Router::new()
        .route("/health", get(health))
        .route("/api/crypt/manifests", get(list).post(store))
        .route("/api/crypt/manifests/:id", get(show))
        .route("/api/crypt/decrypt", get(decrypt))
        .with_state(app);
    let addr: SocketAddr = "0.0.0.0:4102".parse().unwrap();
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind");
    axum::serve(listener, router).await.expect("serve");
}
