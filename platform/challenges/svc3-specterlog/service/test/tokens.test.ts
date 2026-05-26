import { describe, expect, test } from "bun:test";
import {
  signCursor,
  verifyCursor,
  signDownload,
  verifyDownload,
  signView,
  verifyView,
  signSession,
  verifySession,
} from "../src/tokens";

const SECRET = "test-secret:svc3:team0";

describe("cursor", () => {
  test("roundtrip", () => {
    const token = signCursor(SECRET, { stream: "public", after: 0, exp: Date.now() + 60_000 });
    const parsed = verifyCursor(SECRET, token);
    expect(parsed).not.toBeNull();
    expect(parsed?.stream).toBe("public");
  });

  test("tampered body rejected", () => {
    const token = signCursor(SECRET, { stream: "public", after: 0 });
    const [body, sig] = token.split(".");
    const malicious = Buffer.from(JSON.stringify({ stream: "private", after: 0 })).toString("base64url");
    const fake = `${malicious}.${sig}`;
    expect(verifyCursor(SECRET, fake)).toBeNull();
  });

  test("missing pieces rejected", () => {
    expect(verifyCursor(SECRET, "")).toBeNull();
    expect(verifyCursor(SECRET, "abc")).toBeNull();
  });
});

describe("download signatures", () => {
  test("roundtrip", () => {
    const claim = { case_id: "c1", handle: "h1", exp: 1_000 };
    const sig = signDownload(SECRET, claim);
    expect(verifyDownload(SECRET, claim, sig)).toBe(true);
  });

  test("modified exp invalidates", () => {
    const sig = signDownload(SECRET, { case_id: "c1", handle: "h1", exp: 1_000 });
    expect(verifyDownload(SECRET, { case_id: "c1", handle: "h1", exp: 2_000 }, sig)).toBe(false);
  });
});

describe("view tokens", () => {
  test("HS256 roundtrip", () => {
    const exp = Math.floor(Date.now() / 1000) + 600;
    const token = signView(SECRET, { sub: "u1", scope: "briefs:read", brief_id: "brf_x", exp });
    const result = verifyView(SECRET, token);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.claims.brief_id).toBe("brf_x");
    }
  });

  test("alg none accepted (the bug)", () => {
    const header = Buffer.from(JSON.stringify({ alg: "none" })).toString("base64url");
    const claims = Buffer.from(JSON.stringify({ sub: "x", scope: "briefs:read", brief_id: "brf_y", exp: 0 })).toString("base64url");
    const token = `${header}.${claims}.`;
    const result = verifyView(SECRET, token);
    expect(result.ok).toBe(true);
  });

  test("unknown alg rejected", () => {
    const header = Buffer.from(JSON.stringify({ alg: "rs256" })).toString("base64url");
    const claims = Buffer.from(JSON.stringify({ sub: "x", scope: "briefs:read", brief_id: "brf_z", exp: 0 })).toString("base64url");
    const token = `${header}.${claims}.sig`;
    const result = verifyView(SECRET, token);
    expect(result.ok).toBe(false);
  });
});

describe("sessions", () => {
  test("roundtrip", () => {
    const exp = Math.floor(Date.now() / 1000) + 600;
    const token = signSession(SECRET, { uid: 42, exp });
    const parsed = verifySession(SECRET, token);
    expect(parsed?.uid).toBe(42);
  });

  test("expired rejected", () => {
    const exp = Math.floor(Date.now() / 1000) - 10;
    const token = signSession(SECRET, { uid: 1, exp });
    expect(verifySession(SECRET, token)).toBeNull();
  });
});
