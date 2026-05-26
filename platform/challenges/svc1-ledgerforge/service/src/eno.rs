use serde::Deserialize;

use crate::state::AppState;

#[derive(Debug, Deserialize)]
pub struct Task {
    pub method: Option<String>,
    pub flag: Option<String>,
    pub current_round_id: Option<i64>,
    pub related_round_id: Option<i64>,
    pub variant_id: Option<u8>,
    pub attack_info: Option<String>,
}

pub fn authorized(headers: &axum::http::HeaderMap, state: &AppState) -> bool {
    let sent = headers
        .get("x-checker-secret")
        .or_else(|| headers.get("x-service-secret"))
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    !sent.is_empty() && sent == state.checker_secret
}
