use std::collections::HashMap;

use sha2::{Digest, Sha256};

use crate::state::Doc;

pub fn normalize_path(raw: &str) -> String {
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

pub fn merkle_root_pairs(pairs: &[(String, String)]) -> String {
    let mut leaves: Vec<String> = pairs.iter().map(|(id, body)| leaf_hash(id, body)).collect();
    leaves.sort();
    if leaves.is_empty() {
        return "0".repeat(64);
    }
    while leaves.len() > 1 {
        let mut next = Vec::new();
        for chunk in leaves.chunks(2) {
            let right = chunk.get(1).unwrap_or(&chunk[0]);
            let mut h = Sha256::new();
            h.update(chunk[0].as_bytes());
            h.update(right.as_bytes());
            next.push(hex::encode(h.finalize()));
        }
        leaves = next;
    }
    leaves[0].clone()
}

pub fn merkle_root(docs: &HashMap<String, Doc>) -> String {
    let pairs: Vec<(String, String)> = docs
        .values()
        .map(|doc| (doc.id.clone(), doc.body.clone()))
        .collect();
    merkle_root_pairs(&pairs)
}

pub fn merkle_path(docs: &HashMap<String, Doc>, doc_id: &str) -> Option<Vec<String>> {
    let mut entries: Vec<(String, String)> = docs
        .values()
        .map(|doc| (doc.id.clone(), leaf_hash(&doc.id, &doc.body)))
        .collect();
    entries.sort_by(|a, b| a.1.cmp(&b.1));
    let mut target_idx = entries.iter().position(|(id, _)| id == doc_id)?;
    let mut layer: Vec<String> = entries.iter().map(|(_, leaf)| leaf.clone()).collect();
    let mut path = Vec::new();
    while layer.len() > 1 {
        let pair_idx = target_idx ^ 1;
        if pair_idx < layer.len() {
            path.push(layer[pair_idx].clone());
        }
        let mut next = Vec::new();
        for chunk in layer.chunks(2) {
            let right = chunk.get(1).unwrap_or(&chunk[0]);
            let mut h = Sha256::new();
            h.update(chunk[0].as_bytes());
            h.update(right.as_bytes());
            next.push(hex::encode(h.finalize()));
        }
        target_idx /= 2;
        layer = next;
    }
    Some(path)
}

pub fn public_projection(doc: &Doc) -> serde_json::Value {
    serde_json::json!({
        "id": doc.id,
        "path": doc.path,
        "class": doc.class_name,
        "owner": doc.owner,
        "public": doc.public,
        "snapshot": doc.snapshot
    })
}
