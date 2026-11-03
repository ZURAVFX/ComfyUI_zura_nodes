// Shared by Image, Video, HDR, Paintout, Inpaint, Ripple and Watermark setup.
const el=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
export class ModelAccess {
  constructor(host,request,retry){
    this.request=request;this.retry=retry;this.root=el('details');this.root.className='zura-model-access';this.root.hidden=true;
    this.root.innerHTML='<summary>Hugging Face access</summary><p>Some publishers require you to accept their model terms. Use the same account for the terms and the connection below.</p><div data-access-terms></div><p data-access-status role="status" aria-live="polite"></p><div data-access-form><a data-access-create target="_blank" rel="noopener noreferrer">Create a read token on Hugging Face</a><label>Read token<input data-access-token type="password" autocomplete="off" spellcheck="false" placeholder="hf_…" /></label><label class="zura-access-remember"><input data-access-remember type="checkbox" />Remember on this computer</label><p>Enable read access to public gated models you have been approved for. The connection is shared across Studio. Your token stays on the ComfyUI computer.</p><button type="button" data-access-connect>Connect Hugging Face</button></div><div class="zura-access-actions"><button type="button" data-access-retry>Retry missing models</button><button type="button" data-access-disconnect hidden>Disconnect</button></div>';
    host.append(this.root);this.$=key=>this.root.querySelector(`[data-access-${key}]`);
    this.$('create').href='https://huggingface.co/settings/tokens/new?tokenType=read';
    this.$('connect').onclick=()=>this.connect();this.$('disconnect').onclick=()=>this.disconnect();this.$('retry').onclick=()=>this.retry?.();
    this.$('token').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();void this.connect();}});
    this.root.ontoggle=()=>{if(this.root.open)void this.load();else this.$('token').value='';};
  }
  setFiles(files,failed){
    this.root.hidden=!files.some(file=>!file.installed&&file.gated)&&!failed;
    this.$('terms').replaceChildren();
    const repos=[...new Set(files.filter(file=>!file.installed&&file.gated).map(file=>file.repo||(/^https:\/\/huggingface\.co\/([\w.-]+\/[\w.-]+)/.exec(file.model_card||'')||[])[1]).filter(Boolean))];
    if(failed?.access_repo&&!repos.includes(failed.access_repo))repos.unshift(failed.access_repo);
    for(const repo of repos){if(!/^[\w.-]+\/[\w.-]+$/.test(repo))continue;const link=el('a',`Review terms · ${repo}`);link.href=`https://huggingface.co/${repo}`;link.target='_blank';link.rel='noopener noreferrer';this.$('terms').append(link);}
    if(failed){this.root.open=true;this.$('status').textContent=failed.access_reason==='connect'?'Connect below, or use Download in browser beside the missing file.':'Review the model terms with the connected account, then retry. Approval may be required by the publisher.';}
  }
  async load(){
    if(this.busy)return;
    try{this.show(await this.request('/model-access'));}catch{this.$('status').textContent='Could not check the connection. You can connect below or download the files in your browser.';}
  }
  show(state){
    this.$('status').textContent=state.connected?state.name?`Connected as ${state.name}${state.remembered?' · remembered on this computer':''}. Model terms still need to be accepted for this account.`:'Using this computer’s Hugging Face connection. Review the model terms, then retry.':'Connect once to download gated models directly. Signing in on the website alone does not connect Studio.';
    this.$('disconnect').hidden=!state.connected;this.$('form').hidden=!!state.connected;
    // Let people replace an expired or insufficient cached credential.
    if(state.connected){this.change??=el('button','Use a different token');this.change.type='button';this.change.onclick=()=>{this.$('form').hidden=false;this.$('token').focus();};this.$('disconnect').parentNode.append(this.change);}else this.change?.remove();
  }
  async connect(){
    if(this.busy)return;const token=this.$('token').value.trim();if(!token){this.$('status').textContent='Create a read token using the link above, then paste it here.';this.$('token').focus();return;}
    this.busy=true;this.$('connect').disabled=true;this.$('retry').disabled=true;this.$('status').textContent='Checking Hugging Face access…';
    try{const state=await this.request('/model-access',{token,remember:this.$('remember').checked});this.show(state);this.$('token').value='';await this.retry?.();}
    catch(error){this.$('status').textContent=String(error.message||'Could not connect. Try again.').replace(/hf_[\w-]+/g,'[token hidden]');}
    finally{this.$('token').value='';this.busy=false;this.$('connect').disabled=false;this.$('retry').disabled=false;}
  }
  async disconnect(){if(this.busy)return;this.busy=true;try{this.show(await this.request('/model-access',{disconnect:true}));}catch{this.$('status').textContent='Could not disconnect. Try again.';}finally{this.busy=false;}}
}

// File is selected in the user's browser, including on Linux or remote ComfyUI.
// Stream the original bytes; the server verifies the pinned size and SHA-256.
export function importModelFile(base,modelId,file,progress){
  return new Promise((resolve,reject)=>{
    const input=el('input');input.type='file';input.accept='.safetensors,.pt,.pth,.ckpt,.onnx,.bin';
    input.oncancel=()=>resolve({cancelled:true});
    input.onchange=async()=>{
      const selected=input.files?.[0];if(!selected){resolve({cancelled:true});return;}
      if(selected.size!==Number(file.size_bytes)){reject(Error('Choose the completed download with the exact size shown beside this file.'));return;}
      const xhr=new XMLHttpRequest();xhr.open('POST',`${base}/import-file?${new URLSearchParams({model_id:modelId,filename:file.filename})}`);xhr.setRequestHeader('Content-Type','application/octet-stream');
      xhr.upload.onprogress=event=>progress?.(event.loaded,event.total||file.size_bytes);
      xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status>=400||data.error)throw Error(data.error||'Could not install this file.');resolve(data);}catch(error){reject(error);}};
      xhr.onerror=()=>reject(Error('Connection lost during import. Refresh model status before retrying.'));
      xhr.onabort=()=>reject(Error('Import cancelled. Your browser download is kept.'));
      xhr.send(selected);
    };
    input.click();
  });
}
