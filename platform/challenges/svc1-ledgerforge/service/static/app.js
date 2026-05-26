const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[c]));
}

async function api(path, init = {}) {
  const headers = init.headers ? { ...init.headers } : {};
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...init, credentials: "same-origin", headers });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { error: "bad_json", raw: text }; }
  if (!res.ok) throw new Error(body && body.error ? body.error : `http_${res.status}`);
  return body;
}

function setView(view) {
  $$(".rail-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "settlements") refreshSettlements();
  if (view === "audit") refreshAudit();
}

async function refreshJournal() {
  try {
    const { docs, count } = await api("/api/docs");
    $("#doc-count").textContent = `${count} entries`;
    $("#docs").innerHTML = docs.map((doc) => `
      <article class="doc">
        <h3>${esc(doc.class)}</h3>
        <p>${esc(doc.path)} · ${doc.public ? "public" : "private"}</p>
        <code>${esc(doc.id)}</code>
      </article>
    `).join("");
    const root = await api("/debug/merkle");
    $("#root").textContent = root.root;
  } catch (err) {
    $("#docs").innerHTML = `<div class="doc"><h3>error</h3><p>${esc(err.message)}</p></div>`;
  }
}

async function runQuery() {
  try {
    const res = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({ script: $("#script").value }),
    });
    $("#output").textContent = JSON.stringify(res, null, 2);
  } catch (err) {
    $("#output").textContent = `error: ${err.message}`;
  }
}

async function refreshSettlements() {
  try {
    const res = await api("/api/settlements?branch=public-noise");
    $("#settlements-out").textContent = JSON.stringify(res, null, 2);
  } catch (err) {
    $("#settlements-out").textContent = `error: ${err.message}`;
  }
}

async function refreshAudit() {
  try {
    const res = await api("/api/admin/audit?limit=80");
    $("#audit-out").textContent = res.entries
      .map((e) => `${new Date(e.ts).toISOString()} ${e.actor} ${e.action} ${e.target} ${e.detail}`)
      .join("\n");
  } catch (err) {
    $("#audit-out").textContent = `not available: ${err.message}`;
  }
}

async function refreshSession() {
  try {
    const me = await api("/api/accounts/me");
    $("#session").textContent = `session: ${me.username} (${me.role})`;
  } catch {
    $("#session").textContent = "session: anonymous";
  }
}

function bindNav() {
  $$(".rail-item").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view)),
  );
}

function bindSignIn() {
  $("#sign-form").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    event.preventDefault();
    const username = $("#sign-user").value.trim();
    const password = $("#sign-pass").value;
    const action = button.dataset.action;
    const out = $("#sign-out");
    try {
      if (action === "register") {
        const res = await api("/api/accounts/register", { method: "POST", body: JSON.stringify({ username, password }) });
        out.textContent = `registered: ${res.username}`;
      } else if (action === "login") {
        const res = await api("/api/accounts/login", { method: "POST", body: JSON.stringify({ username, password }) });
        out.textContent = `logged in: ${res.username}`;
      } else if (action === "logout") {
        await api("/api/accounts/logout", { method: "POST" });
        out.textContent = "logged out";
      }
      await refreshSession();
    } catch (err) {
      out.textContent = `error: ${err.message}`;
    }
  });
}

function bindTreasury() {
  $("#treasury-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("#treasury-key").value.trim();
    const id = $("#treasury-id").value.trim();
    if (!key || !id) return;
    try {
      const res = await api(`/api/treasury/receipts/${encodeURIComponent(id)}`, {
        headers: { "X-Viewer-Key": key },
      });
      $("#treasury-out").textContent = JSON.stringify(res, null, 2);
    } catch (err) {
      $("#treasury-out").textContent = `error: ${err.message}`;
    }
  });
}

bindNav();
bindSignIn();
bindTreasury();
$("#run").addEventListener("click", runQuery);
$("#refresh").addEventListener("click", refreshJournal);
$("#audit-refresh").addEventListener("click", refreshAudit);

await refreshSession();
await refreshJournal();
await runQuery();
setInterval(refreshJournal, 20_000);
