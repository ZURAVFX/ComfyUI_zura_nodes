export async function fetchJsonWithTimeout(fetcher,path,options={},timeoutMs=90000){
  const controller=new AbortController();
  const parent=options.signal;
  const relay=()=>controller.abort();
  if(parent?.aborted)controller.abort();
  else parent?.addEventListener('abort',relay,{once:true});
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const response=await fetcher(path,{...options,signal:controller.signal});
    const text=await response.text();
    let data;
    try{data=text?JSON.parse(text):{};}catch(_){throw Error(`Server returned invalid JSON (${response.status})`);}
    if(!response.ok)throw Error(data.error||`Request failed (${response.status})`);
    return data;
  }catch(error){
    if(error?.name==='AbortError')throw Error('Request timed out or was cancelled.');
    throw Error(error?.message||'Network request failed.');
  }finally{
    clearTimeout(timer);parent?.removeEventListener('abort',relay);
  }
}
