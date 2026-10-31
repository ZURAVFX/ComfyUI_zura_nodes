/** Existing Zura website-session nodes, with an explicit account connection. */
export class BrowserImageConnection {
  constructor(owner,host){
    this.owner=owner;this.host=host;this.states={};this.closed=false;
    host.className='zc-browser-connection';host.hidden=true;
    host.innerHTML='<div><strong>Browser sign-in · No API credits</strong><small role="status" aria-live="polite"></small><span>Uses your website account allowance. References are uploaded to the provider.</span></div><button type="button" class="gs-quiet"></button>';
    this.button=host.querySelector('button');this.note=host.querySelector('small');
    this.button.onclick=()=>this.connect();
  }
  connected(model){return !model?.provider||this.states[model.provider]?.state==='connected';}
  sync(model){
    this.model=model;const provider=model?.provider;
    this.host.hidden=!provider;if(!provider){this.stop();return;}
    if(provider!==this.provider){this.stop();this.provider=provider;if(!this.closed)void this.refresh(provider);}
    const status=this.states[provider]||{},pending=['checking','setting_up','signing_in'].includes(status.state),label=model.name;
    this.note.textContent=!model.ready?'Update Zura Nodes and restart ComfyUI to enable this browser image node.':status.message||'Sign in using your normal Firefox account. Website plan limits apply; references are sent to the provider.';
    this.button.textContent=pending?'Connecting…':status.state==='connected'?'Reconnect account':`Sign in to ${label.replace(' Image','')}`;
    this.button.disabled=!model.ready||pending||!!this.connecting||!!this.owner.job||!!this.owner.pendingSubmission||!!this.owner.submitting||!!this.owner.uploading;
    this.button.title='Uses your website account allowance. No Zura credits or paid developer API key.';
  }
  async connect(){
    const provider=this.model?.provider;if(!provider||this.connecting||!this.model.ready||this.owner.job||this.owner.pendingSubmission||this.owner.submitting||this.owner.uploading)return;
    this.connecting=true;this.states[provider]={state:'checking',message:'Checking your signed-in Firefox session…'};this.owner.render();
    try{await this.owner.fetch('/zura/browser_image_login',{provider});await this.refresh(provider);}
    catch(error){this.states[provider]={state:'error',message:error.message};}
    finally{this.connecting=false;this.owner.render();}
  }
  async refresh(provider=this.provider){
    if(this.closed||!provider)return;
    try{this.states[provider]=await this.owner.fetch('/zura/browser_image_status?provider='+encodeURIComponent(provider));}
    catch{this.states[provider]={state:'error',message:'Connection status is unavailable. Restart ComfyUI, then reconnect.'};}
    if(this.closed||this.provider!==provider)return;
    this.owner.render();clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(provider),3000);
  }
  stop(){clearTimeout(this.timer);this.timer=null;this.provider=null;}
  close(){this.closed=true;this.stop();}
  open(){this.closed=false;this.stop();this.sync(this.model);}
}
