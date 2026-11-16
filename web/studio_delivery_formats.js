// Legacy enum values remain readable by saved workflows. New video masters are MOV.
export const deliveryFormatLabel=value=>({
  'HLG video':'ProRes 4444 MOV',
  'EXR + HLG video':'EXR + ProRes 4444',
})[value]||value;

export const deliveryVideoFile=files=>{
  const values=(files||[]).filter(file=>file?.type==='output'&&typeof file.filename==='string');
  return values.find(file=>/\.mov$/i.test(file.filename))||values.find(file=>/\.mp4$/i.test(file.filename))||null;
};

// Browser-only playback uses an explicitly returned preview. Never guess a sibling.
export const playbackFile=file=>file?.preview?.type==='output'&&typeof file.preview.filename==='string'?file.preview:file;

/** The movie is a codec container, never evidence of HLG or a particular gamut. */
export function deliveryVideoColour(file,metadata={}){
  const colour=file?.colour||metadata.videoColour||metadata.colour;
  if(colour&&typeof colour.encoding==='string'&&typeof colour.sceneLinear==='boolean')return {...colour};
  if(/\.mov$/i.test(file?.filename||''))return {encoding:'unknown',sceneLinear:false};
  // Keep old saved HLG MP4 masters correctly identified.
  return {encoding:'hlg_rec2020',sceneLinear:false};
}
