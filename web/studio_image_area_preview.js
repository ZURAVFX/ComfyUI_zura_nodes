/** Exact mask-raster boundary and quiet tint. Display only, never inference data. */
export function selectionPreviewPixels(mask,width,height){
  const out=new Uint8ClampedArray(width*height*4),selected=i=>i>=0&&i<width*height&&mask[i*4]>0;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const i=y*width+x;if(!selected(i))continue;
    const edge=x===0||y===0||x===width-1||y===height-1||!selected(i-1)||!selected(i+1)||!selected(i-width)||!selected(i+width);
    out.set([245,99,71,edge?230:26],i*4);
  }
  return out;
}

/** Read-only shot preview, isolated from the native removal mask and undo stack. */
export function installShotSelectionPreview(viewer,current,load){
  const draw=viewer.draw.bind(viewer);let key='',raster=null,epoch=0;
  viewer.draw=()=>{
    draw();const state=current();
    if(!state){key='';raster=null;epoch++;return;}
    if(state.key!==key){
      key=state.key;raster=null;const token=++epoch;
      Promise.resolve().then(()=>load(state.mask,state)).then(value=>{
        if(token!==epoch||current()?.key!==state.key)return;
        raster=value;viewer.draw();
      }).catch(()=>{if(token===epoch){key='';raster=null;}});
    }
    if(!raster)return;
    const t=viewer.transform(),ctx=viewer.ctx;ctx.save();ctx.imageSmoothingEnabled=false;
    if(raster.sketch){ctx.globalAlpha=1;ctx.drawImage(raster.sketch,t.x,t.y,viewer.width*t.scale,viewer.height*t.scale);}
    ctx.globalAlpha=.65;ctx.drawImage(raster.selection||raster,t.x,t.y,viewer.width*t.scale,viewer.height*t.scale);ctx.restore();
  };
}

/** Accepted generated frames stay clean; original/source views remember the guide. */
export const shotSelectionSourceVisible=(anchor,showOriginal)=>!!anchor&&(!anchor.file||!!showOriginal);
