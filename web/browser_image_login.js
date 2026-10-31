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
      const widget = this.addWidget('button', item[1], null, async () => {
        try {
          const response = await api.fetchApi('/zura/browser_image_login', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({provider: item[0]})
          });
          const body = await response.json();
          if (!response.ok) throw new Error(body.error || 'Unable to start sign-in.');
          widget.name = 'Connecting your Firefox session…';
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
          const status = await response.json();
          if (removed) return;
          widget.name = status.state === 'connected' ? `Connected · ${item[0] === 'chatgpt' ? 'ChatGPT' : 'Gemini'} (reconnect)`
            : status.state === 'setting_up' ? 'Preparing connection…'
            : status.state === 'checking' ? 'Checking Firefox session…'
            : status.state === 'signing_in' ? 'Complete sign-in in the browser…'
            : status.state === 'error' ? `${item[1]} · retry` : item[1];
          widget.tooltip = status.message;
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
