export function nodesOf(graph) {
  return graph?._nodes || graph?.nodes || [];
}

function findByPath(graph, parts, index = 0, host = null) {
  if (!graph || index >= parts.length) return null;
  const node = nodesOf(graph).find(candidate => String(candidate.id) === parts[index]);
  if (!node) return null;
  const root = host || node;
  if (index === parts.length - 1) return {node, host: root};
  return findByPath(node.subgraph, parts, index + 1, root);
}

function findById(graph, id, host = null, seen = new Set()) {
  if (!graph || seen.has(graph)) return null;
  seen.add(graph);
  for (const node of nodesOf(graph)) {
    const root = host || node;
    if (String(node.id) === String(id)) return {node, host: root};
    const found = findById(node.subgraph, id, root, seen);
    if (found) return found;
  }
  return null;
}

export function findRenderer(graph, id) {
  const parts = String(id).split(":").filter(Boolean);
  return (parts.length > 1 && findByPath(graph, parts)) || findById(graph, parts[0] || id);
}

function cleanStage(value) {
  const stage = String(value || "").trim().replace(/\s+/g, " ");
  return stage ? stage.slice(0, 90) : "Preparing";
}

export function elapsedSeconds(status, nowSeconds) {
  const reported = typeof status?.elapsed_seconds === "number" && Number.isFinite(status.elapsed_seconds)
    ? Math.max(0, status.elapsed_seconds) : null;
  const started = Number(status?.stage_started_at);
  if (typeof nowSeconds === "number" && Number.isFinite(nowSeconds) && Number.isFinite(started)) {
    return Math.max(reported || 0, nowSeconds - started, 0);
  }
  return reported;
}

function formatElapsed(seconds) {
  const whole = Math.floor(Math.max(0, seconds));
  if (whole < 60) return `${whole}s`;
  return `${Math.floor(whole / 60)}m ${whole % 60}s`;
}

export function formatStatus(status, nowSeconds) {
  const preparing = status?.state === "preparing";
  const completed = preparing ? 0 : Number(status?.completed_frames || 0);
  const total = Number(status?.total_frames || 0);
  const chunk = Number(status?.chunk || 0);
  const chunks = Number(status?.chunks || 0);
  if (status?.state === "error") return `Wan 2.2 error: ${String(status.error || "render failed").slice(0, 90)}`;
  if (status?.state === "completed") return `Rendering complete · ${chunks}/${chunks} loops · ${completed}/${total} frames`;
  if (preparing) {
    const elapsed = elapsedSeconds(status, nowSeconds);
    const elapsedLabel = elapsed === null ? "" : ` · ${formatElapsed(elapsed)}`;
    return `Wan 2.2 preparing · ${cleanStage(status.stage ?? status.phase)}${elapsedLabel} · 0/${total} frames (0%)`;
  }
  const percent = total ? Math.floor(100 * completed / total) : 0;
  return `Wan 2.2 ${status?.state === "started" ? "starting" : "rendering"} · shot ${Number(status?.shot || 0)}/${Number(status?.shots || 0)} · loop ${chunk}/${chunks} · ${completed}/${total} frames (${percent}%)`;
}
