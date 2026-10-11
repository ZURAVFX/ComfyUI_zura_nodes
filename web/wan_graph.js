// Explicit Graph view planning. This module never queues or executes nodes.
import { expandStageSignals, promptFingerprint } from "./artist_graph.js";

const STATE_KEY = "zuraWanGraph";
const SCHEMA = "zura_wan_graph_ui_v1";
const STAGES = new Set(["wan_prepare", "wan_merge", "wan"]);
const MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024;
const controllers = new WeakMap();
const loading = new WeakSet();
const BOOKKEEPING = {
  ZuraWanPreparationWindow: new Set(["start_frame", "frame_count"]),
  ZuraWanCarryPoseWindow: new Set(["cache_key"]),
  ZuraWanSavePreparationPart: new Set(["cache_key"]),
  ZuraWanGraphQueueGuard: new Set(["plan_json"]),
  VHS_LoadVideoFFmpegPath: new Set(["frame_load_cap", "start_time"]),
};
const GUARD_OUTPUTS = {
  ZuraWanPreparationWindow: { start_frame: 1, frame_count: 2 },
  ZuraWanCarryPoseWindow: { cache_key: 0 },
  ZuraWanSavePreparationPart: { cache_key: 0 },
  VHS_LoadVideoFFmpegPath: { frame_load_cap: 2, start_time: 3 },
};

function clone(value) {
  if (value === undefined) return undefined;
  const text = JSON.stringify(value);
  if (text == null || new TextEncoder().encode(text).length > MAX_SNAPSHOT_BYTES)
    throw new Error("The editable Wan workflow is too large to keep locally.");
  return JSON.parse(text);
}

function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function rootOf(app) { return app.rootGraph || app.graph; }
function nodesOf(graph) { return [...(graph?.nodes || graph?._nodes || [])]; }
function nodeType(node) { return node.comfyClass || node.type; }
function linkOf(graph, id) { return graph.getLink?.(id) || graph.links?.get?.(id); }

export function nativeNodes(graph, prefix = [], result = []) {
  for (const node of nodesOf(graph)) {
    const path = [...prefix, String(node.id)];
    result.push({ node, graph, path: path.join(":"), hosts: prefix });
    if (node.subgraph) nativeNodes(node.subgraph, path, result);
  }
  return result;
}

// Execution IDs are native subgraph-instance paths, not definition IDs.
export function findNativeNode(graph, executionId, roleId) {
  const all = nativeNodes(graph);
  const direct = all.find(item => item.path === String(executionId));
  if (direct) return direct;
  const tagged = roleId && all.filter(item => item.node.properties?.zuraWanRole === roleId);
  if (tagged?.length === 1) return tagged[0];
  throw new Error("A Wan section control moved or became ambiguous. Reopen its motion graph.");
}

function inputWidgets(root, item, name) {
  const widgets = [];
  let node = item.node, graph = item.graph;
  const add = widget => { if (widget && !widgets.includes(widget)) widgets.push(widget); };
  while (true) {
    const input = node.inputs?.find(slot => slot.name === name);
    if (input) add(node.getWidgetFromSlot?.(input));
    add(node.widgets?.find(widget => widget.name === name));
    if (input?.link == null) break;
    const link = linkOf(graph, input.link);
    if (!link || String(link.origin_id) !== String(graph.inputNode?.id))
      throw new Error("A Wan bookkeeping control is connected to an unexpected node.");
    const host = nativeNodes(root).find(entry => entry.node.subgraph === graph)?.node;
    const promoted = host?.inputs?.[link.origin_slot];
    if (!host || !promoted) throw new Error("A promoted Wan control cannot be resolved.");
    node = host; graph = host.graph; name = promoted.name;
  }
  if (!widgets.length) throw new Error("A native Wan section widget is unavailable.");
  return widgets;
}

export function applyWanPatches(root, prompt, plan) {
  const undo = [], changes = [], tags = [];
  const expanded = expandStageSignals(prompt);
  const patches = [...(plan.patches || [])];
  if (plan.guard) patches.push({ node_id: plan.guard.semantic_id,
    class_type: "ZuraWanGraphQueueGuard", role_id: "zura.wan.guard",
    inputs: { plan_json: plan.guard.plan_json || plan.guard.inputs?.plan_json } });
  for (const patch of patches) {
    const item = findNativeNode(root, patch.node_id, patch.role_id);
    const compiled = expanded[patch.node_id];
    if (!compiled || nodeType(item.node) !== compiled.class_type ||
        (patch.class_type && patch.class_type !== compiled.class_type))
      throw new Error("A Wan section node changed while its plan was being prepared.");
    const allowed = BOOKKEEPING[compiled.class_type];
    if (!allowed || (!patch.inputs && !patch.connections))
      throw new Error("The Wan plan contains unsupported node changes.");
    tags.push({ node: item.node, role: patch.role_id });
    for (const [name, connection] of Object.entries(patch.connections || {})) {
      const prior = compiled.inputs?.[name];
      if (!allowed.has(name) || connection?.source_role !== "zura.wan.guard" ||
          connection.output !== GUARD_OUTPUTS[compiled.class_type]?.[name] ||
          !Array.isArray(prior) || prior.length !== 2 ||
          expanded[String(prior[0])]?.class_type !== "ZuraWanGraphQueueGuard" ||
          prior[1] !== connection.output || String(prior[0]) !== String(plan.guard?.semantic_id))
        throw new Error("A Wan section control is no longer connected to its queue guard.");
    }
    for (const [name, value] of Object.entries(patch.inputs || {})) {
      if (compiled.class_type === "VHS_LoadVideoFFmpegPath" ||
          !allowed.has(name) || (typeof value !== "string" && typeof value !== "number") ||
          (typeof value === "number" && !Number.isFinite(value)))
        throw new Error("The Wan plan tried to change a native artist setting.");
      const prior = compiled.inputs?.[name];
      // Guard edges remain native connections. Only its immutable plan changes.
      if (Array.isArray(prior) && prior.length === 2 && expanded[String(prior[0])]) {
        if (expanded[String(prior[0])].class_type !== "ZuraWanGraphQueueGuard")
          throw new Error("A Wan cursor or key is not connected to its queue guard.");
        continue;
      }
      for (const widget of inputWidgets(root, item, name))
        changes.push({ widget, before: clone(widget.value), after: clone(value) });
    }
  }
  // All paths/widgets are checked before the first mutation.
  for (const change of changes) {
    change.widget.value = change.after;
    undo.push(() => { if (equal(change.widget.value, change.after)) change.widget.value = change.before; });
  }
  for (const { node, role } of tags) {
    node.properties ??= {};
    const before = node.properties.zuraWanRole;
    node.properties.zuraWanRole = role;
    undo.push(() => {
      if (node.properties.zuraWanRole !== role) return;
      if (before === undefined) delete node.properties.zuraWanRole;
      else node.properties.zuraWanRole = before;
    });
  }
  root.setDirtyCanvas?.(true, true);
  return () => { for (const restore of undo.reverse()) restore(); root.setDirtyCanvas?.(true, true); };
}

function readState(root) {
  const state = root?.extra?.[STATE_KEY];
  return state?.schema === SCHEMA && STAGES.has(state.stage) &&
    typeof state.projectId === "string" && state.projectId.length > 0 ? state : null;
}

function storeState(root, state) {
  root.extra ??= {};
  root.extra[STATE_KEY] = clone(state);
  root.setDirtyCanvas?.(true, true);
  return root.extra[STATE_KEY];
}

export function preparationSnapshot(root) {
  const snapshot = clone(root.serialize());
  const state = snapshot.extra?.[STATE_KEY];
  if (state) { state.savedPreparation = null; state.preparationPrompt = null; }
  return snapshot;
}

function hasPreparation(prompt) {
  return Object.values(prompt || {}).some(node => node.class_type === "ZuraWanSavePreparationPart");
}

function initialState(root, options) {
  const previous = readState(root);
  if (!options.projectId || !STAGES.has(options.stage)) return previous;
  return { schema: SCHEMA, projectId: options.projectId, stage: options.stage,
    context: clone(options.context || null), progress: clone(options.progress || null),
    savedPreparation: previous?.projectId === options.projectId ? previous.savedPreparation : null,
    preparationPrompt: previous?.projectId === options.projectId ? previous.preparationPrompt : null };
}

function labels(state) {
  if (state.stage === "wan") return { primary: null, secondary: "Edit motion", hint: "Use Queue to render this video." };
  if (state.stage === "wan_merge") return { primary: "Open render", secondary: "Edit motion",
    hint: "Use Queue to finish motion, then open the render graph." };
  const p = state.progress;
  const ready = p?.completed_frames === p?.total_frames && p?.total_frames > 0;
  const section = Number.isInteger(p?.section_index) ? `Section ${p.section_index + 1} of ${p.section_total} is ready. ` : "";
  return { primary: ready ? "Finish motion" : "Next section", secondary: null,
    hint: section + "Use Queue for this section, then update it here." };
}

export class WanGraphControls {
  constructor(app, options = {}) {
    this.app = app; this.options = options; this.busy = false; this.disposed = false;
    this.root = rootOf(app); this.state = initialState(this.root, options);
    if (this.state) this.state = storeState(this.root, this.state);
    this.makeToolbar(options.document || globalThis.document, options.container);
    this.refresh();
  }

  current(root = this.root, state = this.state) {
    return !this.disposed && rootOf(this.app) === root && readState(root) === state;
  }

  makeToolbar(doc, container) {
    if (!doc || !this.state) return;
    if (!doc.getElementById("zura-wan-graph-style")) {
      const style = doc.createElement("style"); style.id = "zura-wan-graph-style";
      style.textContent = `.zura-wan-graph-controls{position:fixed;right:20px;bottom:24px;z-index:1100;max-width:min(430px,calc(100vw - 32px));box-sizing:border-box;padding:12px 14px;border:1px solid #526272;border-radius:10px;background:#17212bef;color:#edf3f8;font:13px/1.45 system-ui;box-shadow:0 5px 24px #0004}.zura-wan-graph-controls[hidden]{display:none}.zura-wan-graph-controls p{margin:0 0 8px}.zura-wan-graph-controls .wan-graph-actions{display:flex;flex-wrap:wrap;gap:8px}.zura-wan-graph-controls button{font:inherit;cursor:pointer;border:1px solid #7394a8;border-radius:6px;padding:6px 12px;background:#244b60;color:#fff}.zura-wan-graph-controls button:disabled{cursor:wait;opacity:.6}.zura-wan-graph-controls button:focus-visible{outline:2px solid #c8e9ff;outline-offset:3px}.zura-wan-graph-controls .wan-graph-error{color:#ffd0c9;margin-top:8px}@media(max-width:600px){.zura-wan-graph-controls{left:12px;right:12px;bottom:12px;max-width:none}.zura-wan-graph-controls button{min-height:40px}}`;
      doc.head.append(style);
    }
    const box = doc.createElement("section"); box.className = "zura-wan-graph-controls";
    box.setAttribute("aria-label", "Wan motion graph controls");
    const hint = doc.createElement("p"); hint.setAttribute("role", "status"); hint.setAttribute("aria-live", "polite");
    const actions = doc.createElement("div"); actions.className = "wan-graph-actions";
    const primary = doc.createElement("button"), secondary = doc.createElement("button");
    primary.type = secondary.type = "button";
    primary.onclick = () => this.run(this.state.stage === "wan_merge" ? "render" :
      labels(this.state).primary === "Finish motion" ? "finish" : "next").catch(() => {});
    secondary.onclick = () => this.editMotion().catch(() => {});
    const error = doc.createElement("p"); error.className = "wan-graph-error"; error.setAttribute("role", "alert");
    actions.append(primary, secondary); box.append(hint, actions, error); (container || doc.body).append(box);
    this.ui = { box, hint, primary, secondary, error };
  }

  refresh(message = "", error = "") {
    if (!this.ui) return;
    const live = this.current(); this.ui.box.hidden = !live;
    if (!live) return;
    const view = labels(this.state);
    this.ui.box.setAttribute("aria-busy", String(this.busy));
    this.ui.hint.textContent = message || view.hint;
    for (const [name, label] of [["primary", view.primary], ["secondary", view.secondary]]) {
      this.ui[name].hidden = !label; this.ui[name].disabled = this.busy;
      this.ui[name].textContent = label || "";
    }
    this.ui.error.textContent = error; this.ui.error.hidden = !error;
  }

  async request(action, prompt) {
    if (typeof this.options.request !== "function") throw new Error("Wan graph planning is unavailable. Reopen Studio.");
    return this.options.request(`/projects/${encodeURIComponent(this.state.projectId)}/wan-graph/plan`,
      { action, context: clone(this.state.context), prompt: clone(prompt) });
  }

  async compiled(root = this.root) { return (await this.app.graphToPrompt(root)).output; }

  async run(action = "next") {
    if (this.busy) throw new Error("Wait for the current graph update to finish.");
    if (!this.current()) throw new Error("This Wan workflow is no longer active.");
    this.busy = true; this.refresh("Updating the motion graph…");
    const root = this.root, state = this.state;
    let undo = null;
    try {
      const visible = await this.compiled(root);
      if (!this.current(root, state)) throw new Error("The active workflow changed. No section was updated.");
      // Studio may export a completed default preparation's merge graph before
      // this artist has opened an editable motion workflow. The planner checks
      // that default builder and the strict cache before allowing its render.
      const warmMerge = state.stage === "wan_merge" && !hasPreparation(state.preparationPrompt);
      const prompt = state.stage === "wan_prepare" || warmMerge ? visible : state.preparationPrompt;
      if (!warmMerge && !hasPreparation(prompt)) throw new Error("Open Edit motion before updating its sections.");
      const result = await this.request(state.stage === "wan_merge" ? "render" : action, prompt);
      if (!this.current(root, state) || !equal(visible, await this.compiled(root)))
        throw new Error("The workflow changed during planning. Update the section again.");
      if (!result || !["prepare", "merge", "render"].includes(result.action) ||
          (!result.context && !(warmMerge && result.context === null &&
            ["merge", "render"].includes(result.action))))
        throw new Error("Wan planning returned an incomplete response.");
      if (result.action === "prepare") {
        if (state.stage !== "wan_prepare") throw new Error("Return to Edit motion to prepare this section.");
        if (!result.guard?.plan_json && !result.guard?.inputs?.plan_json)
          throw new Error("The section plan is missing its queue guard.");
        undo = applyWanPatches(root, visible, result);
        const updated = await this.compiled(root);
        if (!this.current(root, state)) throw new Error("The active workflow changed. No section was updated.");
        if (!result.graph || await promptFingerprint(updated) !== await promptFingerprint(result.graph))
          throw new Error("The section update did not reach its native controls. The previous values were restored.");
        if (!this.current(root, state)) throw new Error("The active workflow changed. No section was updated.");
        const next = { ...state, context: result.context, progress: result.progress,
          preparationPrompt: updated, savedPreparation: preparationSnapshot(root) };
        this.state = storeState(root, next);
        undo = null;
        this.refresh(result.progress?.recipe_forked ? "Your motion edits started a fresh preparation. Use Queue for this section." : "Section updated. Use Queue when ready.");
      } else if (result.action === "merge" && state.stage === "wan_merge") {
        this.state = storeState(root, { ...state, context: result.context, progress: result.progress });
        this.refresh("Use Queue to finish motion first, then open the render graph.");
      } else {
        const saved = state.stage === "wan_prepare" ? preparationSnapshot(root) : state.savedPreparation;
        const api = state.stage === "wan_prepare" ? visible : state.preparationPrompt;
        await this.openStage(result, { savedPreparation: saved, preparationPrompt: api });
      }
      return result;
    } catch (error) {
      undo?.(); this.refresh("", String(error.message || error).slice(0, 600)); throw error;
    } finally { this.busy = false; this.refresh(this.ui?.hint.textContent, this.ui?.error.textContent); }
  }

  async openStage(result, retained) {
    if (!result.graph || typeof result.graph !== "object")
      throw new Error("The next native Wan graph is unavailable. No workflow was replaced.");
    const origin = this.root, previous = clone(origin.serialize()), previousState = this.state;
    const token = `${Date.now()}:${Math.random()}`;
    loading.add(this.app);
    try {
      await this.app.loadApiJson(result.graph, `Wan ${result.action} · editable.json`);
      const loaded = rootOf(this.app);
      if (await promptFingerprint(await this.compiled(loaded)) !== await promptFingerprint(result.graph))
        throw new Error("The active workflow changed while opening the next Wan stage.");
      loaded.extra ??= {}; loaded.extra.zuraWanTransition = token;
      if (typeof this.options.tidy === "function")
        await this.options.tidy(this.app, result.graph, result.action === "merge" ? "wan_merge" : result.action === "render" ? "wan" : "wan_prepare");
      if (rootOf(this.app) !== loaded || loaded.extra?.zuraWanTransition !== token)
        throw new Error("The active workflow changed. Its graph was preserved.");
      if (await promptFingerprint(await this.compiled(loaded)) !== await promptFingerprint(result.graph))
        throw new Error("Native grouping changed the Wan stage inputs.");
      if (rootOf(this.app) !== loaded || loaded.extra?.zuraWanTransition !== token)
        throw new Error("The active workflow changed. Its graph was preserved.");
      delete loaded.extra.zuraWanTransition;
      this.root = loaded;
      this.state = storeState(loaded, { ...previousState, ...retained,
        stage: result.action === "merge" ? "wan_merge" : result.action === "render" ? "wan" : "wan_prepare",
        context: result.context, progress: result.progress });
      if (result.action === "prepare") {
        this.state.preparationPrompt = await this.compiled(loaded);
        this.state.savedPreparation = preparationSnapshot(loaded);
      }
      this.refresh();
    } catch (error) {
      const current = rootOf(this.app);
      // Roll back only a graph still owned by this transition. Never replace a
      // different workflow the artist opened while the async call was pending.
      if (current.extra?.zuraWanTransition === token || (current === origin && readState(current) === previousState)) {
        const restored = await this.app.loadGraphData(previous, true, true, "Wan motion · editable.json");
        if (restored === false) throw new Error("The previous Wan workflow could not be restored. Reopen its saved graph.");
        this.root = rootOf(this.app); this.state = readState(this.root);
      }
      throw error;
    } finally { loading.delete(this.app); this.refresh(); }
  }

  async editMotion() {
    if (this.busy) throw new Error("Wait for the current graph update to finish.");
    if (!this.current()) throw new Error("This Wan workflow is no longer active.");
    this.busy = true; this.refresh("Opening the editable motion graph…");
    const root = this.root, state = this.state;
    loading.add(this.app);
    try {
      if (state.savedPreparation) {
        const saved = clone(state.savedPreparation);
        saved.extra ??= {}; saved.extra[STATE_KEY] = clone({ ...state, stage: "wan_prepare" });
        const previous = clone(root.serialize()), token = `${Date.now()}:${Math.random()}`;
        saved.extra.zuraWanTransition = token;
        try {
          const loaded = await this.app.loadGraphData(saved, true, true, "Wan motion · editable.json");
          if (loaded === false) throw new Error("The saved native motion graph could not be opened.");
          const active = rootOf(this.app);
          if (active.extra?.zuraWanTransition !== token)
            throw new Error("The active workflow changed. Its graph was preserved.");
          delete active.extra.zuraWanTransition;
          this.root = active; this.state = readState(active);
        } catch (error) {
          const active = rootOf(this.app);
          if (active.extra?.zuraWanTransition === token || this.current(root, state)) {
            const restored = await this.app.loadGraphData(previous, true, true, "Wan render · editable.json");
            if (restored === false) throw new Error("The previous Wan workflow could not be restored. Reopen its saved graph.");
            this.root = rootOf(this.app); this.state = readState(this.root);
          }
          throw error;
        }
      } else {
        const visible = await this.compiled(root);
        const result = await this.request("edit_motion", visible);
        if (!this.current(root, state) || !equal(visible, await this.compiled(root)))
          throw new Error("The workflow changed. Its graph was preserved.");
        if (result.action !== "prepare") throw new Error("The editable motion graph is unavailable.");
        await this.openStage(result, { savedPreparation: null, preparationPrompt: null });
      }
      this.refresh("Motion edits restored. Update the section before using Queue.");
    } catch (error) { this.refresh("", String(error.message || error).slice(0, 600)); throw error; }
    finally { loading.delete(this.app); this.busy = false; this.refresh(this.ui?.hint.textContent, this.ui?.error.textContent); }
  }

  dispose() { this.disposed = true; this.ui?.box.remove(); }
}

// Call after loadApiJson + native tidy, and from the native extension hook
// afterConfigureGraph(missingNodeTypes, app) with request/tidy callbacks only.
export function attachWanGraphControls(app, options = {}) {
  if (loading.has(app)) return controllers.get(app) || null;
  controllers.get(app)?.dispose();
  const root = rootOf(app);
  if (!readState(root) && !(options.projectId && STAGES.has(options.stage))) {
    controllers.delete(app); return null;
  }
  const controller = new WanGraphControls(app, options);
  controllers.set(app, controller); return controller;
}
