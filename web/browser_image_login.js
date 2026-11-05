import { app } from '/scripts/app.js';
import { api } from '/scripts/api.js';

app.registerExtension({
  name: 'Zura.BrowserImageLogin',
  beforeRegisterNodeDef(nodeType, nodeData) {
    const providers = { ZuraChatGPTImage: ['chatgpt', 'Sign in to ChatGPT'], ZuraGeminiImage: ['gemini', 'Sign in to Gemini'] };
    const item = providers[nodeData.name];
    if (!item) return;
    const previous = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = previous?.apply(this, args);
      let removed = false;
      let refresh;
      let status = {}, choices = [], changed = false;
      const browser = this.addWidget('combo', 'Sign-in browser', '', async () => {
        changed = true;
        widget.name = item[1];
        this.setDirtyCanvas(true, true);
        try {
          const response = await api.fetchApi('/zura/browser_image_cancel', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({provider: item[0]})
          });
          if (!response.ok) throw new Error('Could not disconnect the previous account. Reconnect before generating.');
          status = {...status, state: 'disconnected'};
        } catch (err) { alert(`Zura sign-in: ${err.message}`); }
      }, {values: [], serialize: false});
      const widget = this.addWidget('button', item[1], null, async () => {
        try {
          const pending = ['setting_up', 'checking', 'signing_in'].includes(status.state);
          const selected = choices.find(choice => choice.name === browser.value)?.id;
          const response = await api.fetchApi(pending ? '/zura/browser_image_cancel' : '/zura/browser_image_login', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({provider: item[0], ...(!pending && selected ? {browser: selected} : {})})
          });
          const body = await response.json();
          if (!response.ok) throw new Error(body.error || 'Unable to start sign-in.');
          widget.name = pending ? 'Cancelling connection…' : 'Connecting your browser session…';
          changed = false;
          this.setDirtyCanvas(true, true);
          await refresh();
        } catch (err) { alert(`Zura sign-in: ${err.message}`); }
      }, {serialize: false});
      this.widgets.splice(this.widgets.indexOf(widget), 1);
      this.widgets.unshift(widget);
      refresh = async () => {
        if (removed) return;
        try {
          const response = await api.fetchApi(`/zura/browser_image_status?provider=${item[0]}`);
          if (!response.ok) return;
          status = await response.json();
          if (removed) return;
          choices = status.browsers || [];
          browser.options.values = choices.map(choice => choice.name);
          const selected = choices.find(choice => choice.id === status.browser);
          if (!changed && selected) browser.value = selected.name;
          else if (!choices.some(choice => choice.name === browser.value)) browser.value = choices[0]?.name || '';
          widget.name = changed ? item[1] : status.state === 'connected' ? `Connected · ${item[0] === 'chatgpt' ? 'ChatGPT' : 'Gemini'} (reconnect)`
            : ['setting_up', 'checking', 'signing_in'].includes(status.state) ? 'Cancel connection'
            : status.state === 'error' ? `${item[1]} · retry` : item[1];
          widget.tooltip = status.message;
          browser.tooltip = 'Choose a browser installed on the computer running ComfyUI. Safari is available on macOS.';
          this.setDirtyCanvas(true, true);
        } catch (_) {}
      };
      const interval = setInterval(refresh, 3000);
      const onRemoved = this.onRemoved;
      this.onRemoved = function (...args) { removed = true; clearInterval(interval); return onRemoved?.apply(this, args); };
      refresh();
      this.setSize(this.computeSize());
      return result;
    };
  }
});
