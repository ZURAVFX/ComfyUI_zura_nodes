// Paintout's canvas surface is mounted lazily. Do not expose its legacy DOM
// before the styles which replace that layout have finished loading.
const documents=new WeakMap();
const criticalStyles=['../studio.css','../studio_components.css','../studio_create.css','../studio_composer.css','./studio_paintout.css','./paintout_editor.css','./paintout_integrated.css','../studio_polish.css','../studio_plate_surface.css'].map(path=>new URL(path,import.meta.url).href);

export function stylesheetReady(href,doc,{timeout=15000}={}){
  let cache=documents.get(doc);if(!cache){cache=new Map();documents.set(doc,cache);}
  const previous=cache.get(href);if(previous?.link.isConnected)return previous.promise;
  const link=[...doc.querySelectorAll('link[rel="stylesheet"]')].find(item=>item.href===href)||doc.createElement('link');
  link.rel='stylesheet';link.href=href;
  if(link.sheet&&!link.disabled){const promise=Promise.resolve();cache.set(href,{link,promise});return promise;}
  let timer;
  const promise=new Promise((resolve,reject)=>{
    const clear=()=>{clearTimeout(timer);link.removeEventListener('load',loaded);link.removeEventListener('error',failed);};
    const loaded=()=>{clear();resolve();};
    const failed=()=>{clear();link.remove();reject(new Error('Editor stylesheet could not be loaded.'));};
    link.addEventListener('load',loaded,{once:true});link.addEventListener('error',failed,{once:true});
    timer=setTimeout(failed,timeout);timer.unref?.();
    if(!link.isConnected)(doc.head||doc.documentElement).append(link);
  });
  const entry={link,promise};cache.set(href,entry);
  promise.catch(()=>{if(cache.get(href)===entry)cache.delete(href);});
  return promise;
}

export const paintoutStylesReady=doc=>Promise.all(criticalStyles.map(href=>stylesheetReady(href,doc)));
const nextFrame=doc=>new Promise(resolve=>{const view=doc.defaultView;if(view?.requestAnimationFrame)view.requestAnimationFrame(resolve);else resolve();});

export class PaintoutStyleGate{
  constructor(page,{beforeReveal=()=>{}}={}){
    this.page=page;this.beforeReveal=beforeReveal;this.finished=false;this.pending=null;
    this.previous={visibility:page.style.visibility,minHeight:page.style.minHeight,position:page.style.position};
    page.style.visibility='hidden';page.style.minHeight='180px';page.style.position='relative';page.setAttribute('aria-busy','true');
    const doc=page.ownerDocument;this.status=doc.createElement('div');this.status.dataset.paintoutStyleStatus='';
    this.status.style.cssText='visibility:visible;position:absolute;inset:24px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;min-height:130px;font:inherit;color:inherit;text-align:center';
    this.text=doc.createElement('span');this.retry=doc.createElement('button');this.retry.type='button';this.retry.textContent='Retry opening editor';
    this.retry.style.cssText='font:inherit;color:inherit;background:transparent;border:1px solid currentColor;border-radius:6px;padding:8px 12px;cursor:pointer';
    this.retry.onclick=()=>void this.show();this.status.append(this.text,this.retry);
    const Observer=doc.defaultView?.MutationObserver;
    this.observer=Observer?new Observer(()=>this.syncStatus()):null;this.observer?.observe(page,{attributes:true,attributeFilter:['hidden']});
  }
  syncStatus(){this.status.hidden=this.finished||this.page.hidden;}
  show(){
    if(this.finished)return Promise.resolve(true);if(this.pending)return this.pending;
    if(this.status.parentNode!==this.page)this.page.append(this.status);
    this.text.textContent='Opening editor…';this.retry.hidden=true;this.status.setAttribute('role','status');this.page.setAttribute('aria-busy','true');this.syncStatus();
    this.pending=paintoutStylesReady(this.page.ownerDocument).then(()=>nextFrame(this.page.ownerDocument)).then(()=>{
      // Force fresh geometry while still invisible, then reveal in this frame.
      this.beforeReveal();this.finished=true;this.status.remove();this.observer?.disconnect();
      for(const [name,value]of Object.entries(this.previous))this.page.style[name]=value||'';
      this.page.removeAttribute('aria-busy');return true;
    }).catch(error=>{
      this.text.textContent='The editor could not finish opening. Check the connection and retry.';this.retry.hidden=false;this.status.setAttribute('role','alert');this.page.removeAttribute('aria-busy');this.syncStatus();
      console.warn('Zura editor presentation unavailable:',error.message);return false;
    }).finally(()=>{this.pending=null;});
    return this.pending;
  }
}
