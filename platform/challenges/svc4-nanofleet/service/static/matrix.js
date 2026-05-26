const nfMatrix = Array.from({ length: 24 }, (_, row) =>
  Array.from({ length: 8 }, (_, col) => (row * 37 + col * 17 + 3) % 109)
);

function nfFoldMatrix(seed) {
  let acc = seed >>> 0;
  for (const row of nfMatrix) {
    for (const value of row) {
      acc = ((acc * 33) ^ value) >>> 0;
    }
  }
  return acc.toString(16).padStart(8, "0");
}

window.FleetMatrix = { fold: nfFoldMatrix };
