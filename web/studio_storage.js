// A workspace captures its store at construction, including late job callbacks.
export function memoryStorage(){
  const values=new Map();
  return {getItem:key=>values.get(String(key))??null,setItem:(key,value)=>values.set(String(key),String(value)),removeItem:key=>values.delete(String(key)),key:index=>[...values.keys()][index]??null,get length(){return values.size;}};
}
const fallback=memoryStorage();
export function normalStudioStorage(){try{return globalThis.localStorage||fallback;}catch{return fallback;}}
export function workspaceStorage(owner){return owner?.storage||normalStudioStorage();}
export function aeStudioStorage(id,backing){
  // No capability or broker token is ever written here. Each tab has its own backing.
  if(!backing)try{backing=globalThis.sessionStorage;}catch{}
  backing=backing||memoryStorage();const current=new Map(),prefix=`zura-ae:${id}:`;
  return {getItem(key){key=String(key);if(current.has(key))return current.get(key);try{return backing.getItem(prefix+key);}catch{return null;}},setItem(key,value){key=String(key);current.set(key,String(value));try{backing.setItem(prefix+key,value);}catch{}},removeItem(key){key=String(key);current.set(key,null);try{backing.removeItem(prefix+key);}catch{}}};
}
