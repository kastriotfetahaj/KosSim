import type { FastifyInstance } from "fastify";
import { readFileSync } from "node:fs";
import { authorized, type EnoTask, type EnoResult } from "./eno";
import type { Store } from "./state";
import { verifyCursor } from "./tokens";
import { opsRoutes } from "./ops";
import { accountRoutes } from "./accounts";
import { caseRoutes } from "./cases";
import { briefRoutes } from "./briefs";
import { attachmentRoutes } from "./attachments";
import { rateRoutes } from "./ratelimit";
import { apiTokenRoutes } from "./apitokens";
import { adminRoutes } from "./admin";
import { putFlag, getFlag, putNoise, getNoise, havoc } from "./flagstores";

const STATIC_ROOT = process.env.SPECTERLOG_STATIC_DIR ?? "/app/static";

export function buildRoutes(app: FastifyInstance, store: Store): void {
  const db = store.db;
  const secret = store.secret;
  const dataDir = store.dataDir;

  rateRoutes(app, db);

  app.get("/", async (_, reply) =>
    reply.type("text/html").send(readFileSync(`${STATIC_ROOT}/index.html`, "utf8")),
  );
  app.get("/health", async () => ({
    status: "up",
    name: "specterlog",
    service: `${store.team}/${store.service}`,
  }));
  app.get("/whoami", async () => ({
    team: store.team,
    service: store.service,
    runtime: "typescript-bun-fastify",
  }));
  app.get("/service", async (req, reply) => {
    if (!authorized(req)) return reply.code(403).send({ error: "forbidden" });
    return {
      serviceName: "specterlog",
      flagVariants: 3,
      noiseVariants: 3,
      havocVariants: 9,
    };
  });

  app.post("/", async (req, reply): Promise<EnoResult> => {
    if (!authorized(req)) {
      reply.code(403);
      return { result: "INTERNAL_ERROR", message: "forbidden" };
    }
    const task = req.body as EnoTask;
    const method = (task.method ?? "").toUpperCase();
    const tick = task.related_round_id ?? task.current_round_id ?? 0;
    const variant = task.variant_id ?? 0;

    if (method === "PUTFLAG") {
      if (!task.flag) return { result: "INTERNAL_ERROR", message: "missing flag" };
      try {
        const info = putFlag(db, store, secret, dataDir, tick, variant, task.flag);
        return { result: "OK", attack_info: JSON.stringify(info) };
      } catch (err) {
        return { result: "MUMBLE", message: err instanceof Error ? err.message : "putflag" };
      }
    }
    if (method === "GETFLAG") {
      const found = getFlag(db, store, dataDir, tick, variant, task.flag ?? "");
      return { result: found ? "OK" : "MUMBLE" };
    }
    if (method === "PUTNOISE") {
      const ok = putNoise(db, store, dataDir, tick, variant);
      return { result: ok ? "OK" : "MUMBLE" };
    }
    if (method === "GETNOISE") {
      const ok = getNoise(db, store, dataDir, tick, variant);
      return { result: ok ? "OK" : "MUMBLE" };
    }
    if (method === "HAVOC") {
      const ok = havoc(db, store, tick, variant);
      return { result: ok ? "OK" : "MUMBLE" };
    }
    return { result: "OK" };
  });

  app.get("/api/events", async () => ({
    events: store.events.map((ev) => ({
      id: ev.id,
      stream: ev.stream,
      kind: ev.kind,
      public: ev.public,
      archive: ev.archive,
      payload: ev.payload,
    })),
  }));

  app.get("/api/cursor/public", async () => ({
    cursor: store.publicCursor(),
    stream: "public",
  }));

  app.get("/ws", { websocket: true }, (conn: any) => {
    conn.socket.on("message", (raw: Buffer) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(raw.toString("utf8"));
      } catch {
        conn.socket.send(JSON.stringify({ error: "bad_frame" }));
        return;
      }
      if (msg.op === "subscribe") {
        const cursor = verifyCursor(store.cursorSecret, String(msg.cursor ?? ""));
        if (!cursor) {
          conn.socket.send(JSON.stringify({ error: "bad_cursor" }));
          return;
        }
        const stream = String(msg.stream ?? cursor.stream ?? "public");
        const after = Number(cursor.after ?? 0);
        conn.socket.send(
          JSON.stringify({
            events: store.events.filter(
              (ev) => ev.id >= after && ev.stream === stream && ev.public,
            ),
          }),
        );
        return;
      }
      if (msg.op === "tail") {
        conn.socket.send(
          JSON.stringify({ cursor: store.publicCursor(), count: store.events.length }),
        );
        return;
      }
      conn.socket.send(JSON.stringify({ error: "unknown_op" }));
    });
  });

  app.get("/api/replay", async (req, reply) => {
    const q = req.query as Record<string, string>;
    const cursor = verifyCursor(store.cursorSecret, q.cursor ?? "");
    if (!cursor) return reply.code(403).send({ error: "bad_cursor" });
    let stream = String(cursor.stream ?? "public");
    if (q.mode === "delta") stream = q.stream ?? stream;
    const after = Number(cursor.after ?? 0);
    return {
      events: store.events.filter(
        (ev) => ev.id >= after && ev.stream === stream && (ev.public || q.mode === "delta"),
      ),
    };
  });

  app.get("/api/search", async (req) => {
    const q = req.query as Record<string, string>;
    const filter = q.filter ?? "public";
    const project = q.project ?? "meta";
    const allowPrivate = filter.toLowerCase().includes("public||private");
    return {
      rows: store.events
        .filter((ev) => ev.public || allowPrivate)
        .map((ev) =>
          project === "body"
            ? { id: ev.id, body: ev.body }
            : { id: ev.id, stream: ev.stream, public: ev.public },
        ),
    };
  });

  app.get("/api/archive/:archive", async (req, reply) => {
    const archive = (req.params as { archive: string }).archive;
    const q = req.query as Record<string, string>;
    const ids = store.archives.get(archive);
    if (!ids) return reply.code(404).send({ error: "missing_archive" });
    const includePrivate = (q.window ?? "").startsWith("public:../private");
    return {
      archive,
      events: ids.map((id) => store.events[id]).filter((ev) => ev.public || includePrivate),
    };
  });

  accountRoutes(app, db, secret);
  caseRoutes(app, db, secret);
  briefRoutes(app, db, secret);
  attachmentRoutes(app, db, secret, dataDir);
  apiTokenRoutes(app, db, secret);
  adminRoutes(app, db, store, secret);
  opsRoutes(app, db, store);
}
