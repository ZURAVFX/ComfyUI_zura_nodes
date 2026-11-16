// AInVFX Paint a plate. Apache-2.0. See LICENSE and NOTICE.md.
// Canvas helpers of the page: making, scaling, encoding and measuring images. Browser only.

export const canvas = ([w, h]) => Object.assign(document.createElement("canvas"), { width: w, height: h });
export const blob = (c) => new Promise((r) => c.toBlob(r, "image/png"));
export const loadImage = (src) => new Promise((res, rej) => Object.assign(new Image(), { onload() { res(this); }, onerror: rej, src }));

export function snap(src, size, fill) { // `src` drawn at `size` over an optional fill colour
  const c = canvas(size), x = c.getContext("2d");
  if (fill) { x.fillStyle = fill; x.fillRect(0, 0, c.width, c.height); }
  if (src) x.drawImage(src, 0, 0, c.width, c.height);
  return c;
}

export function bounds(mask) { // painted area as FLUX 3 box coordinates: [y_min, x_min, y_max, x_max] on 0..1000
  const c = snap(mask, [256, Math.max(1, Math.round((256 * mask.height) / mask.width))]);
  const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
  let [x0, y0, x1, y1] = [c.width, c.height, -1, -1];
  for (let i = 3; i < d.length; i += 4) {
    if (d[i] < 16) continue;
    const p = (i - 3) / 4, x = p % c.width, y = (p / c.width) | 0;
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return x1 < 0 ? [0, 0, 1000, 1000] : [y0 / c.height, x0 / c.width, (y1 + 1) / c.height, (x1 + 1) / c.width].map((v) => Math.round(v * 1000));
}

export function whiteOf(img, tint) { // an image's alpha (where an edit put new pixels) as a white mask, or as a tint
  const c = snap(img, [img.width, img.height]), x = c.getContext("2d");
  const d = x.getImageData(0, 0, c.width, c.height);
  const [r, g, b] = tint ? [1, 3, 5].map((i) => parseInt(tint.slice(i, i + 2), 16)) : [255, 255, 255];
  for (let i = 0; i < d.data.length; i += 4) {
    const on = d.data[i + 3] > 127;
    [d.data[i], d.data[i + 1], d.data[i + 2]] = on ? [r, g, b] : [0, 0, 0];
    d.data[i + 3] = tint ? (on ? 255 : 0) : 255;
  }
  x.putImageData(d, 0, 0);
  return c;
}
