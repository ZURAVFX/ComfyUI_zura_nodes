// Optional source-space edit area. Crop and stitch are Hallett's native nodes;
// the small Zura nodes only validate the artist mask and returned crop.
export const IMAGE_AREA_NODE_TYPES=[
  'LoadImage','GetImageSize','ImageScale','ImageScaleToTotalPixels','ImageCompositeMasked',
  'SmartImageCrop','SmartImageStitcher','ZuraImageEditMask','ZuraImageEditCropResult','ZuraImageEditResolution',
];

export function imageAreaSourceKey(reference){return typeof reference?.file==='string'?reference.file:'';}

export function smartCropCapabilities(info={}){
  const missing=IMAGE_AREA_NODE_TYPES.filter(name=>!info?.[name]);
  const inputs=name=>({...info?.[name]?.input?.required,...info?.[name]?.input?.optional});
  const crop=inputs('SmartImageCrop'),stitch=inputs('SmartImageStitcher');
  return {available:!missing.length,missing,schema:{
    contextPadding:Object.hasOwn(crop,'context_padding'),
    maxMegapixels:Object.hasOwn(crop,'max_megapixels'),
    featherMode:Object.hasOwn(stitch,'feather_mode'),
  }};
}

const node=(class_type,title,inputs)=>({class_type,_meta:{title},inputs});

/** Wrap a complete image-edit graph while preserving its native model path. */
export function applyImageEditArea(graph,{edit_area,smart_crop_schema,recipe,shape,width,height,references}){
  if(!edit_area?.enabled)return graph;
  if(!recipe?.edit)throw new Error('Choose Edit image to paint an edit area.');
  const source=imageAreaSourceKey(references?.[0]);
  const mask=edit_area.mask?.file;
  if(!source||edit_area.source_key!==source)throw new Error('The edit area belongs to a different main image. Paint it again.');
  if(typeof mask!=='string'||!mask||mask.includes('..'))throw new Error('Paint and save an edit area before applying the edit.');
  if(!graph.reference_1||!graph.save?.inputs?.images)throw new Error('This image model cannot use an edit area yet.');
  const context=Number(edit_area.context??64),feather=Number(edit_area.feather??16);
  if(!Number.isInteger(context)||context<0||context>4096||!Number.isInteger(feather)||feather<0||feather>256)throw new Error('Choose a valid context and feather size for the edit area.');
  const schema=smart_crop_schema||{contextPadding:true,featherMode:true,maxMegapixels:true};
  const step=recipe.sizeStep||16;
  const megapixels=width*height/(1024*1024);
  if(shape!=='auto'&&megapixels>16)throw new Error('The edit area supports up to 16 MP of AI processing. Choose a smaller processing size.');

  // Rewrite only consumers of Image 1. Keep the original LoadImage for the
  // crop and final source-sized composite; all other references stay intact.
  const replace=value=>{
    if(Array.isArray(value))return value.length===2&&value[0]==='reference_1'&&value[1]===0?['zura_area_working',0]:value.map(replace);
    if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,replace(item)]));
    return value;
  };
  for(const entry of Object.values(graph))entry.inputs=replace(entry.inputs);
  const dimensions=['zura_area_size',0],heightDimensions=['zura_area_size',1];
  // Every model's output canvas and native scheduler must use the actual crop
  // dimensions rather than the full-source dimensions entered in the UI.
  for(const entry of Object.values(graph)){
    for(const key of ['width','custom_width'])if(Object.hasOwn(entry.inputs,key))entry.inputs[key]=dimensions;
    for(const key of ['height','custom_height'])if(Object.hasOwn(entry.inputs,key))entry.inputs[key]=heightDimensions;
  }
  if(recipe.provider)graph.browser_image.inputs.size='Custom';
  const generated=graph.save.inputs.images;
  graph.zura_area_mask_image=node('LoadImage','Load painted edit area',{image:mask});
  graph.zura_area_mask=node('ZuraImageEditMask','Prepare edit area',{image:['reference_1',0],painted_mask:['zura_area_mask_image',0],feather_pixels:feather,...(edit_area.guide?.file?{drawing_region:edit_area.drawing_region!==false}:{})});
  const crop={image:['reference_1',0],mask:['zura_area_mask',0],resolution_mode:'Automatic',max_resolution:8192,min_resolution:256,manual_width:1024,manual_height:1024,mask_grow_pixels:schema.contextPadding?0:context,patch_mask_holes:false,no_mask_mode:'Bypass',force_divisibility:step};
  if(schema.contextPadding)crop.context_padding=context;
  graph.zura_area_crop=node('SmartImageCrop','Crop selected area with context',crop);
  // Auto preserves larger native crops and gives small crops a 1 MP quality
  // floor. Explicit sizes remain approximate MP targets at the crop's aspect.
  let guideCrop=['zura_area_crop',0];
  if(edit_area.guide?.file){const guide=edit_area.guide.file;if(typeof guide!=='string'||!guide||guide.includes('..'))throw Error('Choose a valid drawing guide.');graph.zura_drawing=node('LoadImage','Load the drawn guide',{image:guide});graph.zura_drawing_crop=node('SmartImageCrop','Use the same edit area for the drawing',{...crop,image:['zura_drawing',0]});guideCrop=['zura_drawing_crop',0];}
  graph.zura_area_target=node('ZuraImageEditResolution','Keep the crop within model size limits',{image:['zura_area_crop',0],megapixels:shape==='auto'?0:Math.max(.01,megapixels),resolution_steps:step});
  graph.zura_area_working=node('ImageScaleToTotalPixels','Set edit processing size',{image:guideCrop,upscale_method:'lanczos',megapixels:['zura_area_target',0],resolution_steps:step});
  graph.zura_area_size=node('GetImageSize','Edit processing dimensions',{image:['zura_area_working',0]});
  graph.zura_area_result=node('ZuraImageEditCropResult','Check edited crop',{image:generated,reference:['zura_area_working',0]});
  const stitch={original_image:['reference_1',0],processed_image:['zura_area_result',0],stitcher_info:['zura_area_crop',2],feather_pixels:0,blend_mode:'Mask Feather',resize_full_image_output:'Restore Original Size',enable_color_match:false,color_match_amount:0,mask:['zura_area_crop',1]};
  if(schema.featherMode)stitch.feather_mode='Pixels';
  graph.zura_area_stitch=node('SmartImageStitcher','Stitch edited crop',stitch);
  graph.zura_area_composite=node('ImageCompositeMasked','Preserve unpainted image',{destination:['reference_1',0],source:['zura_area_stitch',0],mask:['zura_area_mask',1],x:0,y:0,resize_source:false});
  graph.save.inputs.images=['zura_area_composite',0];
  return graph;
}
