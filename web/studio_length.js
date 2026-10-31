export function clipLength(config,sourceDuration) {
  const source=Number(sourceDuration),original=config.length_mode==="original";
  const start=original?0:Number(config.start)||0;
  const seconds=original?source:Math.min(Number(config.duration),source-start);
  const frames=Math.max(1,Math.ceil(seconds*24-1e-6));
  const viewport=config.workflow_mode==="viewport",scene=config.edit_area==="scene";
  // Saved H3 relight choices are migrated to Wan 2.1 before the next run.
  const chainedRelight=config.workflow_mode==="relight";
  const modelMaximum=chainedRelight?null:config.engine==="wan2"?81/24:config.engine==="h3"?5:config.engine==="local"&&scene?(viewport?15:5):config.engine==="wan"&&config.audio_id&&config.lip_sync?30:null;
  const maximum=original?modelMaximum:Math.min(modelMaximum??30,30);
  const invalid=Number.isFinite(source)&&source>0&&(seconds<=0 || (!original&&Number(config.duration)>30) || (!chainedRelight&&["h3","wan2"].includes(config.engine)&&frames<5) || (maximum!==null&&frames>maximum*24));
  const h3Padded=config.engine==="h3"&&!chainedRelight;
  const stride=chainedRelight||config.engine==="wan2"||config.engine==="wan"?4:h3Padded?17:config.engine==="local"?8:0, remainder=stride===17?5:1;
  const deliveryFrames=stride&&Number.isFinite(frames)?frames+(remainder-frames%stride+stride)%stride:frames;
  return {seconds,frames,outputSeconds:frames/24,deliveryFrames,maximum,invalid};
}

export function recoverClipLength(config,sourceDuration) {
  const info=clipLength(config,sourceDuration),source=Number(sourceDuration);
  const start=Math.max(0,Math.min(Number(config.start)||0,Math.max(0,source-0.25)));
  const duration=Math.max(0.25,Math.min(info.maximum||30,source-start,Number(config.duration)||2));
  return {...config,length_mode:"custom",start:config.length_mode==="original"?0:start,
    duration:config.length_mode==="original"?Math.max(0.25,Math.min(info.maximum||30,source)):duration};
}
