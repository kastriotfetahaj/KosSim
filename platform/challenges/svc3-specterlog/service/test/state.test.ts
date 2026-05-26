import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/state";

let dir: string;
let prevDir: string | undefined;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "specter-"));
  prevDir = process.env.SPECTERLOG_DATA_DIR;
  process.env.SPECTERLOG_DATA_DIR = dir;
});

afterEach(() => {
  if (prevDir === undefined) delete process.env.SPECTERLOG_DATA_DIR;
  else process.env.SPECTERLOG_DATA_DIR = prevDir;
  rmSync(dir, { recursive: true, force: true });
});

function newStore(): Store {
  return new Store({ team: "team0", service: "svc3", secret: "rotate-secret" });
}

describe("store", () => {
  test("boot heartbeat appended", () => {
    const store = newStore();
    expect(store.countEvents()).toBeGreaterThan(0);
    expect(store.events[0].kind).toBe("heartbeat");
    expect(store.events[0].public).toBe(true);
  });

  test("incident write surfaces public checkpoint + private body", () => {
    const store = newStore();
    const flag = "FLAG{TEST_INCIDENT}";
    store.putIncident(42, flag);
    const incidents = store.events.filter((ev) => ev.body === flag);
    expect(incidents.length).toBe(1);
    expect(incidents[0].stream).toBe("private");
    expect(incidents[0].public).toBe(false);
  });

  test("noise survives across reload", () => {
    const store = newStore();
    store.putNoiseEvent(7, 0);
    expect(store.hasNoiseEvent(7, 0)).toBe(true);

    const reopened = newStore();
    expect(reopened.hasNoiseEvent(7, 0)).toBe(true);
  });

  test("getIncident requires matching flag", () => {
    const store = newStore();
    store.putIncident(11, "FLAG{ALPHA}");
    expect(store.getIncident(11, "FLAG{ALPHA}")).toBe(true);
    expect(store.getIncident(11, "FLAG{BETA}")).toBe(false);
    expect(store.getIncident(12, "FLAG{ALPHA}")).toBe(false);
  });

  test("pruneOldNoise leaves recent samples", () => {
    const store = newStore();
    store.putNoiseEvent(1, 0);
    const dropped = store.pruneOldNoise(60_000);
    expect(dropped).toBe(0);
    expect(store.hasNoiseEvent(1, 0)).toBe(true);
  });
});
