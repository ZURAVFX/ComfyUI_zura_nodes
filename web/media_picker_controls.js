// Promoted subgraph widgets can differ from their inner node until compilation.
export function readControl(host, inner, name, fallback) {
  const visible = host?.widgets?.find(w => w.name === name);
  const stored = inner?.widgets?.find(w => w.name === name);
  return visible?.value ?? stored?.value ?? fallback;
}
