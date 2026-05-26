const pfMatrix = Array.from({ length: 24 }, (_, row) =>
  Array.from({ length: 8 }, (_, col) => (row * 41 + col * 11 + 9) % 107)
);

function pfFoldMatrix(seed) {
  let acc = seed >>> 0;
  for (const row of pfMatrix) {
    for (const value of row) {
      acc = (((acc << 7) | (acc >>> 25)) ^ value) >>> 0;
    }
  }
  return acc.toString(16).padStart(8, "0");
}

window.PolicyMatrix = { fold: pfFoldMatrix };
