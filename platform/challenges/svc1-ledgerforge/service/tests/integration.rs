// Standalone integration tests: only modules that don't pull AppState transitively.
// State + ledger have their own unit tests in src/.

#[path = "../src/crypto.rs"] mod crypto;

#[test]
fn grant_roundtrip_uses_derived_key() {
    let key = crypto::grant_key("super-secret", "team1", "svc1");
    let token = crypto::sign_grant(&key, "/public", "guest-mirror");
    let parsed = crypto::verify_grant(&key, &token).expect("verify");
    assert_eq!(parsed.scope, "/public");
    assert_eq!(parsed.label, "guest-mirror");
}

#[test]
fn grant_with_other_team_rejected() {
    let key_a = crypto::grant_key("super-secret", "team1", "svc1");
    let key_b = crypto::grant_key("super-secret", "team2", "svc1");
    let token = crypto::sign_grant(&key_a, "/public", "guest-mirror");
    assert!(crypto::verify_grant(&key_b, &token).is_none());
}

#[test]
fn settlement_token_under_sha256_construction() {
    let secret = "abcdefghijklmnop";
    let id = "stl_123";
    let viewer = b"public";
    let token = crypto::sign_settlement_token(secret, id, viewer);
    assert_eq!(token.len(), 64);
    assert!(crypto::verify_settlement_token(secret, id, viewer, &token));
    assert!(!crypto::verify_settlement_token(secret, id, b"admin", &token));
}

#[test]
fn session_token_roundtrip() {
    let key = crypto::session_key("super-secret", "team1");
    let now = chrono::Utc::now().timestamp();
    let token = crypto::sign_session(&key, 42, now + 600);
    let (uid, _) = crypto::verify_session(&key, &token).expect("verify");
    assert_eq!(uid, 42);
}

#[test]
fn session_token_expired_rejected() {
    let key = crypto::session_key("super-secret", "team1");
    let now = chrono::Utc::now().timestamp();
    let token = crypto::sign_session(&key, 42, now - 10);
    assert!(crypto::verify_session(&key, &token).is_none());
}
