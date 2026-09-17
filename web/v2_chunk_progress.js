/* Live chunk/frame status for the Zura renderer.  The server event is
 * deliberately separate from Comfy's sampler progress: one chunk can contain
 * many sampling steps, so displaying a fake percentage would be misleading. */
import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

// Class ID of Zura Wan 2.2 Looped Chunks Sampler; kept from before the Zura
// rename so graphs saved earlier keep resolving.
const NODE_TYPE = "TrendStudioV2Render";
let panel;
let latest;
let preparingTimer;

function formatElapsed(seconds) {
  const whole = Math.floor(Math.max(0, seconds));
  if (whole < 60) return `${whole}s`;
  return `${Math.floor(whole / 60)}m ${whole % 60}s`;
}

function cleanStage(value) {
  const stage = String(value || "").trim().replace(/\s+/g, " ");
  return stage ? stage.slice(0, 90) : "Preparing";
}

function elapsedSeconds(status, nowSeconds) {
  const started = Number(status?.stage_started_at);
  if (typeof nowSeconds === "number" && Number.isFinite(nowSeconds) && Number.isFinite(started)) {
    return Math.max(0, nowSeconds - started);
  }
  return 0;
}

function formatStatus(status, nowSeconds) {
  const preparing = status?.state === "preparing";
  const completed = preparing ? 0 : Number(status?.completed_frames || 0);
  const total = Number(status?.total_frames || 0);
  const chunk = Number(status?.chunk || 0);
  const chunks = Number(status?.chunks || 0);
  if (status?.state === "error") return `Wan 2.2 error: ${String(status.error || "render failed").slice(0, 90)}`;
  if (status?.state === "completed") return `Rendering complete · ${chunks}/${chunks} loops · ${completed}/${total} frames`;
  if (preparing) {
    const elapsed = formatElapsed(elapsedSeconds(status, nowSeconds));
    return `Wan 2.2 preparing · ${cleanStage(status.stage ?? status.phase)} · ${elapsed} · 0/${total} frames (0%)`;
  }
  const percent = total ? Math.floor(100 * completed / total) : 0;
  const shotStart = Number(status?.shot_start);
  const shotEnd = Number(status?.shot_end);
  const shotRange = Number.isFinite(shotStart) && Number.isFinite(shotEnd) && shotEnd > shotStart
    ? ` (frames ${shotStart}-${shotEnd - 1})` : '';
  return `Wan 2.2 ${status?.state === "started" ? "starting" : "rendering"} · shot ${Number(status?.shot || 0)}/${Number(status?.shots || 0)}${shotRange} · loop ${chunk}/${chunks} · ${completed}/${total} frames (${percent}%)`;
}

function nodesOf(graph) {
  return graph?._nodes || graph?.nodes || [];
}

function findById(graph, id, seen = new Set()) {
  if (!graph || seen.has(graph)) return null;
  seen.add(graph);
  for (const node of nodesOf(graph)) {
    if (String(node.id) === String(id)) return node;
    const found = findById(node.subgraph, id, seen);
    if (found) return found;
  }
  return null;
}

function renderStatus(data, nowSeconds) {
  if (panel) {
    panel.hidden = false;
    panel.textContent = formatStatus(data, nowSeconds);
    const percent = data.state === 'preparing'
      ? 0 : data.total_frames ? Math.floor(100 * data.completed_frames / data.total_frames) : 0;
    panel.style.background = data.state === 'error' ? '#7f1d1d' : `linear-gradient(90deg, #14532d ${percent}%, #164e63 ${percent}%)`;
  }
}

function stopPreparingTimer() {
  if (preparingTimer) clearInterval(preparingTimer);
  preparingTimer = null;
}

function startPreparingTimer() {
  if (preparingTimer) return;
  preparingTimer = setInterval(() => {
    if (!latest || latest.state !== 'preparing') {
      stopPreparingTimer();
      return;
    }
    const nowSeconds = Date.now() / 1000;
    renderStatus(latest, nowSeconds);
  }, 1000);
}

function update(event) {
  const data = event?.detail || event;
  if (!data || !data.node) return;
  const found = findById(app.graph, data.node);
  if (found) found.__zuraProgress = data;
  latest = data;
  renderStatus(data);
  if (data.state === 'preparing') startPreparingTimer();
  else stopPreparingTimer();
}

app.registerExtension({
  name: "Zura.ChunkProgress",
  setup() {
    panel = document.createElement('div');
    panel.hidden = true;
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    Object.assign(panel.style, {
      position: 'fixed', top: '104px', left: '80px', maxWidth: '650px',
      padding: '10px 14px', borderRadius: '6px', color: 'white', font: '14px sans-serif',
      pointerEvents: 'none', zIndex: '900', boxShadow: '0 2px 10px #0006',
    });
    document.body.append(panel);
    api.addEventListener("zura_progress", update);
    api.addEventListener('execution_start', () => {
      stopPreparingTimer();
      latest = null;
      panel.hidden = true;
    });
    for (const name of ['execution_error', 'execution_interrupted']) api.addEventListener(name, () => {
      if (latest && !['completed', 'error'].includes(latest.state)) update({ detail: { ...latest, state: 'error', error: name === 'execution_interrupted' ? 'Stopped by user' : 'Execution failed; see ComfyUI error report' } });
    });
  },
});
