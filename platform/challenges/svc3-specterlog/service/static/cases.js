import { $, $$, api, esc } from "/static/app.js";

let selected = null;

export function renderCases() {
  $("#case-new").addEventListener("click", async () => {
    const title = prompt("case title");
    if (!title) return;
    const summary = prompt("case summary") ?? "";
    try {
      await api("/api/cases", {
        method: "POST",
        body: JSON.stringify({ title, summary, public: false }),
      });
      await refreshCases();
    } catch (err) {
      alert(`error: ${err.message}`);
    }
  });
}

export async function refreshCases() {
  try {
    const { cases } = await api("/api/cases?scope=mine");
    $("#case-list").innerHTML = cases
      .map(
        (c) => `<div class="card${selected === c.id ? " selected" : ""}" data-id="${esc(c.id)}">
          <h3>${esc(c.title)}</h3>
          <p>${c.public ? "public" : "private"} · owner #${c.owner}</p>
        </div>`,
      )
      .join("");
    $$("#case-list .card").forEach((node) =>
      node.addEventListener("click", () => loadCase(node.dataset.id)),
    );
    if (selected) await loadCase(selected);
  } catch (err) {
    $("#case-list").innerHTML = `<div class="card"><h3>error</h3><p>${esc(err.message)}</p></div>`;
  }
}

async function loadCase(id) {
  selected = id;
  try {
    const c = await api(`/api/cases/${encodeURIComponent(id)}`);
    const { attachments } = await api(`/api/cases/${encodeURIComponent(id)}/attachments`);
    $("#case-detail").textContent = JSON.stringify({ case: c, attachments }, null, 2);
    $$("#case-list .card").forEach((node) =>
      node.classList.toggle("selected", node.dataset.id === id),
    );
  } catch (err) {
    $("#case-detail").textContent = `error: ${err.message}`;
  }
}
