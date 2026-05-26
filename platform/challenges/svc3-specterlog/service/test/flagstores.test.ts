import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/state";
import { putFlag, getFlag, putNoise, getNoise } from "../src/flagstores";

let dir: string;
let prevDir: string | undefined;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "specter-fs-"));
  prevDir = process.env.SPECTERLOG_DATA_DIR;
  process.env.SPECTERLOG_DATA_DIR = dir;
});

afterEach(() => {
  if (prevDir === undefined) delete process.env.SPECTERLOG_DATA_DIR;
  else process.env.SPECTERLOG_DATA_DIR = prevDir;
  rmSync(dir, { recursive: true, force: true });
});

function build(): Store {
  return new Store({ team: "team0", service: "svc3", secret: "rotate-secret" });
}

describe("flagstores", () => {
  test("variant 0 put/get round trip", () => {
    const store = build();
    const flag = "FLAG{V0_RT}";
    const info = putFlag(store.db, store, "rotate-secret", dir, 100, 0, flag);
    expect(info.p).toBe(0);
    expect(getFlag(store.db, store, dir, 100, 0, flag)).toBe(true);
    expect(getFlag(store.db, store, dir, 100, 0, "FLAG{OTHER}")).toBe(false);
  });

  test("variant 1 put/get with attachment-backed flag", () => {
    const store = build();
    const flag = "FLAG{V1_RT}";
    const info = putFlag(store.db, store, "rotate-secret", dir, 101, 1, flag);
    expect(info.p).toBe(1);
    expect(info.exp).toBeDefined();
    expect(info.sig).toBeDefined();
    expect(getFlag(store.db, store, dir, 101, 1, flag)).toBe(true);
  });

  test("variant 2 put/get with brief-backed flag", () => {
    const store = build();
    const flag = "FLAG{V2_RT}";
    const info = putFlag(store.db, store, "rotate-secret", dir, 102, 2, flag);
    expect(info.p).toBe(2);
    expect(typeof info.a).toBe("string");
    expect(typeof info.b).toBe("string");
    expect(getFlag(store.db, store, dir, 102, 2, flag)).toBe(true);
  });

  test("flag index survives a reopen", () => {
    const first = build();
    putFlag(first.db, first, "rotate-secret", dir, 200, 0, "FLAG{PERSIST_V0}");
    putFlag(first.db, first, "rotate-secret", dir, 200, 2, "FLAG{PERSIST_V2}");
    first.db.close();
    const second = build();
    expect(getFlag(second.db, second, dir, 200, 0, "FLAG{PERSIST_V0}")).toBe(true);
    expect(getFlag(second.db, second, dir, 200, 2, "FLAG{PERSIST_V2}")).toBe(true);
  });

  test("noise round trips for each variant", () => {
    const store = build();
    for (const variant of [0, 1, 2]) {
      expect(putNoise(store.db, store, dir, 300 + variant, variant)).toBe(true);
      expect(getNoise(store.db, store, dir, 300 + variant, variant)).toBe(true);
    }
  });
});
