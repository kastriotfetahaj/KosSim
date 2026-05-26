import type { Database } from "bun:sqlite";
import type { FastifyInstance } from "fastify";
import type { Store } from "./state";
import { readStats } from "./indexer";

export function opsRoutes(app: FastifyInstance, db: Database, store: Store): void {
  app.get("/health/db", async (_, reply) => {
    try {
      const row = store.db.query("SELECT 1 AS ok").get() as { ok: number };
      if (row.ok !== 1) return reply.code(503).send({ status: "down" });
      return { status: "up", path: "state.db" };
    } catch (err) {
      return reply.code(503).send({ status: "down", message: String(err) });
    }
  });

  app.get("/api/indexer/stats", async () => {
    return { stats: readStats(db), events: store.countEvents() };
  });

  app.get("/api/legacy-token/parse", async () => ({
    parser: "compat",
    accepts: false,
    note: "use /api/briefs/:id/token for view tokens",
  }));
}
