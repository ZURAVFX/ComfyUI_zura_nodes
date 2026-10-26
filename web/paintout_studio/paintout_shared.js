import {PaintoutWorkspace} from './studio_paintout.js';

let workspace;

export function closePaintoutHost(){
  workspace?.owner.studio.close();
}

export function getPaintoutWorkspace(owner){
  if(!workspace)workspace=new PaintoutWorkspace(owner);
  else if(workspace.owner!==owner){
    workspace.owner.videoComposer?.mountWorkflow('video');
    workspace.owner.studio.close();
    workspace.owner=owner;
    workspace.studio=owner.studio;
    workspace.api=owner.api;
    workspace.app=owner.app;
  }
  owner.root.append(workspace.page);
  workspace.page.hidden=false;
  return workspace;
}
