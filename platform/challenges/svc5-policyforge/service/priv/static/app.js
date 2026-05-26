let selected = null;
let session = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

function drawMatrix(objects) {
  document.querySelector("#matrix").innerHTML = `<div class="matrix-grid">${objects.slice(0, 12).map((obj, index) => `
    <article class="cell">
      <b>${index % 3 === 0 ? "allow" : "review"}</b>
      <span>${esc(obj.class || obj.label || "object")}</span>
      <span>${esc(obj.id).slice(0, 16)}</span>
    </article>
  `).join("")}</div>`;
}

function show(obj) {
  selected = obj;
  document.querySelectorAll(".object").forEach((el) => el.classList.toggle("active", el.dataset.id === obj.id));
  document.querySelector("#out").textContent = JSON.stringify(obj, null, 2);
}

async function load() {
  const data = await fetch("/api/objects").then((r) => r.json());
  document.querySelector("#objects").innerHTML = data.objects.map((o, index) => `
    <article class="object" data-index="${index}" data-id="${esc(o.id)}">
      <strong>${esc(o.class || o.label || "record")}</strong>
      <span>${o.public ? "public lane" : "sealed lane"}</span>
      <code>${esc(o.id)}</code>
    </article>
  `).join("");
  document.querySelectorAll(".object").forEach((el) => {
    el.addEventListener("click", () => show(data.objects[Number(el.dataset.index)]));
  });
  drawMatrix(data.objects);
  if (data.objects[0]) show(data.objects[0]);
}

document.querySelector("#session").addEventListener("click", async () => {
  session = await fetch("/api/session/guest").then((r) => r.json());
  document.querySelector("#out").textContent = JSON.stringify(session, null, 2);
});

document.querySelector("#eval").addEventListener("click", async () => {
  if (!session) session = await fetch("/api/session/guest").then((r) => r.json());
  const expr = document.querySelector("#expr").value;
  const res = await fetch(`/api/policy/eval?session=${encodeURIComponent(session.session)}&expr=${encodeURIComponent(expr)}`).then((r) => r.json());
  document.querySelector("#out").textContent = JSON.stringify({ selected, result: res }, null, 2);
});

load();
