function nfRenderCells(target, rows) {
  const root = document.querySelector(target);
  if (!root) return;
  root.replaceChildren();
  for (const row of rows.slice(0, 18)) {
    const node = document.createElement("div");
    node.className = "nf-cell";
    node.textContent = `${row.id || "node"} ${row.zone || row.model || ""}`.trim();
    root.appendChild(node);
  }
}

function nfRenderBadge(target, value) {
  const root = document.querySelector(target);
  if (!root) return;
  root.textContent = String(value).slice(0, 48);
}

window.FleetRenderers = { cells: nfRenderCells, badge: nfRenderBadge };
