// Shared by Image, Video, HDR, Paintout, Inpaint, Ripple and Watermark setup.
const el=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
export class ModelAccess {
  constructor(host,request,retry){
    this.window=host.ownerDocument?.defaultView||globalThis.window;this.request=request;this.retry=retry;this.root=el('details');this.root.className='zura-model-access';this.root.hidden=true;
    this.root.innerHTML='<summary>Hugging Face access</summary><p>Sign in, allow Studio to download approved gated models, then accept the publisher’s terms below.</p><button type="button" data-access-browser disabled>Sign in with Hugging Face</button><a data-access-resume hidden target="_blank" rel="noopener noreferrer">Open sign-in window</a><p data-access-code hidden></p><button type="button" data-access-cancel hidden>Cancel sign-in</button><label class="zura-access-remember"><input data-access-remember type="checkbox" />Remember on this computer</label><div data-access-terms></div><p data-access-status role="status" aria-live="polite"></p><details data-access-form><summary>Advanced: use a read token</summary><a data-access-create target="_blank" rel="noopener noreferrer">Create a read token on Hugging Face</a><label>Read token<input data-access-token type="password" autocomplete="off" spellcheck="false" placeholder="hf_…" /></label><p>Use this only if browser sign-in is unavailable. Credentials stay on the ComfyUI computer.</p><button type="button" data-access-connect>Connect Hugging Face</button></details><div class="zura-access-actions"><button type="button" data-access-retry>Continue download</button><button type="button" data-access-disconnect hidden>Disconnect</button></div>';
    host.append(this.root);this.$=key=>this.root.querySelector(`[data-access-${key}]`);
    this.$('browser').onclick=()=>this.startBrowser();this.$('cancel').onclick=()=>this.cancelBrowser();
    this.$('create').href='https://huggingface.co/settings/tokens/new?tokenType=read';
    this.$('connect').onclick=()=>this.connect();this.$('disconnect').onclick=()=>this.disconnect();this.$('retry').onclick=()=>this.retry?.();
    this.$('token').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();void this.connect();}});
    this.onTermsReturn=async()=>{this.window?.removeEventListener('focus',this.onTermsReturn);if(this.busy)return;try{const state=await this.request('/model-access');this.show(state);if(state.connected)await this.retry?.();}catch{this.$('status').textContent='Could not resume the download. Choose Continue download to try again.';}};
    this.root.ontoggle=()=>{if(this.root.open)void this.load();else this.$('token').value='';};
  }
  setFiles(files,failed){
    const signature=JSON.stringify(files.filter(file=>!file.installed&&file.gated).map(file=>[file.repo,file.revision,file.remote_path]));
    if(signature!==this.fileSignature){this.blocked=null;this.fileSignature=signature;}
    failed=failed||this.blocked;
    this.root.hidden=!this.busy&&!files.some(file=>!file.installed&&file.gated)&&!failed;
    this.$('terms').replaceChildren();
    const repos=[...new Set(files.filter(file=>!file.installed&&file.gated).map(file=>file.repo||(/^https:\/\/huggingface\.co\/([\w.-]+\/[\w.-]+)/.exec(file.model_card||'')||[])[1]).filter(Boolean))];
    for(const repo of failed?.access_repos||[failed?.access_repo])if(repo&&!repos.includes(repo))repos.unshift(repo);
    for(const repo of repos){if(!/^[\w.-]+\/[\w.-]+$/.test(repo))continue;const link=el('a',`Review terms · ${repo}`);link.href=`https://huggingface.co/${repo}`;link.target='_blank';link.rel='noopener noreferrer';link.onclick=event=>{this.window?.removeEventListener('focus',this.onTermsReturn);this.window?.addEventListener('focus',this.onTermsReturn,{once:true});const popup=this.window?.open?.('about:blank','_blank','popup,width=960,height=760');if(popup){popup.opener=null;popup.location.href=link.href;event.preventDefault();}};this.$('terms').append(link);}
    if(failed){this.root.open=true;this.$('status').textContent=failed.auth_required===false?'Access could not be checked. Check your connection and try Continue download. A model may be unavailable at its publisher.':failed.access_reason==='connect'?'Sign in with Hugging Face, review the model terms below, then continue the download.':'Review the model terms with the connected account. Return here to continue the download. Approval may be required by the publisher.';}
  }
  async load(){
    if(this.busy)return;
    try{this.show(await this.request('/model-access'));}catch{this.$('status').textContent='Could not check the connection. You can connect below or download the files in your browser.';}
  }
  async check(files){
    const gated=files.filter(file=>!file.installed&&file.gated);
    if(!gated.length)return true;
    this.setFiles(files);this.root.hidden=false;this.root.open=true;
    this.$('status').textContent='Checking access before downloading models…';
    try{
      const result=await this.request('/model-access',{action:'check_files',files:gated.map(({repo,revision,remote_path})=>({repo,revision,remote_path}))});
      if(result.allowed===true){this.blocked=null;return true;}
      this.blocked=result;this.setFiles(files,result);
      await this.load();
      this.$('status').textContent=result.auth_required?(result.access_reason==='connect'?'1. Sign in with Hugging Face. 2. Open the model terms below and accept or request access. 3. Continue download.':'Open the model terms below with the connected account, then continue. If approval is pending, return after the publisher grants access.'):'Access could not be checked. Check your connection and try Continue download. A model may be unavailable at its publisher.';
    }catch{this.$('status').textContent='Could not check model access. Check your connection, update Zura Studio if needed, and try Continue download.';}
    return false;
  }
  show(state){
    this.$('browser').disabled=state.browser_signin_available!==true;
    this.$('browser').textContent=state.browser_signin_available===true?'Sign in with Hugging Face':'Restart ComfyUI for browser sign-in';
    this.$('status').textContent=state.connected?state.name?`Connected as ${state.name}${state.remembered?' · remembered on this computer':''}. Model terms still need to be accepted for this account.`:'Using this computer’s Hugging Face connection. Review the model terms, then retry.':'Sign in through the browser. Studio will continue the download after you approve access.';
    this.$('browser').hidden=!!state.connected;this.$('remember').closest('label').hidden=!!state.connected;
    this.$('disconnect').hidden=!state.connected;this.$('form').hidden=!!state.connected;
    // Let people replace an expired or insufficient cached credential.
    if(state.connected){this.change??=el('button','Switch account');this.change.type='button';this.change.disabled=state.browser_signin_available!==true;this.change.title=state.browser_signin_available===true?'Sign in with a different Hugging Face account':'Restart ComfyUI to enable browser sign-in';this.change.onclick=()=>this.startBrowser();this.$('disconnect').parentNode.append(this.change);}else this.change?.remove();
  }
  async startBrowser(){
    if(this.busy||this.disposed)return;
    const attempt={};this.attempt=attempt;
    const popup=this.window?.open?.('about:blank','_blank','popup,width=620,height=760');
    if(popup)popup.opener=null;
    this.busy=true;for(const id of ['browser','retry','connect','remember'])this.$(id).disabled=true;this.$('cancel').hidden=false;this.$('status').textContent='Opening secure browser sign-in…';
    try{
      const login=await this.request('/model-access',{action:'browser_start',remember:!!this.$('remember').checked});
      if(this.attempt!==attempt||this.disposed){popup?.close();await this.request('/model-access',{action:'browser_cancel',id:login.id});return;}
      const url=new URL(login.url);if(url.origin!=='https://huggingface.co')throw Error('Unexpected sign-in address.');
      this.login=login;this.$('resume').href=url.href;this.$('resume').hidden=false;
      this.$('code').textContent=login.code?`Enter this code if asked: ${login.code}`:'';this.$('code').hidden=!login.code;
      this.$('cancel').hidden=false;if(popup)popup.location.href=url.href;
      this.$('status').textContent='Complete sign-in in the browser. This page will continue automatically.';
      this.loginTimer=setTimeout(()=>this.pollBrowser(),Math.max(5,login.interval||5)*1000);
    }catch(error){popup?.close();if(this.attempt!==attempt||this.disposed)return;this.finishBrowser();this.$('status').textContent=error.message||'Could not start browser sign-in.';}
  }
  async pollBrowser(){
    const login=this.login;if(!login)return;
    try{
      const state=await this.request('/model-access',{action:'browser_poll',id:login.id});
      if(this.login!==login)return;
      if(state.phase==='connected'){
        this.finishBrowser();this.show(state);try{await this.retry?.();}catch{this.$('status').textContent='Connected. The download could not resume. Choose Continue download to try again.';}return;
      }
      this.loginTimer=setTimeout(()=>this.pollBrowser(),Math.max(5,state.interval||5)*1000);
    }catch(error){if(this.login!==login)return;this.finishBrowser();this.$('status').textContent=error.message||'Sign-in could not complete. Try again.';}
  }
  finishBrowser(){this.attempt=null;clearTimeout(this.loginTimer);this.login=null;this.busy=false;for(const id of ['browser','retry','connect','remember'])this.$(id).disabled=false;for(const id of ['resume','code','cancel'])this.$(id).hidden=true;}
  async cancelBrowser(){const login=this.login;this.finishBrowser();this.$('status').textContent='Sign-in cancelled. Your models are unchanged.';if(login)try{await this.request('/model-access',{action:'browser_cancel',id:login.id});}catch{}}
  dispose(){this.disposed=true;this.window?.removeEventListener('focus',this.onTermsReturn);void this.cancelBrowser();}
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
