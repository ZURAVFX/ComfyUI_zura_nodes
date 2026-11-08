// Keep the artist's canvas separate from the model's spatial grid. Stretch
// the whole endpoint to that grid, then undo the stretch after decoding.
export function frameSourceResolution(source,cap,megapixels=null){
  const sw=Number(source?.width),sh=Number(source?.height);
  if(![sw,sh].every(n=>Number.isSafeInteger(n)&&n>0))return null;
  if(megapixels!==null&&!(Number.isFinite(Number(megapixels))&&Number(megapixels)>0))throw new Error('Choose a valid megapixel size.');
  const step=cap.dimensionStep,min=cap.minDimension||256,max=cap.maxDimension||4096;
  const at=scale=>{
    // MP4 delivery requires even dimensions; odd source sizes round up by 1 px.
    const outputWidth=Math.max(2,Math.ceil(sw*scale/2)*2),outputHeight=Math.max(2,Math.ceil(sh*scale/2)*2);
    return {width:Math.max(min,Math.ceil(outputWidth/step)*step),height:Math.max(min,Math.ceil(outputHeight/step)*step),outputWidth,outputHeight};
  };
  const fits=s=>s.width<=max&&s.height<=max&&s.width*s.height<=cap.maxPixels;
  const requested=megapixels===null?1:Math.sqrt(Number(megapixels)*1e6/(sw*sh));
  let size=at(requested);
  if(!fits(size)){
    let lo=0,hi=requested;
    for(let i=0;i<52;i++){const mid=(lo+hi)/2;if(fits(at(mid)))lo=mid;else hi=mid;}
    size=at(lo);
  }
  return {...size,sourceWidth:sw,sourceHeight:sh};
}

export function frameOutputSize(config,maxDimension=4096){
  if(config.outputWidth===undefined&&config.outputHeight===undefined)return null;
  const width=Number(config.outputWidth),height=Number(config.outputHeight);
  if(![width,height].every(n=>Number.isInteger(n)&&n>=2&&n<=maxDimension&&n%2===0))throw new Error('Output dimensions must be even numbers, within the canvas limit.');
  if(width>config.width||height>config.height)throw new Error('Output dimensions cannot exceed the processing canvas.');
  return {width,height};
}
