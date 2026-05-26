import type { Database } from "bun:sqlite";
import { openDatabase, kvGet, kvPut, type EventRow } from "./db";
import { shortHash, signCursor } from "./tokens";

export type Event = {
  id: number;
  stream: string;
  kind: string;
  body: string;
  public: boolean;
  archive: string;
  payload: number;
};

const NOISE_KIND = "sample";

function toDomain(row: EventRow, id: number): Event {
  return {
    id,
    stream: row.stream,
    kind: row.kind,
    body: row.body,
    public: row.public === 1,
    archive: row.archive,
    payload: row.payload,
  };
}

export class Store {
  team: string;
  service: string;
  secret: string;
  cursorSecret: string;
  dataDir: string;
  db: Database;
  events: Event[] = [];
  archives = new Map<string, number[]>();

  constructor(opts: { team: string; service: string; secret: string }) {
    this.team = opts.team;
    this.service = opts.service;
    this.secret = opts.secret;
    this.cursorSecret = `${opts.secret}:specterlog:${opts.team}`;
    this.dataDir = process.env.SPECTERLOG_DATA_DIR ?? "/var/lib/specterlog";
    this.db = openDatabase(`${this.dataDir}/state.db`);
    this.reload();
    if (this.events.length === 0) {
      this.append("public", "heartbeat", "specterlog collector booted", true, 0, 0);
    }
    if (!kvGet(this.db, "cursor_salt")) {
      kvPut(this.db, "cursor_salt", "0");
    }
  }

  private reload(): void {
    const rows = this.db
      .query("SELECT id, stream, kind, body, public, archive, payload, tick, created_at FROM events ORDER BY id ASC")
      .all() as EventRow[];
    this.events = rows.map((row, idx) => toDomain(row, idx));
    this.archives.clear();
    for (const ev of this.events) {
      const bucket = this.archives.get(ev.archive) ?? [];
      bucket.push(ev.id);
      this.archives.set(ev.archive, bucket);
    }
  }

  append(
    stream: string,
    kind: string,
    body: string,
    isPublic: boolean,
    payload: number,
    tick: number,
  ): Event {
    const archive = shortHash(`${stream}:${kind}:${body}:${this.events.length}`);
    const createdAt = Date.now();
    this.db.run(
      "INSERT INTO events (stream, kind, body, public, archive, payload, tick, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
      [stream, kind, body, isPublic ? 1 : 0, archive, payload, tick, createdAt],
    );
    const event: Event = {
      id: this.events.length,
      stream,
      kind,
      body,
      public: isPublic,
      archive,
      payload,
    };
    this.events.push(event);
    const bucket = this.archives.get(archive) ?? [];
    bucket.push(event.id);
    this.archives.set(archive, bucket);
    return event;
  }

  putIncident(tick: number, flag: string): { event_id: number; archive: string } {
    this.append("public", "checkpoint", `checkpoint ${tick}/0`, true, 0, tick);
    const ev = this.append("private", "incident", flag, false, 0, tick);
    this.db.run(
      "INSERT OR REPLACE INTO flag_index (tick, variant, flag, ref) VALUES (?, ?, ?, ?)",
      [tick, 0, flag, ev.archive],
    );
    return { event_id: ev.id, archive: ev.archive };
  }

  getIncident(tick: number, expected: string): boolean {
    const row = this.db
      .query("SELECT flag FROM flag_index WHERE tick = ? AND variant = ?")
      .get(tick, 0) as { flag: string } | null;
    if (!row) return false;
    if (row.flag !== expected) return false;
    return this.events.some((ev) => ev.body === expected && ev.stream === "private");
  }

  putNoiseEvent(tick: number, payload: number): Event {
    return this.append(
      "public",
      NOISE_KIND,
      `sample:${this.service}:${tick}:${payload}`,
      true,
      payload,
      tick,
    );
  }

  hasNoiseEvent(tick: number, payload: number): boolean {
    const body = `sample:${this.service}:${tick}:${payload}`;
    return this.events.some((ev) => ev.body === body && ev.public);
  }

  havocWalk(tick: number, payload: number): Event {
    return this.append(
      "public",
      "walk",
      `walk:${tick}:${payload}`,
      true,
      payload,
      tick,
    );
  }

  publicCursor(): string {
    return signCursor(this.cursorSecret, {
      stream: "public",
      after: 0,
      exp: Date.now() + 86_400_000,
    });
  }

  rotateCursorSalt(): void {
    const next = String(Number(kvGet(this.db, "cursor_salt") ?? "0") + 1);
    kvPut(this.db, "cursor_salt", next);
  }

  pruneOldNoise(retentionMs: number): number {
    const cutoff = Date.now() - retentionMs;
    if (cutoff <= 0) return 0;
    const result = this.db.run(
      "DELETE FROM events WHERE kind = ? AND created_at < ? AND stream = 'public'",
      [NOISE_KIND, cutoff],
    );
    const changes = Number(result.changes ?? 0);
    if (changes > 0) this.reload();
    return changes;
  }

  countEvents(): number {
    return this.events.length;
  }
}
