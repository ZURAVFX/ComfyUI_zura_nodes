import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const extensions = [];
const source = fs.readFileSync(new URL('../web/anyangle_english.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const context = { app: { registerExtension: value => extensions.push(value) }, URL };
vm.runInNewContext(source, context);
const { translateText, localizeTree, isAnyAngleFrame, cameraApplied, updateLaunchButton } = context;

assert.equal(translateText('  应用到节点\n'), '  Apply to node\n');
assert.equal(translateText('机位草稿 · 尚未应用'), 'Camera draft · click Apply to node to use this view');
assert.equal(translateText('My 原图 studio.png'), 'My 原图 studio.png');
assert.equal(translateText('Custom unknown text'), 'Custom unknown text');
assert.equal(translateText(null), null);
assert.equal(isAnyAngleFrame({ src: 'http://localhost:8188/extensions/ComfyUI-AnyAngle-Studio-T8/editor/index.html?v=1' }, 'http://localhost:8188'), true);
assert.equal(isAnyAngleFrame({ src: '/extensions/Comfyui-Qwen-Image-2.1-MultiAngle-T8/editor/index.html' }, 'http://localhost:8188'), true);
assert.equal(isAnyAngleFrame({ src: 'https://example.com/extensions/AnyAngle/editor/index.html' }, 'http://localhost:8188'), false);
assert.equal(isAnyAngleFrame({ src: '/extensions/other/editor/index.html' }, 'http://localhost:8188'), false);

// Exercise text and attribute mutation boundaries without depending on a GPU,
// browser package, or the third-party node being installed on CI.
function textNode(value, protectedParent = false) {
  let writes = 0;
  return {
    nodeType: 3, parentElement: { closest: selector => selector === '#asset-label' ? false : protectedParent },
    get nodeValue() { return value; },
    set nodeValue(next) { value = next; writes++; },
    get writes() { return writes; },
  };
}
const label = textNode('应用到节点');
localizeTree(label);
assert.equal(label.nodeValue, 'Apply to node');
localizeTree(label);
assert.equal(label.writes, 1, 'already translated text must not trigger another MutationObserver event');
const prompt = textNode('原图', true);
localizeTree(prompt);
assert.equal(prompt.nodeValue, '原图', 'prompt previews and saved names remain untouched');
const assetStatus = textNode('等待原图重建');
assetStatus.parentElement.closest = selector => selector === '#asset-label';
localizeTree(assetStatus);
assert.equal(assetStatus.nodeValue, 'Waiting for reconstruction');
const assetFilename = textNode('原图');
assetFilename.parentElement.closest = selector => selector === '#asset-label';
localizeTree(assetFilename);
assert.equal(assetFilename.nodeValue, '原图', 'asset filenames stay unchanged even when they match another UI label');
assert.equal(translateText('互动编排与道具'), 'Interactions and props');
assert.equal(translateText('实际输出 · image_2 · 640 × 360'), 'Actual output · image_2 · 640 × 360');
assert.equal(translateText('实际输出 · image_2 · 640 × 360 filename.png'), '实际输出 · image_2 · 640 × 360 filename.png');
assert.equal(translateText('预览即将输出到 image_2 的实际引导图。'), 'Actual guide preview for image_2.');
assert.equal(translateText('原图 → image_1；当前引导图 → image_2。更改顺序后请对应调整编码器连线。'), 'Source → image_1; guide → image_2. If you change the order, update the encoder connections to match.');
const attributes = new Map([['placeholder', '描述人物、场景、服装和风格'], ['value', '原图']]);
const input = {
  nodeType: 1, childNodes: [prompt], value: '原图',
  matches: selector => selector.includes('textarea,input'),
  getAttribute: name => attributes.get(name) ?? null,
  setAttribute: (name, value) => attributes.set(name, value),
};
localizeTree(input);
assert.equal(attributes.get('placeholder'), 'Describe the person, setting, clothing and style');
assert.equal(attributes.get('value'), '原图');
assert.equal(input.value, '原图');
assert.equal(prompt.writes, 0);

const node = { widgets: [{ name: 'snapshot', value: '' }, { type: 'button', name: '打开 AnyAngle Studio', callback() {} }] };
const callback = node.widgets[1].callback;
updateLaunchButton(node);
assert.match(node.widgets[1].label, /apply a camera first/);
assert.equal(node.widgets[1].name, '打开 AnyAngle Studio', 'upstream widget name remains stable');
assert.equal(cameraApplied(node), false);
const token = JSON.stringify({ version: 1, id: 'a'.repeat(64) });
node.widgets[0].value = token;
updateLaunchButton(node);
assert.match(node.widgets[1].label, /camera applied/);
assert.equal(node.widgets[0].value, token, 'localisation never rewrites or creates a snapshot');
assert.equal(node.widgets[1].callback, callback, 'the upstream studio launch callback is retained');
assert.equal(node.widgets[1].options.serialize, false);
assert.equal(node.widgets[1].serialize, false, 'modern frontend must also omit the launcher value');
node.widgets[0].value = '{"version":1,"id":"bad"}';
assert.equal(cameraApplied(node), false);
node.widgets[0].value = 'invalid JSON';
assert.equal(cameraApplied(node), false);
assert.equal(extensions[0].name, 'Zura.AnyAngleEnglish');
console.log('AnyAngle English: scoped frames, protected values, idempotent translations, and camera-apply state pass.');
