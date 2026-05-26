let selected = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

function position(index, total) {
  const angle = (Math.PI * 2 * index) / Math.max(total, 1) - Math.PI / 2;
  const x = 44 + Math.cos(angle) * 32;
  const y = 46 + Math.sin(angle) * 30;
  return `left:${Math.max(4, Math.min(78, x))}%;top:${Math.max(6, Math.min(78, y))}%;`;
}

function show(node) {
  selected = node;
  document.querySelectorAll(".node").forEach((el) => el.classList.toggle("active", el.dataset.id === node.id));
  document.querySelector("#out").textContent = JSON.stringify(node, null, 2);
}

async function load() {
  const data = await fetch("/api/nodes").then((r) => r.json());
  document.querySelector("#nodes").innerHTML = data.nodes.map((n, index) => `
    <article class="node" data-index="${index}" data-id="${esc(n.id)}" style="${position(index, data.nodes.length)}">
      <strong>${esc(n.kind)}</strong>
      <b>payload ${esc(n.payload)}</b>
      <code>${esc(n.id)}</code>
    </article>
  `).join("");
  document.querySelectorAll(".node").forEach((el) => {
    el.addEventListener("click", () => show(data.nodes[Number(el.dataset.index)]));
  });
  if (data.nodes[0]) show(data.nodes[0]);
}

document.querySelector("#token").addEventListener("click", async () => {
  const token = await fetch("/api/routes/diag-token").then((r) => r.json());
  document.querySelector("#out").textContent = JSON.stringify(token, null, 2);
});

document.querySelector("#tlv").addEventListener("click", async () => {
  if (!selected) return;
  const res = await fetch(`/api/tlv/decode?node=${encodeURIComponent(selected.id)}&length=8`).then((r) => r.json());
  document.querySelector("#out").textContent = JSON.stringify(res, null, 2);
});

document.querySelector("#firmware").addEventListener("click", async () => {
  if (!selected) return;
  const res = await fetch(`/api/firmware/blob/${encodeURIComponent(selected.blob)}?manifest=public`).then((r) => r.json());
  document.querySelector("#out").textContent = JSON.stringify(res, null, 2);
});

document.querySelector("#cli").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#cmd");
  const [name, ...args] = input.value.trim().split(/\s+/);
  input.value = "";
  if (name === "help") {
    document.querySelector("#out").textContent = "commands: nodes, select <n>, token, tlv, firmware, route";
  } else if (name === "nodes") {
    const data = await fetch("/api/nodes").then((r) => r.json());
    document.querySelector("#out").textContent = data.nodes.map((n, i) => `${i + 1}. ${n.id} ${n.kind} payload=${n.payload}`).join("\n");
  } else if (name === "select") {
    const data = await fetch("/api/nodes").then((r) => r.json());
    const node = data.nodes[Number(args[0] || 1) - 1];
    if (node) show(node);
  } else if (name === "token") {
    document.querySelector("#token").click();
  } else if (name === "tlv") {
    document.querySelector("#tlv").click();
  } else if (name === "firmware") {
    document.querySelector("#firmware").click();
  } else if (name === "route") {
    if (!selected) return;
    const token = await fetch("/api/routes/diag-token").then((r) => r.json());
    const res = await fetch(`/api/route/diag;read:${encodeURIComponent(selected.id)}?token=${encodeURIComponent(token.token)}`).then((r) => r.json());
    document.querySelector("#out").textContent = JSON.stringify(res, null, 2);
  } else if (name) {
    document.querySelector("#out").textContent = `unknown command: ${name}`;
  }
});

load();
