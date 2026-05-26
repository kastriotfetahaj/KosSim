use crate::state::AppState;

pub fn validate(script: &str) -> bool {
    let folded = script.replace('\n', " ").to_ascii_lowercase();
    !folded.contains("/vault/") && !folded.contains("private:")
}

pub fn execute(state: &AppState, script: &str) -> serde_json::Value {
    if !validate(script) {
        return serde_json::json!({"error": "query_scope_denied"});
    }
    let mut out = Vec::new();
    for token in script.split_whitespace() {
        if let Some(raw) = token.strip_prefix("LOAD:") {
            let doc_id = raw.strip_prefix("public::").unwrap_or(raw);
            if let Some(doc) = state.docs.get(doc_id) {
                out.push(serde_json::json!({"id": doc.id, "body": doc.body}));
            }
        }
        if token == "LIST:public" {
            for doc in state.docs.values().filter(|d| d.public) {
                out.push(serde_json::json!({"id": doc.id, "body": doc.body}));
            }
        }
        if token == "COUNT:class=public" {
            let n = state.docs.values().filter(|d| d.class_name == "public").count();
            out.push(serde_json::json!({"count": n}));
        }
    }
    serde_json::json!({"rows": out, "engine": "lfql-2.7"})
}
