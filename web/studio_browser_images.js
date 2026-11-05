/** Existing Zura website-session nodes, with an explicit account connection. */
export class BrowserImageConnection {
  constructor(owner,host){
    this.owner=owner;this.host=host;this.states={};this.choices={};this.requests={};this.closed=false;
    host.className='zc-browser-connection';host.hidden=true;
    host.innerHTML='<div><strong>Browser sign-in · No API credits</strong><small role="status" aria-live="polite"></small><span>Uses your website account allowance. References are uploaded to the provider.</span></div><label class="zc-browser-choice">Browser<select aria-label="Browser for website sign-in"></select></label><button type="button" class="gs-quiet"></button>';
    this.button=host.querySelector('button');this.note=host.querySelector('small');
    this.select=host.querySelector('select');
    this.select.onchange=()=>{this.choices[this.provider]=this.select.value;this.owner.render();};
    this.button.onclick=()=>this.connect();
  }
  connected(model){const status=this.states[model?.provider];return !model?.provider||status?.state==='connected'&&(!status.browser||!this.choices[model.provider]||status.browser===this.choices[model.provider]);}
  sync(model){
    this.model=model;const provider=model?.provider;
    this.host.hidden=!provider;if(!provider){this.stop();return;}
    if(provider!==this.provider){this.stop();this.provider=provider;if(!this.closed)void this.refresh(provider);}
    const status=this.states[provider]||{},pending=['checking','setting_up','signing_in'].includes(status.state),label=model.name;
    const browsers=status.browsers||[],signature=JSON.stringify(browsers);
    if(this.browserSignature!==signature){this.browserSignature=signature;this.select.replaceChildren(...browsers.map(browser=>{const option=this.host.ownerDocument.createElement('option');option.value=browser.id;option.textContent=browser.name;return option;}));}
    const choice=this.choices[provider]||status.browser||browsers[0]?.id||'';
    this.choices[provider]=choice;for(const option of this.select.options)option.selected=option.value===choice;
    const busy=!!this.owner.job||!!this.owner.pendingSubmission||!!this.owner.submitting||!!this.owner.uploading;
    this.select.disabled=pending||!!this.connecting||busy;
    this.note.textContent=!model.ready?'Update Zura Nodes and restart ComfyUI to enable this browser image node.':status.browser&&status.browser!==choice?'Connect the selected browser to use that account.':status.message||'Choose a browser installed on the computer running ComfyUI. Safari is available on macOS.';
    this.button.textContent=pending?'Cancel connection':this.connected(model)?'Reconnect account':`Sign in to ${label.replace(' Image','')}`;
    this.button.disabled=!model.ready||!!this.connecting||busy||(!pending&&Array.isArray(status.browsers)&&!browsers.length);
    this.button.title='Uses your website account allowance. No Zura credits or paid developer API key.';
  }
  async connect(){
    const provider=this.model?.provider;if(!provider||this.connecting||!this.model.ready||this.owner.job||this.owner.pendingSubmission||this.owner.submitting||this.owner.uploading)return;
    const status=this.states[provider]||{},cancel=['checking','setting_up','signing_in'].includes(status.state),browser=this.choices[provider];
    this.requests[provider]=(this.requests[provider]||0)+1;
    this.connecting=true;this.states[provider]={...status,state:'checking',message:cancel?'Cancelling connection…':'Opening the selected browser…'};this.owner.render();
    try{await this.owner.fetch(cancel?'/zura/browser_image_cancel':'/zura/browser_image_login',{provider,...(!cancel&&browser?{browser}:{})});await this.refresh(provider);}
    catch(error){this.states[provider]={...status,state:'error',message:error.message};}
    finally{this.connecting=false;this.owner.render();}
  }
  async refresh(provider=this.provider){
    if(this.closed||!provider)return;
    const request=this.requests[provider]=(this.requests[provider]||0)+1;
    let status;
    try{status=await this.owner.fetch('/zura/browser_image_status?provider='+encodeURIComponent(provider));}
    catch{status={...this.states[provider],state:'error',message:'Connection status is unavailable. Restart ComfyUI, then reconnect.'};}
    if(this.requests[provider]!==request)return;
    this.states[provider]=status;
    if(this.closed||this.provider!==provider)return;
    this.owner.render();clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(provider),3000);
  }
  stop(){clearTimeout(this.timer);this.timer=null;this.provider=null;}
  close(){this.closed=true;this.stop();}
  open(){this.closed=false;this.stop();this.sync(this.model);}
}
