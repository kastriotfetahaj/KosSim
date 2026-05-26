import type { Database } from "bun:sqlite";
import type { Store } from "./state";
import { trim as auditTrim, record as auditRecord } from "./audit";

const NOISE_RETENTION_MS = 30 * 60_000;
const SESSION_GC_INTERVAL_MS = 60_000;
const AUDIT_TRIM_KEEP = 5_000;

export type IndexerHandle = {
  stop(): void;
};

export type IndexerStats = {
  cycles: number;
  archives_indexed: number;
  noise_pruned: number;
  sessions_collected: number;
  last_cycle_ms: number;
  last_cycle_at: number;
};

export function startIndexer(db: Database, store: Store): IndexerHandle {
  const stats: IndexerStats = {
    cycles: 0,
    archives_indexed: 0,
    noise_pruned: 0,
    sessions_collected: 0,
    last_cycle_ms: 0,
    last_cycle_at: 0,
  };

  function cycle(): void {
    const start = Date.now();
    const purged = store.pruneOldNoise(NOISE_RETENTION_MS);
    stats.noise_pruned += purged;

    const sessionResult = db.run(
      "DELETE FROM sessions WHERE expires_at < ?",
      [Math.floor(Date.now() / 1000)],
    );
    const sessionDrop = Number(sessionResult.changes ?? 0);
    stats.sessions_collected += sessionDrop;

    const tokenResult = db.run(
      "DELETE FROM api_tokens WHERE revoked = 1 AND expires_at < ?",
      [Date.now() - 86_400_000],
    );
    stats.archives_indexed += Number(tokenResult.changes ?? 0);

    auditTrim(db, AUDIT_TRIM_KEEP);

    stats.cycles += 1;
    stats.last_cycle_ms = Date.now() - start;
    stats.last_cycle_at = Date.now();
    putStats(db, stats);
  }

  const handle = setInterval(cycle, SESSION_GC_INTERVAL_MS);
  cycle();
  auditRecord(db, "system", "indexer.start", "indexer");
  return {
    stop(): void {
      clearInterval(handle);
      auditRecord(db, "system", "indexer.stop", "indexer");
    },
  };
}

function putStats(db: Database, stats: IndexerStats): void {
  db.run(
    "INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)",
    ["indexer_stats", JSON.stringify(stats)],
  );
}

export function readStats(db: Database): IndexerStats | null {
  const row = db.query("SELECT v FROM kv WHERE k = ?").get("indexer_stats") as { v: string } | null;
  if (!row) return null;
  try {
    return JSON.parse(row.v) as IndexerStats;
  } catch {
    return null;
  }
}
