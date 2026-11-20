import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const ROUTE = "/zura/openai_image/key";
const BILLING_URL = "https://platform.openai.com/settings/organization/billing/overview";
const PRICE_GUIDE = "https://developers.openai.com/api/docs/guides/image-generation#calculating-costs";
const STILL_COSTS = {
  standard: { low: [0.009, 0.013], medium: [0.034, 0.05], high: [0.133, 0.2] },
  mini: { low: [0.005, 0.006], medium: [0.011, 0.015], high: [0.036, 0.052] },
};
const GRID_SIZE = {
  "2": { low: 16, medium: 48, high: 96 },
  "2.5": { low: 16, medium: 24, high: 48, xhigh: 64, max: 96 },
  "2.6": { low: 16, medium: 24, high: 48, xhigh: 64, max: 96 },
};
const BILLABLE_SCALE_26 = { low: 4.2, medium: 3.3, high: 1, xhigh: 1, max: 1 };
let keySource = "none";
let projectModels = [];
let modelRequest;
const mountedNodes = new Set();
let keyDialog;

function estimateOutput({ model, size, quality, count, partials, format }) {
  if (format === "gif" || !Number.isInteger(count) || count < 1) return null;
  const [width, height] = size.split("x").map(Number);
  const short = Math.min(width, height);
  const long = Math.max(width, height);
  const pixels = width * height;
  if (!short || width % 16 || height % 16 || long > 3840 || long > 3 * short ||
      pixels < 655360 || pixels > 8294400) return null;
  const modern = /^(gpt-image-2\.(5|6)-(sunburst|flare)|gpt-image-2)(-\d{4}-\d{2}-\d{2})?$/.exec(model);
  const mini = model === "gpt-image-1-mini";
  const legacy = mini || model === "chatgpt-image-latest" || /^gpt-image-1\.5(-\d{4}-\d{2}-\d{2})?$/.test(model);
  if (modern) {
    const version = modern[2] ? `2.${modern[2]}` : "2";
    const grid = GRID_SIZE[version];
    const levels = quality === "auto" ? Object.keys(grid) : [quality];
    if (!grid[levels[0]]) return null;
    // OpenAI's calculator rounds the short grid edge to the nearest even
    // integer on ties, then scales the grid area by the pixel budget.
    const estimates = levels.map((level) => {
      const longGrid = grid[level];
      const exactShort = longGrid * short / long;
      const floor = Math.floor(exactShort);
      const shortGrid = exactShort - floor === 0.5 ? floor + floor % 2 : Math.round(exactShort);
      const tokens = Math.ceil(longGrid * shortGrid * (2_000_000 + pixels) / 4_000_000);
      const billable = version === "2.6" ? Math.round(tokens * BILLABLE_SCALE_26[level]) : tokens;
      return (billable + 100 * partials) * count * 30 / 1_000_000;
    });
    return [Math.min(...estimates), Math.max(...estimates)];
  }
  if (!legacy || !["1024x1024", "1536x1024", "1024x1536"].includes(size)) return null;
  const table = mini ? STILL_COSTS.mini : STILL_COSTS.standard;
  const levels = quality === "auto" ? Object.keys(table) : [quality];
  if (!Object.hasOwn(table, levels[0])) return null;
  const costs = levels.map((level) => count * (table[level][width === height ? 0 : 1] + 100 * partials * (mini ? 8 : 32) / 1_000_000));
  return [Math.min(...costs), Math.max(...costs)];
}

function refreshModels(force) {
  if (force) modelRequest = undefined;
  if (modelRequest) return;
  if (keySource === "none") {
    projectModels = [];
    for (const entry of mountedNodes) entry.updateModels();
    return;
  }
  const request = api.fetchApi("/zura/openai_image/models", { cache: "no-store" });
  modelRequest = request;
  void request.then((response) => response.ok ? response.json() : {})
    .then(({ models }) => {
      if (request !== modelRequest) return;
      projectModels = Array.isArray(models) ? models : [];
      for (const entry of mountedNodes) entry.updateModels();
    }).catch(() => {
      if (request === modelRequest) modelRequest = undefined;
    });
}

async function keyRequest(method = "GET", key) {
  const response = await api.fetchApi(ROUTE, {
    method,
    cache: "no-store",
    ...(key ? {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    } : {}),
  });
  if (!response.ok) throw new Error(await response.text());
  const source = (await response.json()).source;
  const changed = source !== keySource;
  keySource = source;
  for (const { node, widget } of mountedNodes) {
    widget.name = keySource === "none" ? "OpenAI API key…" : "OpenAI API key set…";
    node.setDirtyCanvas(true, true);
  }
  refreshModels(changed || method !== "GET");
}

function openKeyDialog() {
  if (keyDialog) return;
  const dialog = document.createElement("dialog");
  dialog.className = "zura-openai-key-dialog";
  dialog.innerHTML = `
    <style>
      .zura-openai-key-dialog {
        width: min(440px, calc(100% - 32px));
        padding: 24px;
        border: 1px solid var(--border-color, #4e4e4e);
        border-radius: 12px;
        background: var(--comfy-menu-bg, #282828);
        color: var(--fg-color, #eee);
      }
      .zura-openai-key-dialog::backdrop { background: rgb(0 0 0 / 55%); }
      .zura-openai-key-dialog h3 { margin: 0 0 12px; }
      .zura-openai-key-dialog input { display: block; width: 100%; margin-top: 6px; }
      .zura-openai-key-dialog [role="status"]:empty { display: none; }
      .zura-openai-key-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
    </style>
    <form>
      <h3>OpenAI API key</h3>
      <p>The key stays in this ComfyUI session until you clear it or restart.</p>
      <label>API key <input type="password" autocomplete="off" spellcheck="false" required></label>
      <p role="status"></p>
      <div class="zura-openai-key-actions">
        <button type="button" data-cancel>Cancel</button>
        <button type="button" data-clear>Clear session key</button>
        <button type="submit">Use key</button>
      </div>
    </form>`;
  const input = dialog.querySelector("input");
  const status = dialog.querySelector("[role=status]");
  const clear = dialog.querySelector("[data-clear]");
  const submit = dialog.querySelector("[type=submit]");
  clear.hidden = keySource !== "session";
  if (keySource === "environment") status.textContent = "Using the server’s OPENAI_API_KEY.";

  async function update(method) {
    submit.disabled = clear.disabled = true;
    status.textContent = "";
    try {
      await keyRequest(method, method === "POST" ? input.value.trim() : undefined);
      dialog.close();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      input.value = "";
      submit.disabled = clear.disabled = false;
    }
  }
  dialog.querySelector("form").addEventListener("submit", (event) => {
    event.preventDefault();
    void update("POST");
  });
  dialog.querySelector("[data-cancel]").addEventListener("click", () => dialog.close());
  clear.addEventListener("click", () => void update("DELETE"));
  dialog.addEventListener("close", () => {
    input.value = "";
    dialog.remove();
    keyDialog = undefined;
  });
  document.body.append(dialog);
  keyDialog = dialog;
  dialog.showModal();
}

const EXTRA_REFERENCE_NAMES = Array.from({ length: 14 }, (_, index) => `reference_${index + 3}`);

function mount(node) {
  if (!node.widgets) return;
  const inputs = new Map(node.widgets.map((widget) => [widget.name, {
    widget, hidden: widget.hidden, size: widget.computeSize, layout: widget.computeLayoutSize,
    display: widget.element?.style.display,
  }]));
  const model = inputs.get("model").widget;
  const builtInModels = [...model.options.values];
  const key = node.addWidget("button", "OpenAI API key…", null, openKeyDialog, { serialize: false });
  const entry = { node, widget: key, updateModels };
  mountedNodes.add(entry);
  updateModels();
  void keyRequest().catch(() => {});

  const addReference = node.addWidget("button", "Add reference", null, () => {
    const name = nextReference();
    if (!name) return;
    const number = name.split("_")[1];
    node.addInput(name, "IMAGE", { localized_name: `Reference ${number}` });
    refresh();
  }, { serialize: false });
  const billing = node.addWidget("button", "API balance ↗", null, () => {
    window.open(BILLING_URL, "_blank", "noopener,noreferrer");
  }, { serialize: false });
  const vueNodes = app.extensionManager?.setting?.get?.("Comfy.VueNodes.Enabled")
    ?? app.ui?.settings?.getSettingValue?.("Comfy.VueNodes.Enabled", false);
  let advanced = false;
  // Classic canvas nodes ignore the native advanced metadata used by Vue Nodes.
  if (!vueNodes) {
    const disclosure = node.addWidget("button", "Show advanced settings", null, () => {
      advanced = !advanced;
      disclosure.name = advanced ? "Hide advanced settings" : "Show advanced settings";
      refresh();
    }, { serialize: false });
  }
  const value = (name) => inputs.get(name)?.widget.value;
  const isLinked = (name, widget) => widget.type === "converted-widget" ||
    node.inputs?.some((input) => input.name === name && input.link != null);
  const nextReference = () => EXTRA_REFERENCE_NAMES.find((name) => !node.inputs?.some((slot) => slot.name === name));

  function updateModels() {
    if (model.value === "Custom ID") {
      model.value = inputs.get("custom_model")?.widget.value?.trim() || builtInModels[0];
    }
    model.options.values = [...new Set([...builtInModels, ...projectModels, model.value].filter(Boolean))];
    node.setDirtyCanvas(true, true);
  }

  function updateCost() {
    const size = value("size");
    const format = value("output_format");
    const stream = value("stream");
    const pricedInputs = ["model", "size", "quality", "n", "output_format"];
    if (size === "Custom") pricedInputs.push("output_width", "output_height");
    if (format !== "svg" && format !== "gif") {
      pricedInputs.push("stream");
      if (stream) pricedInputs.push("partial_images");
    }
    const linked = pricedInputs.some((name) => {
      const widget = inputs.get(name)?.widget;
      return widget && isLinked(name, widget);
    });
    const range = linked ? null : estimateOutput({
      model: model.value,
      size: size === "auto" ? "1024x1024" : size === "Custom" ? `${value("output_width")}x${value("output_height")}` : size,
      quality: value("quality"),
      count: value("n"),
      partials: stream && format !== "svg" ? value("partial_images") : 0,
      format,
    });
    const money = (usd) => `$${usd.toFixed(usd < 0.01 ? 3 : 2)}`;
    const detail = range && (range[0] === range[1] ? money(range[0]) : `${money(range[0])}–${money(range[1])}`);
    const label = size === "auto" ? "1K example" : format === "svg" ? "SVG render" : "Est. output";
    billing.name = detail ? `${label} ${detail} · Balance ↗` : "API balance ↗";
    billing.tooltip = [
      range ? "Estimated image output in USD for this node run. Prompt, reference image and SVG authoring charges are extra." :
        linked ? "The estimate depends on values from connected nodes." : "Output estimate unavailable for these settings.",
      "Open the OpenAI billing dashboard to see your current balance.",
      PRICE_GUIDE,
    ].join("\n");
  }

  function refresh() {
    const format = value("output_format");
    updateModels();
    updateCost();
    addReference.name = nextReference() ? "Add reference" : "16 reference slots";
    for (const [name, original] of inputs) {
      const { widget } = original;
      if (isLinked(name, widget)) continue;
      let visible = name !== "custom_model";
      if (name === "output_width" || name === "output_height") visible = value("size") === "Custom";
      if (name === "output_compression") visible = ["jpeg", "webp"].includes(format);
      if (name === "svg_model" || name === "svg_reasoning") visible = format === "svg";
      if (name === "frame_count" || name === "frame_duration_ms") visible = format === "gif";
      if (name === "stream") visible = !["gif", "svg"].includes(format);
      if (name === "partial_images") visible = value("stream") && !["gif", "svg"].includes(format);
      if (!vueNodes && widget.options?.advanced && !advanced) visible = false;
      widget.hidden = visible ? original.hidden : true;
      widget.computeSize = visible ? original.size : () => [0, -4];
      widget.computeLayoutSize = visible ? original.layout : () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
      if (widget.element) widget.element.style.display = visible ? original.display ?? "" : "none";
    }
    const [width] = node.size;
    node.setSize([Math.max(340, width), node.computeSize()[1]]);
    node.setDirtyCanvas(true, true);
  }

  for (const name of ["model", "size", "output_format", "stream", "quality", "n",
    "output_width", "output_height", "partial_images"]) {
    const widget = inputs.get(name)?.widget;
    if (!widget) continue;
    const callback = widget.callback;
    widget.callback = function (...args) {
      const result = callback?.apply(this, args);
      refresh();
      return result;
    };
  }
  const connections = node.onConnectionsChange;
  node.onConnectionsChange = function (...args) {
    const result = connections?.apply(this, args);
    queueMicrotask(updateCost);
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function (...args) {
    const result = configure?.apply(this, args);
    queueMicrotask(refresh);
    return result;
  };
  const removed = node.onRemoved;
  node.onRemoved = function (...args) {
    mountedNodes.delete(entry);
    return removed?.apply(this, args);
  };
  refresh();
}

app.registerExtension({
  name: "Zura.OpenAIImage",
  beforeRegisterNodeDef(nodeType, data) {
    if (data.name !== "ZuraOpenAIImage") return;
    // The server accepts all sixteen. On the canvas, append extra sockets on
    // demand so published workflows retain both their names and link indices.
    if (data.input?.optional) {
      for (const name of EXTRA_REFERENCE_NAMES) delete data.input.optional[name];
    }
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = created?.apply(this, args);
      mount(this);
      return result;
    };
  },
});
