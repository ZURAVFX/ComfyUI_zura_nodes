/* A reusable visual, ordered shot planner. No inference or queueing in the UI. */
import { app } from '/scripts/app.js';
import { api } from '/scripts/api.js';

const css = {
  shell: { color: '#e8edf5', background: '#1b222d', padding: '10px', borderRadius: '8px',
    font: '12px system-ui,sans-serif', height: '640px', minHeight: '640px', maxHeight: '640px',
    boxSizing: 'border-box', overflow: 'auto', overscrollBehavior: 'contain' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: '6px' },
  tile: { position: 'relative', minWidth: '0', border: '2px solid #405064', borderRadius: '6px',
    overflow: 'hidden', cursor: 'pointer', background: '#29323f', textAlign: 'left', color: '#fff', padding: '0' },
  image: { width: '100%', aspectRatio: '16/10', objectFit: 'contain', display: 'block',
    background: '#111820' },
  timeline: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: '6px', marginTop: '8px' },
  shot: { border: '1px solid #69788c', borderRadius: '5px', padding: '6px 8px', color: '#fff',
    background: '#303947', cursor: 'pointer' },
};

function make(tag, text, parent, styles = {}) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  Object.assign(el.style, styles);
  parent.append(el);
  if (tag === 'button') {
    el.type = 'button';
    el.onkeydown = event => event.stopPropagation();
    el.onfocus = () => { el.style.outline = '2px solid #fff'; el.style.outlineOffset = '2px'; };
    el.onblur = () => { el.style.outline = ''; };
  }
  return el;
}

function widget(node, name) { return node.widgets?.find(w => w.name === name); }

const seedControls = new Set(['fixed', 'increment', 'decrement', 'randomize']);

function widgetDefinitions(nodeData) {
  return Object.entries({ ...nodeData.input?.required, ...nodeData.input?.optional })
    .filter(([, [kind, options]]) => !options?.forceInput &&
      (Array.isArray(kind) || ['STRING', 'INT', 'FLOAT', 'BOOLEAN'].includes(kind)));
}

function validWidgetValue(value, [kind, options = {}]) {
  if (Array.isArray(kind)) return kind.includes(value);
  if (kind === 'STRING') return typeof value === 'string';
  if (kind === 'BOOLEAN') return typeof value === 'boolean';
  if (typeof value !== 'number' || !Number.isFinite(value)) return false;
  if (kind === 'INT' && !Number.isInteger(value)) return false;
  return (options.min === undefined || value >= options.min) &&
    (options.max === undefined || value <= options.max);
}

// Older workflows omitted the frontend's automatically inserted seed control.
// Decode by the actual input schema rather than shifting values blindly. Both
// old arrays (with/without controls) remain readable after disabling that extra
// seed widget. A named snapshot protects subsequent saves from future changes.
export function decodeSavedWidgetValues(definitions, values) {
  if (!Array.isArray(values)) return null;
  const result = {};
  let index = 0;
  for (const [name, definition] of definitions) {
    const value = values[index++];
    if (!validWidgetValue(value, definition)) return null;
    result[name] = value;
    if (['seed', 'noise_seed', 'klein_seed'].includes(name) && seedControls.has(values[index])) index++;
  }
  // The first gallery version serialized its otherwise non-serializing DOM
  // widget as an empty trailing value. No other unmatched data is accepted.
  return index === values.length || (index === values.length - 1 && values[index] === '') ? result : null;
}

function installWidgetPersistence(nodeType, nodeData) {
  const definitions = widgetDefinitions(nodeData);
  const configure = nodeType.prototype.onConfigure;
  nodeType.prototype.onConfigure = function (data) {
    const result = configure?.call(this, data);
    const saved = { ...decodeSavedWidgetValues(definitions, data?.widgets_values) };
    // A browser may have saved already-shifted widgets before this extension
    // was updated. Invalid or partial named data must not block recovery from
    // a valid positional array. Valid artist overrides still take precedence.
    const named = data?.properties?.zura_widget_values;
    for (const [name, definition] of definitions) {
      if (named && Object.hasOwn(named, name) && validWidgetValue(named[name], definition)) {
        saved[name] = named[name];
      }
    }
    if (saved) {
      for (const [name, definition] of definitions) {
        const target = widget(this, name);
        if (target && Object.hasOwn(saved, name) && validWidgetValue(saved[name], definition)) {
          target.value = saved[name];
        }
      }
    }
    return result;
  };
  const serialize = nodeType.prototype.onSerialize;
  nodeType.prototype.onSerialize = function (data) {
    serialize?.call(this, data);
    data.properties ||= {};
    data.properties.zura_widget_values = Object.fromEntries(definitions
      .map(([name]) => [name, widget(this, name)?.value])
      .filter(([, value]) => value !== undefined));
  };
}

function workflowStage(node) {
  const stageNode = [node.graph, app.graph].flatMap(graph => graph?._nodes || graph?.nodes || [])
    .find(n => n.type === 'ZuraMulticamStageV3' || n.comfyClass === 'ZuraMulticamStageV3');
  const stageWidget = stageNode?.widgets?.find(w => w.name === 'stage');
  return stageWidget ? { stageNode, stageWidget } : null;
}

function draw(node, root) {
  if (!root) return;
  const oldScroll = root.scrollTop;
  root.replaceChildren();
  const data = node.zuraGallery;
  if (!data || !Number.isInteger(data.shot_count) || data.shot_count < 1) {
    make('div', 'Build your camera plan', root, { fontSize: '18px', fontWeight: '700', marginBottom: '8px' });
    make('div', '1. Choose the clip length and frames per shot.\n2. Set the stage to “1 · Plan angles” and run.\n3. Pick a shot, then click its camera preview here.', root,
      { whiteSpace: 'pre-line', lineHeight: '1.8' });
    make('div', 'Clicking a camera saves your selection. It does not start a render.', root, { marginTop: '9px', color: '#b6c4d3' });
    return;
  }
  const choicesWidget = widget(node, 'shot_choices');
  const promptsWidget = widget(node, 'shot_prompts');
  let choices = String(choicesWidget?.value || '').split(',').map(x => Number(x.trim()));
  if (choices.length !== data.shot_count || choices.some(x => !Number.isInteger(x) || x < 0 || x > 9)) {
    choices = Array.from({ length: data.shot_count }, (_, i) =>
      Number.isInteger(choices[i]) && choices[i] >= 0 && choices[i] <= 9 ? choices[i] : 0);
    if (choicesWidget) choicesWidget.value = choices.join(',');
  }
  let prompts;
  try { prompts = JSON.parse(String(promptsWidget?.value || '[]')); } catch { prompts = []; }
  if (!Array.isArray(prompts) || prompts.length !== data.shot_count) {
    const saved = Array.isArray(prompts) ? prompts : [];
    prompts = Array.from({ length: data.shot_count }, (_, i) => typeof saved[i] === 'string' ? saved[i] : '');
    if (promptsWidget) promptsWidget.value = JSON.stringify(prompts);
  }
  let selectedShot = Math.max(0, Math.min(node.zuraSelectedShot || 0, data.shot_count - 1));
  const angles = Array.isArray(data.angles) ? data.angles : [];
  const label = id => id === 0 ? 'Source camera' : angles.find(a => a.id === id)?.label || `Angle ${id}`;
  const fps = Number(data.fps || data.frame_rate) > 0 ? Number(data.fps || data.frame_rate) : 24;
  const seconds = frames => (frames / fps).toFixed(2).replace(/\.00$/, '');
  make('div', 'Plan your shots', root, { fontSize: '18px', fontWeight: '750' });
  make('div', data.look_enabled ? 'Scene / relight is on. Source camera keeps its original viewpoint.' : 'Original scene and lighting.', root,
    { color: data.look_enabled ? '#f2cf89' : '#aab8c9', marginTop: '3px', fontSize: '11px' });
  const summary = make('div', `${data.shot_count} shots · ${data.shot_count - 1} cuts · ${data.frame_count} frames`, root,
    { margin: '3px 0 7px', fontWeight: '700', fontSize: '15px' });
  const stageControls = make('div', null, root, { border: '1px solid #496675', borderRadius: '8px',
    padding: '10px', margin: '10px 0 14px', background: '#21313d' });
  const stageHeading = make('div', 'WORKFLOW STAGE', stageControls,
    { color: '#9db5c3', fontSize: '10px', fontWeight: '800', letterSpacing: '0.08em' });
  const stageRibbon = make('div', null, stageControls, { display: 'flex', gap: '6px', margin: '7px 0' });
  const planStep = make('div', '1 · PLAN ANGLES', stageRibbon, { flex: '1', textAlign: 'center',
    padding: '7px 4px', borderRadius: '5px', fontSize: '11px', fontWeight: '800' });
  const renderStep = make('div', '2 · RENDER VIDEO', stageRibbon, { flex: '1', textAlign: 'center',
    padding: '7px 4px', borderRadius: '5px', fontSize: '11px', fontWeight: '800' });
  const stageLabel = make('div', '', stageControls, { color: '#d8e9ef', fontSize: '11px', lineHeight: '1.45' });
  const stageButton = make('button', '', stageControls, { ...css.shot, display: 'block', width: '100%',
    marginTop: '9px', padding: '10px', background: '#1d675c', borderColor: '#65dfca', fontWeight: '800' });
  stageButton.onpointerdown = event => event.stopPropagation();
  stageButton.onclick = () => {
    const current = workflowStage(node);
    if (!current) return;
    const next = String(current.stageWidget.value).startsWith('1') ? '2 · Render multicam' : '1 · Plan angles';
    current.stageWidget.value = next;
    current.stageWidget.callback?.(next);
    current.stageNode.setDirtyCanvas?.(true, true);
    node.setDirtyCanvas?.(true, true);
    paint();
  };
  make('div', '1 · Pick the shot to edit', root, { color: '#65dfca', fontWeight: '700', marginTop: '10px' });
  const timeline = make('div', null, root, css.timeline);
  timeline.setAttribute('aria-label', 'Shot timeline');
  const selected = make('div', '', root, { color: '#d8e9ef', margin: '10px 0 6px', fontWeight: '700' });
  make('div', '2 · Click one camera for this shot', root, { color: '#65dfca', fontWeight: '700', marginTop: '8px' });
  make('div', 'The tick belongs to the selected shot. Reuse a camera in as many shots as you like.', root,
    { color: '#b6c4d3', fontSize: '11px', marginTop: '4px' });
  const tools = make('div', null, root, { display: 'flex', gap: '6px', margin: '7px 0', flexWrap: 'wrap' });
  const action = (text, click) => {
    const button = make('button', text, tools, css.shot);
    button.onpointerdown = event => event.stopPropagation();
    button.onclick = click;
    return button;
  };
  const setChoice = id => {
    choices[selectedShot] = id;
    // Camera changes must not silently delete an artist's saved prompt.
    if (choicesWidget) { choicesWidget.value = choices.join(','); choicesWidget.callback?.(choicesWidget.value); }
    node.setDirtyCanvas?.(true, true);
    paint();
  };
  const applyAll = action('Use this camera for all shots', () => {
    choices.fill(choices[selectedShot]);
    if (choicesWidget) { choicesWidget.value = choices.join(','); choicesWidget.callback?.(choicesWidget.value); }
    node.setDirtyCanvas?.(true, true);
    paint();
  });
  applyAll.title = 'Copies the selected camera to every shot. Your shot directions are retained.';
  const nextShot = action('Next shot →', () => {
    selectedShot = (selectedShot + 1) % data.shot_count;
    node.zuraSelectedShot = selectedShot;
    paint();
  });
  nextShot.style.display = data.shot_count > 1 ? '' : 'none';
  const source = action(null, () => setChoice(0));
  source.style.display = 'flex';
  source.style.alignItems = 'center';
  source.style.width = '100%';
  source.style.gap = '10px';
  source.setAttribute('aria-label', 'Use source camera for the selected shot');
  if (data.source?.filename) {
    const img = make('img', null, source, { width: '100px', height: '60px', objectFit: 'contain', background: '#111820' });
    img.alt = 'Source camera preview';
    img.src = api.apiURL('/view?' + new URLSearchParams({ ...data.source, type: 'output' }));
    img.onerror = () => { img.style.display = 'none'; };
  }
  const sourceCaption = make('div', null, source);
  make('div', 'Source camera', sourceCaption, { fontWeight: '700' });
  make('div', 'Keep the source viewpoint', sourceCaption, { color: '#b6c4d3', fontSize: '11px', marginTop: '3px' });
  const sourceTick = make('span', '✓', source, { marginLeft: 'auto', color: '#65dfca', fontSize: '20px' });
  sourceTick.setAttribute('aria-hidden', 'true');
  const grid = make('div', null, root, css.grid);
  make('div', 'The preview guides the camera and framing. Review a short render before processing a longer clip.', root,
    { color: '#b6c4d3', fontSize: '11px', marginTop: '7px', lineHeight: '1.45' });
  const motionBox = make('details', null, root, { margin: '12px 0', padding: '9px', background: '#273442', borderRadius: '6px' });
  motionBox.open = Boolean(node.zuraMotionOpen || prompts[selectedShot]);
  motionBox.ontoggle = () => { node.zuraMotionOpen = motionBox.open; };
  const motionSummary = make('summary', 'Optional · prompt / camera movement for this shot', motionBox,
    { color: '#d8e9ef', fontWeight: '700', cursor: 'pointer' });
  motionSummary.onpointerdown = event => event.stopPropagation();
  const motion = make('textarea', null, motionBox, {
    boxSizing: 'border-box', width: '100%', height: '68px', marginTop: '8px', padding: '7px',
    borderRadius: '5px', border: '1px solid #677f91', background: '#111b25', color: '#fff',
    resize: 'none', font: '12px system-ui,sans-serif' });
  motion.setAttribute('aria-label', 'Additional prompt for the selected shot');
  motion.placeholder = 'e.g. A quick, subtle handheld zoom towards the face';
  motion.onpointerdown = event => event.stopPropagation();
  motion.onkeydown = event => event.stopPropagation();
  motion.oninput = () => {
    prompts[selectedShot] = motion.value;
    if (promptsWidget) { promptsWidget.value = JSON.stringify(prompts); promptsWidget.callback?.(promptsWidget.value); }
    node.setDirtyCanvas?.(true, true);
    paintTimeline();
  };
  const suggestions = make('div', null, motionBox, { display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '5px' });
  for (const [name, phrase] of [
    ['Subtle zoom', 'The camera makes a quick, subtle handheld zoom towards the face.'],
    ['Focus on eyes', 'The focus gently adjusts to make the performer’s eyes sharp.'],
    ['Slow arc', 'The camera makes a very slow, subtle arc around the performer.'],
    ['Clear prompt', '']]) {
    const button = make('button', name, suggestions, css.shot);
    button.onclick = () => { motion.value = phrase; motion.oninput(); };
    button.onpointerdown = event => event.stopPropagation();
  }
  const motionNote = make('div', '', motionBox,
    { color: '#aab8c9', marginTop: '5px', fontSize: '11px' });
  const ready = make('div', '', root, { border: '1px solid #405064', borderRadius: '6px', padding: '9px', lineHeight: '1.5' });
  ready.setAttribute('aria-live', 'polite');
  make('div', 'Changed the source, shot length or look? Run “1 · Plan angles” again before rendering.', root,
    { color: '#aab8c9', fontSize: '11px', marginTop: '6px' });
  const paint = () => {
    summary.textContent = `${seconds(data.frame_count)} seconds · ${data.shot_count} shots · ${fps} fps`;
    const start = selectedShot * data.frames_per_shot;
    const end = Math.min(start + data.frames_per_shot, data.frame_count);
    selected.textContent = `Shot ${selectedShot + 1} · ${seconds(start)}–${seconds(end)}s · ${label(choices[selectedShot])}`;
    motion.value = prompts[selectedShot] || '';
    const sourceUnsupported = choices[selectedShot] === 0;
    motion.disabled = sourceUnsupported;
    motion.placeholder = sourceUnsupported ? 'Choose a generated camera to add a shot direction.' : 'Add direction for this shot, or leave blank to follow the performance.';
    suggestions.querySelectorAll('button').forEach(button => {
      button.disabled = sourceUnsupported && button.textContent !== 'Clear prompt';
      button.style.opacity = button.disabled ? '0.5' : '1';
    });
    motionNote.textContent = sourceUnsupported
      ? 'Source camera keeps the original performance. Choose another camera to add direction, or clear an existing prompt here.'
      : 'Keep moves subtle. Strong movements can change the framing or performance. Leave blank for the tested default.';
    source.style.borderColor = choices[selectedShot] === 0 ? '#50d3bd' : '#69788c';
    source.setAttribute('aria-pressed', String(choices[selectedShot] === 0));
    sourceTick.style.visibility = choices[selectedShot] === 0 ? 'visible' : 'hidden';
    grid.querySelectorAll('[data-angle]').forEach(el => {
      const active = Number(el.dataset.angle) === choices[selectedShot];
      el.style.borderColor = active ? '#50d3bd' : '#405064';
      el.style.boxShadow = active ? '0 0 0 1px #50d3bd' : 'none';
      el.setAttribute('aria-pressed', String(active));
      el.querySelector('[data-tick]').style.display = active ? 'block' : 'none';
    });
    const cuts = choices.slice(1).filter((id, i) => id !== choices[i]).length;
    const sourcePromptShot = choices.findIndex((id, index) => id === 0 && prompts[index]);
    ready.textContent = sourcePromptShot >= 0
      ? `Shot ${sourcePromptShot + 1} has a direction but uses Source camera. Choose a generated camera or clear its prompt before rendering.`
      : `${data.shot_count} shots · ${cuts} camera ${cuts === 1 ? 'change' : 'changes'} planned. Choosing cameras never starts generation.`;
    ready.style.borderColor = sourcePromptShot >= 0 ? '#d4a75c' : '#405064';
    const currentStage = workflowStage(node);
    const rendering = String(currentStage?.stageWidget.value || '').startsWith('2');
    stageLabel.textContent = currentStage
      ? rendering ? 'Selected cameras are ready. Press ComfyUI Run to start H3 generation.'
        : 'Pick and review cameras here. H3 generation is off in this stage.'
      : 'Use the START HERE stage switch to choose Plan or Render.';
    for (const [step, active] of [[planStep, !rendering], [renderStep, rendering]]) {
      step.style.background = active ? '#26685e' : '#303e49';
      step.style.color = active ? '#fff' : '#9caebd';
      step.style.border = active ? '1px solid #65dfca' : '1px solid #506477';
    }
    stageControls.style.borderColor = rendering ? '#65dfca' : '#496675';
    stageButton.style.display = currentStage ? 'block' : 'none';
    stageButton.textContent = rendering ? '← Back to angle planning' : 'Continue to Render →';
    stageButton.style.background = rendering ? '#344756' : '#1d675c';
    stageButton.disabled = !rendering && sourcePromptShot >= 0;
    stageButton.style.opacity = stageButton.disabled ? '0.5' : '1';
    stageButton.setAttribute('aria-label', rendering ? 'Switch workflow stage back to Plan angles'
      : 'Switch workflow stage to Render multicam');
    paintTimeline();
  };
  function paintTimeline() {
    timeline.replaceChildren();
    choices.forEach((id, i) => {
      const start = i * data.frames_per_shot;
      const end = Math.min((i + 1) * data.frames_per_shot, data.frame_count);
      const shot = make('button', null, timeline, { ...css.shot, textAlign: 'left', font: 'inherit' });
      make('div', `Shot ${i + 1} · ${seconds(end - start)}s`, shot, { fontWeight: '750' });
      make('div', label(id), shot, { marginTop: '3px' });
      make('div', `${seconds(start)}–${seconds(end)}s${prompts[i] ? ' · prompt' : ''}`, shot,
        { fontSize: '10px', color: '#c3cfdc', marginTop: '3px' });
      shot.title = `Frames ${start}–${end - 1}`;
      shot.setAttribute('aria-pressed', String(i === selectedShot));
      shot.setAttribute('aria-label', `Edit shot ${i + 1}, ${seconds(start)} to ${seconds(end)} seconds, ${label(id)}`);
      shot.style.borderColor = i === selectedShot ? '#50d3bd' : '#69788c';
      shot.style.background = i === selectedShot ? '#25483f' : '#303947';
      shot.onpointerdown = event => event.stopPropagation();
      shot.onclick = () => {
        selectedShot = i; node.zuraSelectedShot = i; paint();
        timeline.children[i]?.focus({ preventScroll: true });
      };
    });
  }
  for (let id = 1; id <= 9; id++) {
    const card = angles.find(a => a.id === id) || { id, label: `Angle ${id}` };
    const tile = make('button', null, grid, css.tile);
    tile.onpointerdown = event => event.stopPropagation();
    tile.dataset.angle = String(card.id);
    tile.setAttribute('aria-label', `Use ${card.label} for the selected shot`);
    const tick = make('span', '✓', tile, { position: 'absolute', top: '5px', right: '5px', borderRadius: '50%',
      padding: '1px 5px', color: '#11251f', background: '#65dfca', fontWeight: '800' });
    tick.dataset.tick = 'true';
    tick.setAttribute('aria-hidden', 'true');
    const img = make('img', null, tile, css.image);
    img.alt = `${card.label} reference preview`;
    const missing = () => {
      img.style.display = 'none';
      tile.disabled = true; tile.style.opacity = '0.55'; tile.style.cursor = 'not-allowed';
      make('div', 'Preview unavailable · run Plan again', tile, { padding: '14px 7px', color: '#f2cf89', fontSize: '11px' });
    };
    img.onerror = missing;
    if (card.filename) img.src = api.apiURL('/view?' + new URLSearchParams({ filename: card.filename,
      subfolder: card.subfolder || '', type: 'output' }));
    else missing();
    img.loading = 'lazy';
    make('div', card.label, tile, { padding: '5px 6px 2px', fontWeight: '700' });
    tile.onclick = () => setChoice(card.id);
  }
  paint();
  root.scrollTop = oldScroll;
}

app.registerExtension({
  name: 'Zura.MulticamAngleGalleryV3',
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (['ZuraMulticamStageV3', 'ZuraAngleGalleryV3', 'ZuraH3MulticamV3',
         'ZuraH3MulticamV4', 'ZuraCleanMulticamV4', 'ZuraH3SingleAngle'].includes(nodeData.name)) {
      installWidgetPersistence(nodeType, nodeData);
    }
    if (nodeData.name !== 'ZuraAngleGalleryV3') return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = created?.apply(this, args);
      // The board edits these serializable values directly. Showing their raw
      // comma/JSON fields above the pictures is confusing for artists.
      for (const name of ['shot_choices', 'shot_prompts', 'look_prompt', 'look_enabled']) {
        const raw = widget(this, name);
        if (raw) { raw.hidden = true; raw.computeSize = () => [0, -4]; }
      }
      const root = document.createElement('div');
      Object.assign(root.style, css.shell);
      this.addDOMWidget('camera_gallery', 'zuraCameraGallery', root, {
        serialize: false, getMinHeight: () => 640, getMaxHeight: () => 640,
        getValue: () => '', setValue: () => {},
      });
      // Set an initial size only. Redraws never add to the node's current height.
      this.setSize([Math.max(this.size?.[0] || 0, 620), Math.max(this.size?.[1] || 0, 880)]);
      this.zuraGalleryRoot = root;
      draw(this, root);
      return result;
    };
    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      executed?.call(this, message);
      const incoming = message?.zura_angle_gallery?.[0];
      if (incoming) {
        this.zuraGallery = incoming;
        draw(this, this.zuraGalleryRoot);
      }
    };
    const serialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (data) {
      serialize?.call(this, data);
      if (this.zuraGallery) {
        data.properties ||= {};
        data.properties.zura_angle_gallery_v3 = this.zuraGallery;
      }
    };
    const configure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (data) {
      const result = configure?.call(this, data);
      this.zuraGallery = data?.properties?.zura_angle_gallery_v3 || null;
      if (this.zuraGalleryRoot) draw(this, this.zuraGalleryRoot);
      return result;
    };
  },
});
