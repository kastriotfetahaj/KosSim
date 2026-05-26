import type { Database } from "bun:sqlite";
import type { AuditRow } from "./db";

export function record(
  db: Database,
  actor: string,
  action: string,
  target: string,
  detail: string = "",
): void {
  db.run(
    "INSERT INTO audit (actor, action, target, detail, ts) VALUES (?, ?, ?, ?, ?)",
    [actor, action, target, detail, Date.now()],
  );
}

export function recent(db: Database, limit: number = 50): AuditRow[] {
  const capped = Math.min(Math.max(Math.floor(limit), 1), 200);
  return db
    .query(
      "SELECT id, actor, action, target, detail, ts FROM audit ORDER BY id DESC LIMIT ?",
    )
    .all(capped) as AuditRow[];
}

export function trim(db: Database, keep: number): number {
  const result = db.run(
    "DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT ?)",
    [keep],
  );
  return Number(result.changes ?? 0);
}
