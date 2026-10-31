import {PaintoutWorkspace} from './studio_paintout.js';
let workspace;

export function getPaintoutWorkspace(owner){
  if(!workspace)workspace=new PaintoutWorkspace(owner);
  else if(workspace.owner!==owner){
    workspace.close();
    Object.assign(workspace,{owner,studio:owner.studio,api:owner.api,app:owner.app});
  }
  if(workspace.page.parentNode!==owner.root)owner.root.append(workspace.page);
  workspace.page.hidden=false;
  return workspace;
}
