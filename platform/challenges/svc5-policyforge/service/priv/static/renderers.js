function pfRenderCells(target, rows) {
  const root = document.querySelector(target);
  if (!root) return;
  root.replaceChildren();
  for (const row of rows.slice(0, 18)) {
    const node = document.createElement("div");
    node.className = "pf-cell";
    node.textContent = `${row.id || "object"} ${row.tenant || row.label || ""}`.trim();
    root.appendChild(node);
  }
}

function pfRenderBadge(target, value) {
  const root = document.querySelector(target);
  if (!root) return;
  root.textContent = String(value).slice(0, 48);
}

window.PolicyRenderers = { cells: pfRenderCells, badge: pfRenderBadge };
