import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Run the shipped extension and its event handlers with the small DOM surface
// it uses. This tests the rendered controls, not a duplicate of their logic.
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.scrollTop = 0;
    this.ownText = '';
  }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; this.ownText = ''; }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get textContent() { return this.ownText + this.children.map(child => child.textContent).join(''); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  querySelectorAll(selector) {
    const matches = element => selector.startsWith('[data-')
      ? Object.hasOwn(element.dataset, selector.slice(6, -1))
      : element.tagName === selector;
    return this.children.flatMap(child => [ ...(matches(child) ? [child] : []), ...child.querySelectorAll(selector) ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { this.onfocus?.(); }
}

const extensions = [];
const app = { registerExtension: extension => extensions.push(extension) };
const source = fs.readFileSync(new URL('../web/multicam_angle_gallery.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
vm.runInNewContext(source, {
  app, api: { apiURL: path => path }, URLSearchParams,
  document: { createElement: tag => new Element(tag) },
});

class GalleryNode {
  constructor(properties = {}) {
    this.properties = properties;
    this.widgets = [
      { name: 'shot_choices', value: '0' },
      { name: 'shot_prompts', value: '[]' },
      { name: 'look_prompt', value: '' },
      { name: 'look_enabled', value: false },
    ];
    this.size = [620, 880];
    this.sizeCalls = 0;
    this.stageChanges = [];
    const stageWidget = { name: 'stage', value: '1 · Plan angles',
      callback: value => this.stageChanges.push(value) };
    this.stageWidget = stageWidget;
    this.graph = { _nodes: [{ type: 'ZuraMulticamStageV3', widgets: [stageWidget] }] };
  }
  addDOMWidget(name, type, root, options) { this.domOptions = options; }
  setSize(size) { this.size = size; this.sizeCalls++; }
  setDirtyCanvas() { this.dirty = true; }
  onConfigure(data) { this.properties = data.properties || {}; }
}
extensions[0].beforeRegisterNodeDef(GalleryNode, {
  name: 'ZuraAngleGalleryV3', input: { required: {
    shot_choices: ['STRING', {}], shot_prompts: ['STRING', {}],
    look_prompt: ['STRING', {}], look_enabled: ['BOOLEAN', {}],
  } },
});

const metadata = count => ({ shot_count: count, frame_count: 48, frames_per_shot: 48 / count, fps: 24,
  source: { filename: 'source.png' },
  angles: Array.from({ length: 9 }, (_, i) => ({ id: i + 1, label: `Camera ${i + 1}`, filename: `angle${i + 1}.png` })),
});
function create(properties = {}, count) {
  const node = new GalleryNode(properties);
  node.onNodeCreated();
  if (count) node.onExecuted({ zura_angle_gallery: [metadata(count)] });
  return node;
}
const field = (node, name) => node.widgets.find(widget => widget.name === name);
const buttons = node => node.zuraGalleryRoot.querySelectorAll('button');
const byText = (node, text) => buttons(node).find(button => button.textContent === text);
const byAria = (node, text) => buttons(node).find(button => button.getAttribute('aria-label') === text);
const timeline = node => node.zuraGalleryRoot.querySelectorAll('div').find(el => el.getAttribute('aria-label') === 'Shot timeline');

const empty = create({ zura_single_camera: true });
assert.match(empty.zuraGalleryRoot.textContent, /Choose one camera/);
assert.match(empty.zuraGalleryRoot.textContent, /Plan angles.*run.*whole clip.*Render video.*run/s);
assert.doesNotMatch(empty.zuraGalleryRoot.textContent, /frames per shot|Pick a shot/);

const single = create({ zura_single_camera: true }, 1);
assert.match(single.zuraGalleryRoot.textContent, /Choose one camera/);
assert.match(single.zuraGalleryRoot.textContent, /whole clip/);
assert.doesNotMatch(single.zuraGalleryRoot.textContent, /Shot 1|selected shot|for this shot|camera changes|multicam/);
assert.equal(timeline(single), undefined);
assert.equal(byText(single, 'Use this camera for all shots'), undefined);
assert.equal(byText(single, 'Next shot →'), undefined);
assert.equal(single.zuraGalleryRoot.querySelectorAll('[data-angle]').length, 9);
assert.equal(single.zuraGalleryRoot.style.height, '640px');
assert.equal(single.domOptions.getMinHeight(), 640);
assert.equal(single.domOptions.getMaxHeight(), 640);
assert.equal(single.sizeCalls, 1, 'execution must not expand the node');
assert.ok(single.widgets.every(widget => widget.hidden), 'raw plan and look fields remain hidden');
assert.equal(byAria(single, 'Use source camera for the whole clip').getAttribute('aria-pressed'), 'true');

let stopCount = 0;
const camera = byAria(single, 'Use Camera 5 for the whole clip');
camera.onkeydown({ stopPropagation: () => stopCount++ });
camera.focus();
assert.equal(stopCount, 1);
assert.equal(camera.style.outline, '2px solid #fff');
camera.onblur();
assert.equal(camera.style.outline, '');
camera.onclick();
assert.equal(field(single, 'shot_choices').value, '5');
assert.equal(camera.getAttribute('aria-pressed'), 'true');
assert.equal(single.stageWidget.value, '1 · Plan angles', 'choosing a camera must not render');
const prompt = single.zuraGalleryRoot.querySelector('textarea');
assert.equal(prompt.disabled, false);
assert.equal(prompt.getAttribute('aria-label'), 'Additional prompt for the whole clip');
prompt.value = 'Keep the movement subtle.';
prompt.oninput();
assert.deepEqual(JSON.parse(field(single, 'shot_prompts').value), ['Keep the movement subtle.']);
byAria(single, 'Use Camera 8 for the whole clip').onclick();
assert.equal(prompt.value, 'Keep the movement subtle.', 'camera selection retains the optional prompt');
byAria(single, 'Use source camera for the whole clip').onclick();
assert.equal(prompt.disabled, true);
assert.equal(byText(single, 'Render video →').disabled, true, 'source with a prompt keeps the existing render protection');
byText(single, 'Clear prompt').onclick();
assert.equal(byText(single, 'Render video →').disabled, false, 'clearing the prompt refreshes render readiness');
const render = byAria(single, 'Switch workflow stage to Render video');
render.onclick();
assert.equal(single.stageWidget.value, '2 · Render multicam', 'backend enum remains unchanged');
assert.deepEqual(single.stageChanges, ['2 · Render multicam']);
assert.match(single.zuraGalleryRoot.textContent, /Press ComfyUI Run to render the video/);
byText(single, '← Back to angle planning').onclick();
assert.equal(single.stageWidget.value, '1 · Plan angles');
single.zuraGalleryRoot.scrollTop = 120;
single.onExecuted({ zura_angle_gallery: [metadata(1)] });
assert.equal(single.zuraGalleryRoot.scrollTop, 120);
assert.equal(single.sizeCalls, 1);
const saved = {};
single.onSerialize(saved);
assert.equal(saved.properties.zura_angle_gallery_v3.shot_count, 1);
const restored = create();
restored.onConfigure({ properties: { ...saved.properties, zura_single_camera: true } });
assert.match(restored.zuraGalleryRoot.textContent, /Choose one camera/);
assert.equal(timeline(restored), undefined);

// A one-shot multicam workflow stays multicam unless explicitly opted in.
for (const properties of [{}, { zura_single_camera: 'true' }]) {
  const normal = create(properties, 1);
  assert.match(normal.zuraGalleryRoot.textContent, /Plan your shots/);
  assert.ok(timeline(normal));
  assert.ok(byText(normal, 'Use this camera for all shots'));
  assert.ok(byAria(normal, 'Switch workflow stage to Render multicam'));
}
const multicam = create({}, 3);
assert.equal(timeline(multicam).children.length, 3);
byText(multicam, 'Next shot →').onclick();
assert.equal(multicam.zuraSelectedShot, 1);
byAria(multicam, 'Use Camera 4 for the selected shot').onclick();
assert.equal(field(multicam, 'shot_choices').value, '0,4,0');
byText(multicam, 'Use this camera for all shots').onclick();
assert.equal(field(multicam, 'shot_choices').value, '4,4,4');
byText(multicam, 'Continue to Render →').onclick();
assert.equal(multicam.stageWidget.value, '2 · Render multicam');

const stale = create({ zura_single_camera: true }, 3);
assert.equal(timeline(stale).children.length, 3, 'incorrect metadata must not be hidden as a single camera');
assert.match(stale.zuraGalleryRoot.textContent, /Single-camera mode needs one shot covering the whole clip/);
assert.doesNotMatch(stale.zuraGalleryRoot.textContent, /Choose one camera/);
assert.ok(stale.zuraGalleryRoot.querySelectorAll('div').find(el => el.getAttribute('role') === 'alert'));
const blocked = byText(stale, 'Continue to Render →');
assert.equal(blocked.disabled, true);
blocked.onclick();
assert.equal(stale.stageWidget.value, '1 · Plan angles');
stale.stageWidget.value = '2 · Render multicam';
stale.onExecuted({ zura_angle_gallery: [metadata(3)] });
byText(stale, '← Back to angle planning').onclick();
assert.equal(stale.stageWidget.value, '1 · Plan angles', 'an incorrect render-stage plan can return to planning');
stale.onExecuted({ zura_angle_gallery: [metadata(1)] });
assert.match(stale.zuraGalleryRoot.textContent, /Choose one camera/);
assert.equal(byText(stale, 'Render video →').disabled, false);

console.log('Single-camera gallery renders whole-clip controls, preserves prompts and stages, guards stale plans, and leaves multicam unchanged.');
