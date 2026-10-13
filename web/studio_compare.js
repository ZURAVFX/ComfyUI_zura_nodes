/** Source/render wipe. The rendered take owns the clock and soundtrack. */
export class ShotComparison {
  constructor(host) {
    this.host=host;
    host.innerHTML=`<div class="gs-compare-toolbar"><strong>Before / after</strong><button type="button" data-close>Back to render</button></div>
      <div class="gs-compare-stage"><video data-result playsinline preload="metadata"></video><video data-source playsinline muted preload="metadata"></video><span class="gs-compare-label is-result">Final render</span><span class="gs-compare-label is-source">Viewport / source</span><div class="gs-compare-divider" aria-hidden="true"><span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m8 7-5 5 5 5m8-10 5 5-5 5M3 12h18"/></svg></span></div><input class="gs-compare-wipe" data-wipe type="range" min="0" max="100" value="50" aria-label="Before and after divider"/></div>
      <div class="gs-compare-controls"><button type="button" data-play aria-label="Play comparison">Play</button><input data-seek type="range" min="0" max="1" step="0.001" value="0" aria-label="Seek both videos"/><output data-time>0:00</output><button type="button" data-mute>Mute</button><button type="button" data-fullscreen aria-label="Fullscreen comparison">Expand</button></div><p class="gs-compare-message" role="status" hidden></p>`;
    const find=s=>host.querySelector(s);
    this.result=find('[data-result]');this.source=find('[data-source]');this.source.muted=true;
    this.seek=find('[data-seek]');this.time=find('[data-time]');this.playButton=find('[data-play]');
    find('[data-wipe]').oninput=e=>host.style.setProperty('--gs-wipe',`${e.target.value}%`);
    this.playButton.onclick=()=>this.result.paused?this.result.play().catch(()=>this.fail('Playback could not start. Try Play again.')):this.result.pause();
    this.seek.oninput=()=>{this.result.currentTime=Number(this.seek.value);this.sync(true);};
    find('[data-mute]').onclick=e=>{this.result.muted=!this.result.muted;e.target.textContent=this.result.muted?'Unmute':'Mute';};
    find('[data-fullscreen]').onclick=()=>host.requestFullscreen?.().catch(()=>{});
    find('[data-close]').onclick=()=>{this.hide();this.onClose?.();};
    this.result.onplay=()=>{this.playButton.textContent='Pause';this.playButton.setAttribute('aria-label','Pause comparison');this.sync(true);this.source.play().catch(()=>this.fail('Source playback unavailable. Use Back to render.'));};
    this.result.onpause=()=>{this.source.pause();this.playButton.textContent='Play';this.playButton.setAttribute('aria-label','Play comparison');};
    this.result.onseeking=()=>this.sync(true);
    this.result.onratechange=()=>{this.source.playbackRate=this.result.playbackRate;};
    this.result.onwaiting=()=>this.source.pause();
    this.result.onplaying=()=>{this.sync(true);this.source.play().catch(()=>{});};
    this.source.onloadedmetadata=()=>this.sync(true);
    this.result.onloadedmetadata=()=>{this.seek.max=Number.isFinite(this.result.duration)?this.result.duration:1;if(this.result.videoWidth)this.host.style.setProperty('--gs-compare-ratio',`${this.result.videoWidth} / ${this.result.videoHeight}`);this.sync(true);};
    this.result.ontimeupdate=()=>this.sync();
    this.result.onended=()=>this.source.pause();
    this.source.onerror=this.result.onerror=()=>this.fail('A comparison video could not load. Use Back to render.');
  }
  sync(force=false) {
    const time=Number(this.result.currentTime)||0, target=time+this.offset;
    if(this.source.readyState && (force || Math.abs(this.source.currentTime-target)>0.08))
      this.source.currentTime=Math.min(target,Math.max(0,(this.source.duration||Infinity)-0.001));
    this.seek.value=time;this.time.textContent=`${Math.floor(time/60)}:${String(Math.floor(time%60)).padStart(2,'0')}`;
  }
  show(source,result,offset=0) {
    const key=JSON.stringify([source,result,offset]);
    if(this.key!==key){
      this.hide();this.key=key;this.offset=Math.max(0,Number(offset)||0);
      this.source.src=source;this.result.src=result;this.source.load();this.result.load();
      this.host.querySelector('.gs-compare-message').hidden=true;
    }
    this.host.hidden=false;
  }
  hide(){this.result.pause();this.source.pause();this.host.hidden=true;}
  fail(message){const node=this.host.querySelector('.gs-compare-message');node.textContent=message;node.hidden=false;this.result.pause();this.source.pause();}
}
