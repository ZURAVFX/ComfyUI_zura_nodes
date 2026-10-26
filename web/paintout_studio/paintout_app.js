import {app} from '/scripts/app.js';
import {api} from '/scripts/api.js';
import {getPaintoutWorkspace} from './paintout_shared.js';

let workspace, root, owner;
async function request(path, body) {
  const response = await api.fetchApi(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || `ComfyUI returned ${response.status}`);
  return data;
}
export async function openPaintout() {
  if (!root) {
    root = document.createElement('section');
    root.id = 'zura-paintout-app';
    root.dataset.workspace='paintout';root.dataset.theme=localStorage.getItem('zura-studio-theme')||'dark';
    const logo=new URL('./assets/zura-logo.png',import.meta.url).href;
    root.innerHTML = `<header class="gs-top"><div class="gs-brand"><img class="gs-zura-mark" src="${logo}" alt=""/><strong>Paintout Studio</strong></div><nav class="zc-nav" aria-label="Workspace"><button type="button" aria-current="page">Paintout</button></nav><div class="gs-top-actions"><span class="gs-status">Local processing</span><button type="button" class="zc-theme-toggle gs-quiet" data-action="theme">Light mode</button><button type="button" class="gs-quiet" data-action="close" aria-label="Close Paintout Studio">Back to graph</button></div></header><main></main>`;
    document.body.append(root);
    const close = () => {workspace?.close(); root.hidden = true;};
    root.querySelector('[data-action=close]').onclick = close;
    const theme=root.querySelector('[data-action=theme]');
    const updateTheme=()=>theme.textContent=root.dataset.theme==='light'?'Dark mode':'Light mode';
    theme.onclick=()=>{root.dataset.theme=root.dataset.theme==='light'?'dark':'light';localStorage.setItem('zura-studio-theme',root.dataset.theme);updateTheme();};updateTheme();
    owner = {root:root.querySelector('main'), api, app, fetch:request, studio:{close}};
  }
  workspace = getPaintoutWorkspace(owner);
  root.hidden = false;
  await workspace.open();
}
app.registerExtension({
  name:'Zura.Paintout.Studio',
  commands:[{id:'zura.paintout.open', label:'Open Paintout Studio', function:openPaintout}],
  menuCommands:[{path:['Zura'], commands:['zura.paintout.open']}],
  async setup() {
    for (const name of ['studio.css','studio_components.css','studio_create.css','studio_composer.css','studio_paintout.css','paintout_editor.css','paintout_app.css']) {
      const link = document.createElement('link'); link.rel='stylesheet'; link.href=new URL(name,import.meta.url).href; document.head.append(link);
    }
    if(new URLSearchParams(location.search).get('paintout')==='1') await openPaintout();
  }
});
