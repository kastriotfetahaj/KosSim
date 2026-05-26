import { renderCases, refreshCases } from "/static/cases.js";
import { renderBriefs, refreshBriefs } from "/static/briefs.js";

const state = {
  user: null,
  events: [],
  view: "console",
};

export function $(sel) {
  return document.querySelector(sel);
}

export function $$(sel) {
  return Array.from(document.querySelectorAll(sel));
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[c]));
}

export async function api(path, init = {}) {
  const headers = init.headers ? { ...init.headers } : {};
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...init, credentials: "same-origin", headers });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { error: "bad_json", raw: text }; }
  if (!res.ok) {
    const error = body && body.error ? body.error : `http_${res.status}`;
    throw new Error(error);
  }
  return body;
}

function setView(view) {
  state.view = view;
  $$(".nav-link").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "cases") refreshCases();
  if (view === "briefs") refreshBriefs();
  if (view === "audit") refreshAudit();
}

function print(kind, text) {
  const node = document.createElement("div");
  node.className = `line ${kind}`;
  node.textContent = text;
  $("#screen").appendChild(node);
  node.scrollIntoView({ block: "end" });
}

async function runCommand(raw) {
  const [name, ...args] = raw.trim().split(/\s+/);
  if (!name) return;
  print("cmd", `sl$ ${raw}`);
  try {
    if (name === "help") {
      print("out", "commands: events, cursor, replay, search, archive <id>, whoami, clear");
    } else if (name === "events") {
      const { events } = await api("/api/events");
      print("out", events.map((ev, i) => `${i + 1}. ${ev.stream} ${ev.kind} ${ev.archive}`).join("\n") || "(empty)");
    } else if (name === "cursor") {
      const res = await api("/api/cursor/public");
      print("out", JSON.stringify(res, null, 2));
    } else if (name === "replay") {
      const cursor = (await api("/api/cursor/public")).cursor;
      const res = await api(`/api/replay?cursor=${encodeURIComponent(cursor)}`);
      print("out", JSON.stringify(res, null, 2));
    } else if (name === "search") {
      const res = await api("/api/search?filter=public&project=meta");
      print("out", JSON.stringify(res, null, 2));
    } else if (name === "archive") {
      const archive = args[0] || state.events[0]?.archive;
      if (!archive) return print("err", "archive id required");
      const res = await api(`/api/archive/${encodeURIComponent(archive)}`);
      print("out", JSON.stringify(res, null, 2));
    } else if (name === "whoami") {
      print("out", JSON.stringify(state.user ?? { team: "anon" }, null, 2));
    } else if (name === "clear") {
      $("#screen").replaceChildren();
    } else {
      print("err", `unknown command: ${name}`);
    }
  } catch (err) {
    print("err", String(err.message ?? err));
  }
}

async function refreshEvents() {
  const { events } = await api("/api/events");
  state.events = events;
  $("#event-count").textContent = `${events.length} events indexed`;
  $("#events").innerHTML = events.slice(-50).map((ev, index) => `
    <article class="event">
      <b>${String(index + 1).padStart(2, "0")}</b>
      <strong>${esc(ev.stream)}</strong> ${esc(ev.kind)}
      <code>${esc(ev.archive)}</code>
    </article>
  `).join("");
}

async function refreshSession() {
  try {
    const me = await api("/api/accounts/me");
    state.user = me;
    $("#session-banner").textContent = `session: ${me.username} (${me.role})`;
  } catch {
    state.user = null;
    $("#session-banner").textContent = "session: anonymous";
  }
}

async function refreshAudit() {
  try {
    const { entries } = await api("/api/admin/audit?limit=80");
    $("#audit-log").textContent = entries
      .map((e) => `${new Date(e.ts).toISOString()} ${e.actor} ${e.action} ${e.target} ${e.detail}`)
      .join("\n");
  } catch (err) {
    $("#audit-log").textContent = `not available: ${err.message}`;
  }
}

function bindNav() {
  $$(".nav-link").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view)),
  );
}

function bindCli() {
  $("#cli").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#cmd");
    const raw = input.value;
    input.value = "";
    await runCommand(raw);
  });
}

function bindSignIn() {
  $("#sign-in-form").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    event.preventDefault();
    const action = button.dataset.action;
    const username = $("#sign-user").value.trim();
    const password = $("#sign-pass").value;
    const feedback = $("#sign-feedback");
    try {
      if (action === "register") {
        const res = await api("/api/accounts/register", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        feedback.textContent = `registered: ${res.username}`;
      } else if (action === "login") {
        const res = await api("/api/accounts/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        feedback.textContent = `logged in: ${res.username}`;
      } else if (action === "logout") {
        await api("/api/accounts/logout", { method: "POST" });
        feedback.textContent = "logged out";
      }
      await refreshSession();
    } catch (err) {
      feedback.textContent = `error: ${err.message}`;
    }
  });
}

bindNav();
bindCli();
bindSignIn();
renderCases();
renderBriefs();
$("#audit-refresh").addEventListener("click", refreshAudit);

await refreshSession();
await refreshEvents();
setInterval(refreshEvents, 15_000);

print("out", "SpecterLog shell ready. Type help.");
