// Keep signed-off Kitchen graphs when the running ComfyUI advertises them.
// PyTorch attention is the portable fallback; older cores can use their
// configured native backend with no explicit model patch.
export function attentionBackend(info, preferred='comfy kitchen attention'){
  // Pure graph builders without runtime capabilities retain their historical
  // output. UI submission always passes the current object_info snapshot.
  if(info==null)return preferred;
  const field=info?.ModelAttentionBackend?.input?.required?.attention;
  const options=Array.isArray(field?.[0])?field[0]:field?.[0]==='COMBO'&&Array.isArray(field[1]?.options)?field[1].options:[];
  if(options.includes(preferred))return preferred;
  if(options.includes('pytorch attention'))return 'pytorch attention';
  return null;
}

export function applyAvailableAttention(graph,info){
  for(const [id,node] of Object.entries(graph)){
    if(node.class_type!=='ModelAttentionBackend')continue;
    const backend=attentionBackend(info,node.inputs.attention);
    if(backend){
      node.inputs.attention=backend;
      if(backend==='pytorch attention'&&node._meta?.title?.includes('Comfy Kitchen'))node._meta.title='PyTorch attention';
      continue;
    }
    const upstream=node.inputs.model;
    if(!Array.isArray(upstream)||upstream.length!==2)throw Error('The attention node has no model input.');
    for(const consumer of Object.values(graph)){
      for(const [key,value] of Object.entries(consumer.inputs||{})){
        if(Array.isArray(value)&&value.length===2&&value[0]===id&&value[1]===0)consumer.inputs[key]=upstream.slice();
      }
    }
    delete graph[id];
  }
  return graph;
}
