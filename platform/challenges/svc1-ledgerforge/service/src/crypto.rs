use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use hmac::{Hmac, Mac};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;

type HmacSha256 = Hmac<Sha256>;

const SETTLEMENT_TOKEN_BYTES: usize = 32;

#[derive(Debug, Serialize, Deserialize)]
pub struct Grant {
    pub scope: String,
    pub label: String,
}

pub fn short_hash(input: &str) -> String {
    let digest = Sha256::digest(input.as_bytes());
    hex::encode(&digest[..10])
}

pub fn random_id(prefix: &str) -> String {
    let mut buf = [0u8; 8];
    rand::thread_rng().fill_bytes(&mut buf);
    format!("{prefix}_{}", hex::encode(buf))
}

pub fn grant_key(checker_secret: &str, team: &str, service: &str) -> Vec<u8> {
    let mut mac = HmacSha256::new_from_slice(checker_secret.as_bytes()).unwrap();
    mac.update(b"grant-key:");
    mac.update(team.as_bytes());
    mac.update(b":");
    mac.update(service.as_bytes());
    mac.finalize().into_bytes().to_vec()
}

pub fn session_key(checker_secret: &str, team: &str) -> Vec<u8> {
    let mut mac = HmacSha256::new_from_slice(checker_secret.as_bytes()).unwrap();
    mac.update(b"session-key:");
    mac.update(team.as_bytes());
    mac.finalize().into_bytes().to_vec()
}

pub fn settlement_secret(checker_secret: &str) -> String {
    checker_secret.to_string()
}

pub fn sign_grant(key: &[u8], scope: &str, label: &str) -> String {
    let body = serde_json::to_vec(&Grant {
        scope: scope.to_string(),
        label: label.to_string(),
    })
    .unwrap();
    let body64 = URL_SAFE_NO_PAD.encode(body);
    let mut mac = HmacSha256::new_from_slice(key).unwrap();
    mac.update(body64.as_bytes());
    let sig = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    format!("{body64}.{sig}")
}

pub fn verify_grant(key: &[u8], token: &str) -> Option<Grant> {
    let (body64, sig) = token.split_once('.')?;
    let mut mac = HmacSha256::new_from_slice(key).ok()?;
    mac.update(body64.as_bytes());
    let expected = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    if expected.as_bytes().ct_eq(sig.as_bytes()).unwrap_u8() == 0 {
        return None;
    }
    let body = URL_SAFE_NO_PAD.decode(body64).ok()?;
    serde_json::from_slice(&body).ok()
}

pub fn sign_session(key: &[u8], uid: i64, exp: i64) -> String {
    let body = serde_json::to_vec(&serde_json::json!({"uid": uid, "exp": exp})).unwrap();
    let body64 = URL_SAFE_NO_PAD.encode(body);
    let mut mac = HmacSha256::new_from_slice(key).unwrap();
    mac.update(body64.as_bytes());
    let sig = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    format!("{body64}.{sig}")
}

pub fn verify_session(key: &[u8], token: &str) -> Option<(i64, i64)> {
    let (body64, sig) = token.split_once('.')?;
    let mut mac = HmacSha256::new_from_slice(key).ok()?;
    mac.update(body64.as_bytes());
    let want = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    if want.as_bytes().ct_eq(sig.as_bytes()).unwrap_u8() == 0 {
        return None;
    }
    let body = URL_SAFE_NO_PAD.decode(body64).ok()?;
    let parsed: serde_json::Value = serde_json::from_slice(&body).ok()?;
    let uid = parsed.get("uid")?.as_i64()?;
    let exp = parsed.get("exp")?.as_i64()?;
    if exp < chrono::Utc::now().timestamp() {
        return None;
    }
    Some((uid, exp))
}

pub fn sign_settlement_token(secret: &str, id: &str, viewer_bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(secret.as_bytes());
    h.update(b"|");
    h.update(id.as_bytes());
    h.update(b"|");
    h.update(viewer_bytes);
    hex::encode(&h.finalize()[..SETTLEMENT_TOKEN_BYTES])
}

pub fn verify_settlement_token(secret: &str, id: &str, viewer_bytes: &[u8], token: &str) -> bool {
    let want = sign_settlement_token(secret, id, viewer_bytes);
    want.as_bytes().ct_eq(token.as_bytes()).unwrap_u8() == 1
}
