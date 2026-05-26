import { $, $$, api, esc } from "/static/app.js";

let selected = null;

export function renderBriefs() {
  $("#brief-new").addEventListener("click", async () => {
    const caseId = prompt("case id");
    if (!caseId) return;
    const title = prompt("brief title");
    if (!title) return;
    const body = prompt("brief body") ?? "";
    try {
      await api("/api/briefs", {
        method: "POST",
        body: JSON.stringify({ case_id: caseId, title, body, public: false }),
      });
      await refreshBriefs();
    } catch (err) {
      alert(`error: ${err.message}`);
    }
  });
}

export async function refreshBriefs() {
  try {
    const { briefs } = await api("/api/briefs?limit=50");
    $("#brief-list").innerHTML = briefs
      .map(
        (b) => `<div class="card${selected === b.id ? " selected" : ""}" data-id="${esc(b.id)}">
          <h3>${esc(b.title)}</h3>
          <p>${b.public ? "public" : "private"} · case ${esc(b.case_id)}</p>
        </div>`,
      )
      .join("");
    $$("#brief-list .card").forEach((node) =>
      node.addEventListener("click", () => loadBrief(node.dataset.id)),
    );
    if (selected) await loadBrief(selected);
  } catch (err) {
    $("#brief-list").innerHTML = `<div class="card"><h3>error</h3><p>${esc(err.message)}</p></div>`;
  }
}

async function loadBrief(id) {
  selected = id;
  try {
    const meta = await api(`/api/briefs/${encodeURIComponent(id)}`);
    let body = meta;
    if (!meta.body) {
      try {
        const tok = await api(`/api/briefs/${encodeURIComponent(id)}/token`, { method: "POST" });
        const view = await api(`/api/briefs/${encodeURIComponent(id)}/view`, {
          headers: { Authorization: `Bearer ${tok.token}` },
        });
        body = view.brief;
      } catch (err) {
        body = { error: err.message, meta };
      }
    }
    const { comments } = await api(`/api/briefs/${encodeURIComponent(id)}/comments`).catch(() => ({ comments: [] }));
    $("#brief-detail").textContent = JSON.stringify({ brief: body, comments }, null, 2);
    $$("#brief-list .card").forEach((node) =>
      node.classList.toggle("selected", node.dataset.id === id),
    );
  } catch (err) {
    $("#brief-detail").textContent = `error: ${err.message}`;
  }
}
