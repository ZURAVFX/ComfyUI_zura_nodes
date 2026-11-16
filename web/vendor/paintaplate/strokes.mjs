// AInVFX Paint a plate stroke renderer, Apache-2.0.
// Adaptation: extracted from app.mjs into an ES module; drawStroke is exported.
// The pressure, line, erase and light-dab algorithms are unchanged.
import {canvas} from './canvas.mjs';
import {dabsAlong,dabFlow,DAB_PROFILE,dark} from './stroke_logic.mjs';
const LIGHT = { flow: 0.3, shade: 0.35, spread: 1.6, spacing: 0.25 };
export function drawStroke(d, s, from = 0) {
  const pc = d.paint.getContext("2d"), mc = d.mask.getContext("2d");
  if (s.tool === "rub") { // the eraser takes strokes away, whatever drew them: paint, light or shade
    const cs = [pc, mc, d.shade?.getContext("2d")].filter(Boolean);
    for (const c of cs) c.globalCompositeOperation = "destination-out";
    for (let i = from; i < s.points.length; i++) {
      const [x, y, p] = s.points[i], [px, py] = s.points[Math.max(i - 1, 0)], r = (s.size * (0.5 + p)) / 2;
      for (const c of cs) line(c, px, py, x, y, r, "#fff");
    }
    for (const c of cs) c.globalCompositeOperation = "source-over";
    return;
  }
  for (let i = from; i < s.points.length; i++) {
    const [x, y, p] = s.points[i], [px, py] = s.points[Math.max(i - 1, 0)], r = (s.size * (0.5 + p)) / 2;
    line(mc, px, py, x, y, r, "#fff");
    if (s.tool === "paint") line(pc, px, py, x, y, r, s.color);
  }
  if (s.tool === "light") lightDabs(d, s, from);
}

// The light brush: soft dabs at a fixed spacing along the stroke (logic.dabsAlong), so the light never depends on how fast
// the hand moved. Light adds up ("lighter") at a flow that gives one stroke at most LIGHT.flow of its colour; a dark colour
// lays shade on its own layer (d.shade) the same way. The eraser takes both away.
const carried = new WeakMap(); // stroke -> the distance walked since its last dab, between two pointer moves
function lightDabs(d, s, from) {
  const shade = dark(s.color), layer = shade ? (d.shade ??= canvas([d.paint.width, d.paint.height])) : d.paint;
  const pts = s.points.map(([x, y, p]) => [x, y, ((s.size * (0.5 + p)) / 2) * LIGHT.spread]);
  const { dabs, carry } = dabsAlong(pts, from, (r) => r * LIGHT.spacing, from ? carried.get(s) ?? 0 : 0);
  carried.set(s, carry);
  const c = layer.getContext("2d"), flow = dabFlow(shade ? LIGHT.shade : LIGHT.flow, LIGHT.spacing), rgb = shade ? "0, 0, 0" : rgbOf(s.color);
  c.globalCompositeOperation = shade ? "source-over" : "lighter";
  for (const [x, y, r] of dabs) {
    const g = c.createRadialGradient(x, y, 0, x, y, r);
    for (const [at, k] of DAB_PROFILE) g.addColorStop(at, `rgba(${rgb}, ${(flow * k).toFixed(4)})`);
    c.fillStyle = g; c.fillRect(x - r, y - r, 2 * r, 2 * r);
  }
  c.globalCompositeOperation = "source-over";
}

const rgbOf = (hex) => { // "#rgb" or "#rrggbb" as "r, g, b"
  const h = hex.replace("#", ""), f = h.length === 3 ? h.replace(/./g, "$&$&") : h.slice(0, 6);
  return [0, 2, 4].map((i) => parseInt(f.slice(i, i + 2), 16) || 0).join(", ");
};

function line(c, x0, y0, x1, y1, r, color) {
  Object.assign(c, { strokeStyle: color, lineWidth: 2 * r, lineCap: "round", lineJoin: "round" });
  c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
}
