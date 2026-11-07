import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = fs.existsSync(path.join(directory, 'browser_login.js'))
  ? path.join(directory, 'browser_login.js')
  : path.join(directory, '../web/browser_image_login.js');
const source = fs.readFileSync(sourcePath, 'utf8').replace(/^import .*;\r?\n/gm, '');
let extension;
const calls = [];
let statusReply = { state: 'connected', message: 'Live session accepted', browser: 'chrome', browsers: [{id:'chrome',name:'Chrome'},{id:'safari',name:'Safari'}] };
const app = { registerExtension(value) { extension = value; } };
const api = { async fetchApi(url, options) {
  calls.push({ url, options });
  return { ok: true, async json() { return url.includes('_status')
    ? statusReply : { ok: true }; } };
} };
const oldInterval = globalThis.setInterval;
const oldClear = globalThis.clearInterval;
let cleared = 0;
globalThis.setInterval = () => 7;
globalThis.clearInterval = value => { assert.equal(value, 7); cleared++; };
try {
  new Function('app', 'api', source)(app, api);
  for (const name of ['ZuraChatGPTImage', 'ZuraGeminiImage']) {
    class Node {
      onNodeCreated() { this.widgets = [{ name: 'prompt', value: 'keep this prompt', options: {} }]; }
      addWidget(type, name, value, callback, options) {
        const widget = { type, name, value, callback, options }; this.widgets.push(widget); return widget;
      }
      setDirtyCanvas() {}
      computeSize() { return [380, 400]; }
      setSize() {}
    }
    extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    node.onNodeCreated();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(node.widgets[0].type, 'button');
    assert.equal(node.widgets[0].options.serialize, false);
    assert.match(node.widgets[0].name, /^Connected/);
    assert.deepEqual(node.widgets.filter(w => w.options.serialize !== false).map(w => w.value), ['keep this prompt']);
    const browser = node.widgets.find(widget => widget.type === 'combo');
    assert.deepEqual(browser.options.values, ['Chrome', 'Safari']);
    browser.value = 'Safari'; await browser.callback();
    assert.equal(calls.findLast(c => c.options?.method === 'POST').url, '/zura/browser_image_cancel');
    await node.widgets[0].callback();
    assert.equal(calls.findLast(c => c.options?.method === 'POST').url, '/zura/browser_image_login');
    assert.equal(JSON.parse(calls.findLast(c => c.options?.method === 'POST').options.body).browser, 'safari');
    node.onRemoved();
    statusReply = {state:'disconnected', browser:'', browsers:[{id:'firefox',name:'Firefox'},{id:'chrome',name:'Chrome'}]};
    const fresh = new Node();
    fresh.onNodeCreated();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(fresh.widgets.find(w => w.type === 'combo').value, 'Firefox', 'A new connection uses the system-default browser returned first by the host');
    await fresh.widgets[0].callback();
    assert.equal(JSON.parse(calls.findLast(c => c.options?.method === 'POST').options.body).browser, 'firefox');
    fresh.onRemoved();
    statusReply = { state: 'connected', message: 'Live session accepted', browser: 'chrome', browsers: [{id:'chrome',name:'Chrome'},{id:'safari',name:'Safari'}] };
  }
  assert.equal(cleared, 4);
  console.log('Both login buttons: top position, connection action, workflow values and timer cleanup passed.');
} finally {
  globalThis.setInterval = oldInterval;
  globalThis.clearInterval = oldClear;
}
