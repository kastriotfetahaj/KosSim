import Fastify from "fastify";
import websocket from "@fastify/websocket";
import { readFileSync } from "node:fs";
import { buildRoutes } from "./routes";
import { Store } from "./state";
import { startIndexer } from "./indexer";
import { closeDatabase } from "./db";
import { putFlag as putFlagDispatch } from "./flagstores";

const STATIC_ROOT = process.env.SPECTERLOG_STATIC_DIR ?? "/app/static";
const PORT = Number(process.env.PORT ?? 8080);

const app = Fastify({ logger: false, bodyLimit: 1_500_000 });

const secret = process.env.SERVICE_PUSH_SECRET ?? "rotate-secret";
const store = new Store({
  team: process.env.TEAM_NAME ?? "team",
  service: process.env.SERVICE_NAME ?? "svc3",
  secret,
});

await app.register(websocket);

const bootFlag = process.env.BOOT_FLAG ?? "FLAG{BOOT_SPECTERLOG}";
if (
  !store.db
    .query("SELECT 1 FROM flag_index WHERE tick = 0 AND variant = 0")
    .get()
) {
  putFlagDispatch(store.db, store, secret, store.dataDir, 0, 0, bootFlag);
  putFlagDispatch(store.db, store, secret, store.dataDir, 0, 1, `${bootFlag}_EVIDENCE`);
  putFlagDispatch(store.db, store, secret, store.dataDir, 0, 2, `${bootFlag}_DIRECTIVE`);
}

buildRoutes(app, store);

app.get("/static/:name", async (req, reply) => {
  const name = (req.params as { name: string }).name.replace(/[^a-zA-Z0-9_.-]/g, "");
  const type = name.endsWith(".css")
    ? "text/css"
    : name.endsWith(".js")
      ? "application/javascript"
      : "application/octet-stream";
  return reply.type(type).send(readFileSync(`${STATIC_ROOT}/${name}`, "utf8"));
});

const indexer = startIndexer(store.db, store);

function shutdown(signal: string): void {
  app.log.info(`received ${signal}`);
  indexer.stop();
  app.close().then(() => {
    closeDatabase(store.db);
    process.exit(0);
  }).catch((err) => {
    console.error("shutdown_error", err);
    process.exit(1);
  });
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

await app.listen({ host: "0.0.0.0", port: PORT });
