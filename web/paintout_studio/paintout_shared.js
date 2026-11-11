import {WatermarkWorkspace} from './watermark_workspace.js';
import {PaintoutWorkspace} from './studio_paintout.js';
import {workspaceStorage} from '../studio_storage.js';
const paintouts=new WeakMap(),watermarks=new WeakMap();

export function getPaintoutWorkspace(owner){
  const store=workspaceStorage(owner);let workspace=paintouts.get(store);
  if(!workspace){workspace=new PaintoutWorkspace(owner,{paintoutOnly:true});paintouts.set(store,workspace);}
  else if(workspace.owner!==owner){
    workspace.close();
    Object.assign(workspace,{owner,studio:owner.studio,api:owner.api,app:owner.app});
  }
  if(workspace.page.parentNode!==owner.root)owner.root.append(workspace.page);
  workspace.page.hidden=false;
  return workspace;
}

export function getWatermarkWorkspace(owner){
  const store=workspaceStorage(owner);let watermarkWorkspace=watermarks.get(store);
  if(!watermarkWorkspace){watermarkWorkspace=new WatermarkWorkspace(owner);watermarks.set(store,watermarkWorkspace);}
  else if(watermarkWorkspace.owner!==owner){watermarkWorkspace.close();Object.assign(watermarkWorkspace,{owner,studio:owner.studio,api:owner.api,app:owner.app});}
  if(watermarkWorkspace.page.parentNode!==owner.root)owner.root.append(watermarkWorkspace.page);
  watermarkWorkspace.page.hidden=false;return watermarkWorkspace;
}
