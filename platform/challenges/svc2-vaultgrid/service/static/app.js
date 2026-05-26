let objects = [];
let selected = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

function print(kind, text) {
  const node = document.createElement("div");
  node.className = `line ${kind}`;
  node.textContent = text;
  document.querySelector("#screen").appendChild(node);
  node.scrollIntoView({ block: "end" });
}

function selectObject(value) {
  const item = objects.find((o, index) => String(index + 1) === value || o.object === value);
  if (!item) {
    print("err", `not found: ${value}`);
    return;
  }
  selected = item;
  document.querySelector("#selected-name").textContent = item.object.slice(0, 10);
  document.querySelectorAll(".object").forEach((el) => el.classList.toggle("active", el.dataset.object === item.object));
  print("out", JSON.stringify(item, null, 2));
}

async function command(raw) {
  const [name, ...args] = raw.trim().split(/\s+/);
  if (!name) return;
  print("cmd", `vg$ ${raw}`);
  if (name === "help") {
    print("out", "commands: objects, select <n|id>, inspect, rebuild, ticket, shard <s0|s1|s2>, meta, clear");
  } else if (name === "objects") {
    print("out", objects.map((o, i) => `${i + 1}. ${o.object} payload=${o.payload}`).join("\n"));
  } else if (name === "select") {
    selectObject(args.join(" "));
  } else if (name === "inspect") {
    print("out", selected ? JSON.stringify(selected, null, 2) : "no object selected");
  } else if (name === "rebuild") {
    if (!selected) return print("err", "select an object first");
    const res = await fetch("/api/rebuild", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ object: selected.object }) }).then((r) => r.json());
    print("out", JSON.stringify(res, null, 2));
  } else if (name === "ticket") {
    if (!selected) return print("err", "select an object first");
    const res = await fetch(`/api/lease/${encodeURIComponent(selected.lease)}/ticket`).then((r) => r.json());
    print("out", JSON.stringify(res, null, 2));
  } else if (name === "shard") {
    if (!selected) return print("err", "select an object first");
    const shard = args[0] || "s0";
    const ticket = await fetch(`/api/lease/${encodeURIComponent(selected.lease)}/ticket`).then((r) => r.json());
    const res = await fetch(`/api/repair/${encodeURIComponent(selected.object)}/${encodeURIComponent(shard)}?ticket=${encodeURIComponent(ticket.ticket)}`).then((r) => r.json());
    print("out", JSON.stringify(res, null, 2));
  } else if (name === "meta") {
    if (!selected) return print("err", "select an object first");
    const res = await fetch(`/api/meta/${encodeURIComponent(selected.meta)}`).then((r) => r.json());
    print("out", JSON.stringify(res, null, 2));
  } else if (name === "clear") {
    document.querySelector("#screen").replaceChildren();
  } else {
    print("err", `unknown command: ${name}`);
  }
}

async function load() {
  const data = await fetch("/api/objects").then((r) => r.json());
  objects = data.objects;
  document.querySelector("#object-count").textContent = objects.length;
  document.querySelector("#objects").innerHTML = objects.map((o, index) => `
    <article class="object" data-index="${index}" data-object="${esc(o.object)}">
      <strong>${index + 1}. payload ${esc(o.payload)}</strong>
      <code>${esc(o.object)}</code>
    </article>
  `).join("");
  document.querySelectorAll(".object").forEach((el) => el.addEventListener("click", () => selectObject(String(Number(el.dataset.index) + 1))));
  print("out", "VaultGrid terminal ready. Type help.");
  if (objects[0]) selectObject("1");
}

document.querySelector("#cli").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#cmd");
  const raw = input.value;
  input.value = "";
  try {
    await command(raw);
  } catch (err) {
    print("err", String(err));
  }
});

load();
