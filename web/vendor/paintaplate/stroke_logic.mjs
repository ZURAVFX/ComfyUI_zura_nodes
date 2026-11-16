// Extracted without algorithm changes from AInVFX Paint a plate web/logic.mjs. Apache-2.0.
export const dark = (hex) => [1, 3, 5].reduce((a, i, k) => a + [0.2126, 0.7152, 0.0722][k] * parseInt(hex.slice(i, i + 2), 16), 0) < 60;

export function dabsAlong(points, from, spacing, carry = 0) {
  const dabs = [];
  for (let i = from; i < points.length; i++) {
    const [x, y, r] = points[i];
    if (i === 0) { dabs.push([x, y, r]); carry = 0; continue; }
    const [px, py, pr] = points[i - 1], len = Math.hypot(x - px, y - py), s = Math.max(1, spacing((pr + r) / 2));
    let last = -1;
    for (let at = Math.max(0, s - carry); at <= len; at += s) {
      const f = len > 0 ? at / len : 1;
      dabs.push([px + (x - px) * f, py + (y - py) * f, pr + (r - pr) * f]);
      last = at;
    }
    carry = last < 0 ? carry + len : len - last;
  }
  return { dabs, carry };
}

// A soft dab: its alpha by distance over its radius, close to a Gaussian, as colour stops of a radial gradient
export const DAB_PROFILE = [[0, 1], [0.25, 0.85], [0.5, 0.5], [0.75, 0.18], [1, 0]];
export function dabAlpha(d) { // the profile between its stops
  if (d >= 1) return 0;
  const i = DAB_PROFILE.findIndex(([at]) => at > d), [a0, k0] = DAB_PROFILE[i - 1], [a1, k1] = DAB_PROFILE[i];
  return k0 + ((k1 - k0) * (d - a0)) / (a1 - a0);
}
// Each dab's alpha so the dabs of one straight stroke add up to `peak` on its centre line, at a spacing of
// `spacingOverRadius` of their radius
export function dabFlow(peak, spacingOverRadius) {
  let sum = 0;
  for (let k = -Math.ceil(1 / spacingOverRadius); k <= Math.ceil(1 / spacingOverRadius); k++) sum += dabAlpha(Math.abs(k * spacingOverRadius));
  return peak / sum;
}
