import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the shipped extension with a minimal ComfyUI node, without a DOM or
// GPU. This guards the saved-workflow corruption shown in the user's report.
const extensions = [];
const source = fs.readFileSync(new URL('../web/multicam_angle_gallery.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const context = { app: { registerExtension: extension => extensions.push(extension) }, api: {} };
vm.runInNewContext(source, context);
const definitions = [
  ['shot_plan', ['STRING', {}]],
  ['look_enabled', ['BOOLEAN', {}]],
  ['look_prompt', ['STRING', {}]],
  ['width', ['INT', { min: 128, max: 2048 }]],
  ['height', ['INT', { min: 128, max: 2048 }]],
  ['seed', ['INT', { min: 0, max: 0xffffffffffffffff, control_after_generate: false }]],
  ['klein_seed', ['INT', { min: 0, max: 0xffffffffffffffff, control_after_generate: false }]],
  ['wan_steps', ['INT', { min: 1, max: 60 }]],
  ['klein_steps', ['INT', { min: 1, max: 60 }]],
  ['prompt_preset', [['Custom look', 'Approved grey studio (reference clip)'], {}]],
];
const raw = ['', true, 'Grey studio', 960, 544, 314159, 33874211, 4, 4, 'Custom look'];
const canonical = JSON.parse(JSON.stringify(context.decodeSavedWidgetValues(definitions, raw)));
assert.equal(canonical.klein_seed, 33874211);
assert.equal(canonical.wan_steps, 4);
assert.equal(canonical.prompt_preset, 'Custom look');
const controlled = [...raw.slice(0, 6), 'fixed', ...raw.slice(6)];
assert.deepEqual(JSON.parse(JSON.stringify(context.decodeSavedWidgetValues(definitions, controlled))), canonical);
const bothControlled = [...raw.slice(0, 6), 'randomize', raw[6], 'fixed', ...raw.slice(7)];
assert.deepEqual(JSON.parse(JSON.stringify(context.decodeSavedWidgetValues(definitions, bothControlled))), canonical);
assert.equal(context.decodeSavedWidgetValues(definitions, [...raw.slice(0, 8), NaN, 'Custom look']), null);
assert.equal(context.decodeSavedWidgetValues(definitions, [...raw, 'unexpected']), null);

class Node {
  constructor() { this.widgets = definitions.map(([name]) => ({ name, value: 'shifted' })); }
  onConfigure() { this.configured = true; }
  onSerialize() { this.serialized = true; }
}
extensions[0].beforeRegisterNodeDef(Node, {
  name: 'ZuraCleanMulticamV4', input: { required: Object.fromEntries(definitions) },
});
const node = new Node();
node.onConfigure({ widgets_values: raw, widgets_values_named: { wan_steps: 8 } });
assert.equal(node.configured, true);
assert.equal(node.widgets.find(widget => widget.name === 'wan_steps').value, 4,
  'stale legacy named metadata must not overwrite valid positional values');
const saved = {};
node.onSerialize(saved);
assert.equal(node.serialized, true);
assert.deepEqual(JSON.parse(JSON.stringify(saved.properties.zura_widget_values)), canonical);
const second = new Node();
second.onConfigure({ widgets_values: controlled, properties: { zura_widget_values: { ...canonical, wan_steps: 16 } } });
assert.equal(second.widgets.find(widget => widget.name === 'wan_steps').value, 16,
  'the current named snapshot must win over historical widget order');
const singleDefinitions = [
  ['seed', ['INT', { min: 0, max: 0xffffffffffffffff, control_after_generate: false }]],
  ['steps', ['INT', { min: 1, max: 60 }]],
  ['prompt', ['STRING', {}]],
];
class SingleAngleNode {
  constructor() { this.widgets = singleDefinitions.map(([name]) => ({ name, value: 'shifted' })); }
}
extensions[0].beforeRegisterNodeDef(SingleAngleNode, {
  name: 'ZuraH3SingleAngle', input: { required: Object.fromEntries(singleDefinitions) },
});
const oldSingle = new SingleAngleNode();
oldSingle.onConfigure({ widgets_values: [42, 'fixed', 16, 'Keep original performance.'] });
assert.deepEqual(oldSingle.widgets.map(w => w.value), [42, 16, 'Keep original performance.'],
  'v1.2.1 single-camera workflows must recover steps and prompt after removing the seed control');
const staleSingle = new SingleAngleNode();
staleSingle.onConfigure({
  widgets_values: [42, 'fixed', 16, 'Keep original performance.'],
  properties: { zura_widget_values: { seed: 99, steps: 'fixed', prompt: 16 } },
});
assert.deepEqual(staleSingle.widgets.map(w => w.value), [99, 16, 'Keep original performance.'],
  'invalid named values must not suppress positional recovery; valid named values still win');
const partialSingle = new SingleAngleNode();
partialSingle.onConfigure({
  widgets_values: [42, 'fixed', 16, 'Keep original performance.'],
  properties: { zura_widget_values: { steps: 20 } },
});
assert.deepEqual(partialSingle.widgets.map(w => w.value), [42, 20, 'Keep original performance.']);
const savedSingle = {};
oldSingle.onSerialize(savedSingle);
const reloadedSingle = new SingleAngleNode();
reloadedSingle.onConfigure({ properties: savedSingle.properties });
assert.deepEqual(reloadedSingle.widgets.map(w => w.value), [42, 16, 'Keep original performance.']);
console.log('Multicam widgets reload without seed-control drift; named values survive, stale metadata and invalid arrays do not override them.');
