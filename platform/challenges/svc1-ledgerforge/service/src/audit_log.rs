use rusqlite::{params, Connection};

use crate::db;

pub fn record(conn: &Connection, actor: &str, action: &str, target: &str, detail: &str) {
    let _ = conn.execute(
        "INSERT INTO audit (actor, action, target, detail, ts) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![actor, action, target, detail, db::now_ms()],
    );
}

pub fn recent(conn: &Connection, limit: i64) -> Vec<serde_json::Value> {
    let capped = limit.clamp(1, 200);
    let mut stmt = match conn.prepare(
        "SELECT id, actor, action, target, detail, ts FROM audit ORDER BY id DESC LIMIT ?1",
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    let rows = stmt.query_map(params![capped], |row| {
        Ok(serde_json::json!({
            "id": row.get::<_, i64>(0)?,
            "actor": row.get::<_, String>(1)?,
            "action": row.get::<_, String>(2)?,
            "target": row.get::<_, String>(3)?,
            "detail": row.get::<_, String>(4)?,
            "ts": row.get::<_, i64>(5)?,
        }))
    });
    rows.map(|iter| iter.flatten().collect()).unwrap_or_default()
}

pub fn trim(conn: &Connection, keep: i64) {
    let _ = conn.execute(
        "DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT ?1)",
        params![keep],
    );
}
