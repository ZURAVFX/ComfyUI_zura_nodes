import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const CLASS = "ZuraImageGuidance";
const LAYERS = {
  mask: ["Edit mask", "Paint the area you want ChatGPT to edit. White is the editable area."],
  markup: ["Markup", "Draw notes directly on the frame with a brush, arrow or box."],
  alpha: ["Markup alpha", "Hide or restore parts of the markup. The overlay starts with the transparency of your marks."],
};

function sourceFile(node) {
  const source = node.getInputNode?.(0);
  if (source?.comfyClass !== "LoadImage") return null;
  const value = source.widgets?.find((widget) => widget.name === "image")?.value;
  if (typeof value !== "string" || !value) return null;
  const pieces = value.replaceAll("\\", "/").split("/");
  return { filename: pieces.pop(), subfolder: pieces.join("/"), type: "input" };
}

async function captureFrame(node) {
  const { output, workflow } = await app.graphToPrompt();
  const id = String(node.id);
  if (output[id]?.class_type !== CLASS || !output[id].inputs.frame) {
    throw new Error("Connect a frame to the painter on the main canvas.");
  }
  // Submit just this node and its ancestors. Downstream API nodes stay out of the job.
  const prompt = {};
  const add = (key) => {
    if (prompt[key] || !output[key]) return;
    prompt[key] = output[key];
    for (const input of Object.values(output[key].inputs)) {
      if (Array.isArray(input) && input.length === 2 && typeof input[0] === "string") add(input[0]);
    }
  };
  add(id);
  prompt[id] = {
    ...output[id], inputs: { frame: output[id].inputs.frame, preview_only: true },
  };
  const job = await api.queuePrompt(0, { output: prompt, workflow });
  return job.prompt_id;
}

function paint(context, stroke, realWidth, width, height, layer) {
  const points = stroke.points.map(([x, y]) => [x * width, y * height]);
  const start = points[0];
  const end = points.at(-1);
  const size = Math.max(0.5, stroke.width * width / realWidth);
  context.save();
  context.lineWidth = size;
  context.lineCap = context.lineJoin = "round";
  context.strokeStyle = context.fillStyle = layer === "markup" ? stroke.colour : "#fff";
  if ((layer !== "alpha" && stroke.tool === "erase") || (layer === "alpha" && stroke.tool === "brush")) {
    context.globalCompositeOperation = "destination-out";
  }
  context.beginPath();
  if (stroke.tool === "box") {
    context.strokeRect(start[0], start[1], end[0] - start[0], end[1] - start[1]);
  } else if (stroke.tool === "arrow") {
    const angle = Math.atan2(end[1] - start[1], end[0] - start[0]);
    const head = Math.max(12 * width / realWidth, 3 * size);
    context.moveTo(...start);
    context.lineTo(...end);
    for (const direction of [angle - Math.PI / 6, angle + Math.PI / 6]) {
      context.moveTo(...end);
      context.lineTo(end[0] - head * Math.cos(direction), end[1] - head * Math.sin(direction));
    }
    context.stroke();
  } else if (points.length === 1) {
    context.arc(start[0], start[1], size / 2, 0, Math.PI * 2);
    context.fill();
  } else {
    context.moveTo(...start);
    for (const point of points.slice(1)) context.lineTo(...point);
    context.stroke();
  }
  context.restore();
}

function openEditor(node, drawing, captured) {
  const dialog = document.createElement("dialog");
  dialog.className = "zura-guidance";
  dialog.innerHTML = `
    <header>
      <div><h2>Image Guidance Painter</h2><p data-help></p></div>
      <button type="button" data-action="cancel" aria-label="Close painter">×</button>
    </header>
    <div class="zg-controls">
      <nav aria-label="Drawing layer">
        <button type="button" data-layer="mask">Edit mask</button>
        <button type="button" data-layer="markup">Markup</button>
        <button type="button" data-layer="alpha">Markup alpha</button>
      </nav>
      <div class="zg-tools" role="group" aria-label="Drawing tools">
        <button type="button" data-tool="brush">Brush</button>
        <button type="button" data-tool="erase">Eraser</button>
        <button type="button" data-tool="arrow">Arrow</button>
        <button type="button" data-tool="box">Box</button>
        <label class="zg-colour">Colour <input type="color" value="#ff7245"></label>
        <label class="zg-brush">Size <input type="range" min="1" max="160" value="24"><output>24 px</output></label>
      </div>
      <div class="zg-history" role="group" aria-label="History and zoom">
        <button type="button" data-action="undo" title="Ctrl+Z">Undo</button>
        <button type="button" data-action="redo" title="Ctrl+Shift+Z">Redo</button>
        <button type="button" data-action="clear">Clear layer</button>
        <button type="button" data-action="zoom" aria-pressed="false">100%</button>
      </div>
    </div>
    <div class="zg-viewport">
      <canvas hidden aria-label="Draw on the source frame"></canvas>
      <div class="zg-empty">
        <strong>Load a reference frame</strong>
        <p>Connect an image. A Load Image node is shown immediately. For other sources, fetch the connected frame.</p>
        <button type="button" data-action="capture">Fetch connected frame</button>
      </div>
    </div>
    <footer>
      <p data-status role="status"></p>
      <button type="button" data-action="refresh" hidden>Refresh frame</button>
      <button type="button" data-action="cancel">Cancel</button>
      <button type="button" class="zg-save" data-action="save">Use drawing</button>
    </footer>`;
  const query = (selector) => dialog.querySelector(selector);
  const actions = (name) => query(`[data-action="${name}"]`);
  const canvas = query("canvas");
  const viewport = query(".zg-viewport");
  const context = canvas.getContext("2d");
  const brush = query('input[type="range"]');
  const colour = query('input[type="color"]');
  const status = query("[data-status]");
  const buffers = Object.fromEntries(Object.keys(LAYERS).map((name) => [name, document.createElement("canvas")]));
  const composite = document.createElement("canvas");
  const transient = document.createElement("canvas");
  const records = { mask: [], markup: [], alpha: [] };
  const redo = { mask: [], markup: [], alpha: [] };
  let state;
  try { state = JSON.parse(drawing.value || "{}"); } catch { state = {}; }
  for (const name of Object.keys(LAYERS)) {
    if (state?.version === 1 && Array.isArray(state[name])) records[name] = state[name];
  }
  let layer = "mask";
  let tool = "brush";
  let preview;
  let pending;
  let pixels = false;
  let pointerId;
  let loadId = 0;
  let animation = 0;
  let captureJob;

  function fit() {
    if (!preview) return;
    const zoom = pixels ? 1 : Math.min(1, (viewport.clientWidth - 30) / preview.naturalWidth,
      (viewport.clientHeight - 30) / preview.naturalHeight);
    canvas.style.width = `${Math.max(1, Math.round(preview.naturalWidth * zoom))}px`;
    canvas.style.height = `${Math.max(1, Math.round(preview.naturalHeight * zoom))}px`;
  }

  function renderLayer(name) {
    const buffer = buffers[name];
    const draw = buffer.getContext("2d");
    draw.clearRect(0, 0, buffer.width, buffer.height);
    if (name === "alpha") {
      draw.fillStyle = "#fff";
      draw.fillRect(0, 0, buffer.width, buffer.height);
    }
    for (const stroke of records[name]) paint(draw, stroke, preview.naturalWidth, buffer.width, buffer.height, name);
  }

  function drawScene() {
    if (!preview) return;
    const { width, height } = canvas;
    context.clearRect(0, 0, width, height);
    context.drawImage(preview, 0, 0, width, height);
    let layerImage = buffers[layer];
    if (pending) {
      const draw = transient.getContext("2d");
      draw.clearRect(0, 0, width, height);
      draw.drawImage(layerImage, 0, 0);
      paint(draw, pending, preview.naturalWidth, width, height, layer);
      layerImage = transient;
    }
    if (layer === "mask") {
      const draw = composite.getContext("2d");
      draw.clearRect(0, 0, width, height);
      draw.drawImage(layerImage, 0, 0);
      draw.globalCompositeOperation = "source-in";
      draw.fillStyle = "rgba(64,230,179,.46)";
      draw.fillRect(0, 0, width, height);
      draw.globalCompositeOperation = "source-over";
    } else {
      const draw = composite.getContext("2d");
      draw.clearRect(0, 0, width, height);
      draw.drawImage(layer === "markup" ? layerImage : buffers.markup, 0, 0);
      draw.globalCompositeOperation = "destination-in";
      draw.drawImage(layer === "alpha" ? layerImage : buffers.alpha, 0, 0);
      draw.globalCompositeOperation = "source-over";
    }
    context.drawImage(composite, 0, 0);
  }

  function scheduleDraw() {
    if (animation) return;
    animation = requestAnimationFrame(() => {
      animation = 0;
      drawScene();
    });
  }

  function sync() {
    query("[data-help]").textContent = LAYERS[layer][1];
    for (const button of dialog.querySelectorAll("[data-layer]")) {
      button.setAttribute("aria-pressed", String(button.dataset.layer === layer));
    }
    for (const button of dialog.querySelectorAll("[data-tool]")) {
      button.hidden = ["arrow", "box"].includes(button.dataset.tool) && layer !== "markup";
      button.setAttribute("aria-pressed", String(button.dataset.tool === tool));
      if (button.dataset.tool === "brush") button.textContent = layer === "alpha" ? "Hide" : "Brush";
      if (button.dataset.tool === "erase") button.textContent = layer === "alpha" ? "Restore" : "Eraser";
    }
    query(".zg-colour").hidden = layer !== "markup";
    query("output").value = `${brush.value} px`;
    actions("undo").disabled = !preview || !records[layer].length;
    actions("redo").disabled = !preview || !redo[layer].length;
    actions("clear").disabled = actions("undo").disabled;
    actions("zoom").disabled = actions("save").disabled = !preview;
    actions("refresh").hidden = !preview || Boolean(sourceFile(node));
    scheduleDraw();
  }

  async function load(file) {
    if (!file) return;
    const token = ++loadId;
    const image = new Image();
    image.src = api.apiURL("/view?" + new URLSearchParams(file));
    try {
      await image.decode();
    } catch {
      if (token === loadId) status.textContent = "Could not open that frame. Fetch the connected frame again.";
      return;
    }
    if (token !== loadId || !dialog.open) return;
    preview = image;
    canvas.hidden = true;
    const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
    for (const surface of [canvas, composite, transient, ...Object.values(buffers)]) {
      surface.width = Math.max(1, Math.round(image.naturalWidth * scale));
      surface.height = Math.max(1, Math.round(image.naturalHeight * scale));
    }
    for (const name of Object.keys(LAYERS)) renderLayer(name);
    canvas.hidden = false;
    query(".zg-empty").hidden = true;
    status.textContent = state?.width && (state.width !== image.naturalWidth || state.height !== image.naturalHeight)
      ? "Review the drawing against the new frame size before saving."
      : `${image.naturalWidth} × ${image.naturalHeight}`;
    fit();
    sync();
  }

  const resize = new ResizeObserver(fit);
  const onFailure = ({ detail }) => {
    if (detail?.prompt_id !== captureJob) return;
    status.textContent = "The connected frame could not be rendered. Check the upstream node.";
    actions("capture").disabled = actions("refresh").disabled = false;
    captureJob = undefined;
  };
  api.addEventListener("execution_error", onFailure);
  api.addEventListener("execution_interrupted", onFailure);
  dialog.addEventListener("close", () => {
    cancelAnimationFrame(animation);
    resize.disconnect();
    api.removeEventListener("execution_error", onFailure);
    api.removeEventListener("execution_interrupted", onFailure);
    dialog.remove();
  });
  for (const button of dialog.querySelectorAll("[data-layer]")) {
    button.onclick = () => {
      layer = button.dataset.layer;
      tool = "brush";
      sync();
    };
  }
  for (const button of dialog.querySelectorAll("[data-tool]")) {
    button.onclick = () => {
      tool = button.dataset.tool;
      sync();
    };
  }
  brush.oninput = sync;
  function point(event) {
    const rect = canvas.getBoundingClientRect();
    const clamp = (value) => Math.round(Math.min(1, Math.max(0, value)) * 100000) / 100000;
    return [clamp((event.clientX - rect.left) / rect.width), clamp((event.clientY - rect.top) / rect.height)];
  }
  canvas.onpointerdown = (event) => {
    if (event.button !== 0 || !preview || pending) return;
    if (records[layer].length >= 1024) {
      status.textContent = "This layer is full. Undo or clear a stroke before drawing.";
      return;
    }
    pointerId = event.pointerId;
    canvas.setPointerCapture(pointerId);
    pending = { tool, width: Number(brush.value), colour: colour.value, points: [point(event)] };
    scheduleDraw();
  };
  canvas.onpointermove = (event) => {
    if (!pending || event.pointerId !== pointerId) return;
    const position = point(event);
    if (pending.tool === "arrow" || pending.tool === "box") {
      pending.points[1] = position;
    } else if (pending.points.length < 4096) {
      const [x, y] = pending.points.at(-1);
      if (Math.hypot((x - position[0]) * canvas.width, (y - position[1]) * canvas.height) > 0.7) {
        pending.points.push(position);
      }
    }
    scheduleDraw();
  };
  canvas.onpointerup = (event) => {
    if (!pending || event.pointerId !== pointerId) return;
    canvas.onpointermove(event);
    records[layer].push(pending);
    redo[layer] = [];
    pending = null;
    renderLayer(layer);
    sync();
  };
  canvas.onpointercancel = () => {
    pending = null;
    sync();
  };

  actions("undo").onclick = () => {
    if (!records[layer].length) return;
    redo[layer].push([records[layer].pop()]);
    renderLayer(layer);
    sync();
  };
  actions("redo").onclick = () => {
    if (!redo[layer].length) return;
    records[layer].push(...redo[layer].pop());
    renderLayer(layer);
    sync();
  };
  actions("clear").onclick = () => {
    redo[layer].push(records[layer]);
    records[layer] = [];
    renderLayer(layer);
    sync();
  };
  actions("zoom").onclick = () => {
    pixels = !pixels;
    actions("zoom").textContent = pixels ? "Fit frame" : "100%";
    actions("zoom").setAttribute("aria-pressed", String(pixels));
    fit();
  };
  dialog.onkeydown = (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      actions(event.shiftKey ? "redo" : "undo").click();
    }
  };
  async function fetchFrame() {
    actions("capture").disabled = actions("refresh").disabled = true;
    status.textContent = "Fetching the connected frame…";
    try {
      captureJob = await captureFrame(node);
    } catch (error) {
      status.textContent = error.message || "Could not fetch the connected frame.";
      actions("capture").disabled = actions("refresh").disabled = false;
    }
  }
  actions("capture").onclick = actions("refresh").onclick = fetchFrame;
  for (const button of dialog.querySelectorAll('[data-action="cancel"]')) {
    button.onclick = () => dialog.close();
  }
  actions("save").onclick = () => {
    const data = JSON.stringify({ version: 1, width: preview.naturalWidth, height: preview.naturalHeight, ...records });
    if (data.length > 2_000_000) {
      status.textContent = "The drawing is too large. Clear or undo some strokes.";
      return;
    }
    node.graph?.beforeChange();
    drawing.value = data;
    drawing.callback?.(data);
    node.graph?.afterChange();
    node.setDirtyCanvas(true, true);
    dialog.close();
  };
  document.body.append(dialog);
  dialog.showModal();
  resize.observe(viewport);
  sync();
  void load(sourceFile(node) || captured);
  return {
    dialog,
    updateFrame(file) {
      captureJob = undefined;
      actions("capture").disabled = actions("refresh").disabled = false;
      void load(file);
    },
  };
}

app.registerExtension({
  name: "Zura.ImageGuidancePainter",
  beforeRegisterNodeDef(nodeType, data) {
    if (data.name !== CLASS) return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = created?.apply(this, args);
      const drawing = this.widgets.find((widget) => widget.name === "drawing");
      let editor;
      let captured;
      this.addWidget("button", "Draw guidance…", null, () => {
        if (editor?.dialog.open) return;
        if (!document.querySelector("link[data-zura-guidance-style]")) {
          const sheet = document.createElement("link");
          sheet.rel = "stylesheet";
          sheet.href = new URL("./image_guidance.css", import.meta.url);
          sheet.dataset.zuraGuidanceStyle = "";
          document.head.append(sheet);
        }
        editor = openEditor(this, drawing, captured);
      }, { serialize: false });
      const previous = this.onExecuted;
      this.onExecuted = function (message) {
        previous?.call(this, message);
        const frame = message?.zura_guidance_frame?.[0];
        if (frame) {
          captured = frame;
          if (editor?.dialog.open) editor.updateFrame(frame);
        }
      };
      const connections = this.onConnectionsChange;
      this.onConnectionsChange = function (...values) {
        if (values[0] === 1 && values[1] === 0) captured = undefined;
        return connections?.apply(this, values);
      };
      const removed = this.onRemoved;
      this.onRemoved = function (...values) {
        if (editor?.dialog.open) editor.dialog.close();
        return removed?.apply(this, values);
      };
      for (const widget of this.widgets.filter((item) => ["drawing", "preview_only"].includes(item.name))) {
        widget.hidden = true;
        widget.computeSize = () => [0, -4];
        widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
      }
      this.setSize([Math.max(310, this.size[0]), this.computeSize()[1]]);
      return result;
    };
  },
});
