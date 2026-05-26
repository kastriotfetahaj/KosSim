// Ledger normalization and pair-based merkle (no AppState dependency).

use sha2::{Digest, Sha256};

fn normalize_path(raw: &str) -> String {
    let decoded = urlencoding::decode(raw).unwrap_or_else(|_| raw.into());
    let mut parts: Vec<&str> = Vec::new();
    for part in decoded.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            _ => parts.push(part),
        }
    }
    format!("/{}", parts.join("/"))
}

fn leaf_hash(id: &str, body: &str) -> String {
    let mut h = Sha256::new();
    h.update(id.as_bytes());
    h.update([0]);
    h.update(body.as_bytes());
    hex::encode(h.finalize())
}

#[test]
fn normalize_collapses_percent_decoded_dotdot() {
    assert_eq!(normalize_path("/public/%2e%2e/vault/abcdef"), "/vault/abcdef");
}

#[test]
fn normalize_handles_repeated_traversal() {
    assert_eq!(normalize_path("/a/b/../../c"), "/c");
}

#[test]
fn normalize_drops_trailing_dot_segments() {
    assert_eq!(normalize_path("/x/./y"), "/x/y");
}

#[test]
fn leaf_hash_depends_on_body() {
    assert_ne!(leaf_hash("doc", "alpha"), leaf_hash("doc", "beta"));
}
