import assert from 'node:assert/strict';
import {CreativeWorkspace} from '../web/studio_create.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';

for (const Workspace of [CreativeWorkspace, FrameVideoWorkspace, PaintoutWorkspace]) {
  let historyReads = 0;
  const output = {filename:'completed.mp4', subfolder:'test', type:'output'};
  const entry = {status:{completed:true,messages:[]}, outputs:{save:{images:[output]}}};
  const ui = Object.create(Workspace.prototype);
  Object.assign(ui, {
    job:{id:'own-job',config:{outputMode:'video'},started:Date.now()}, polling:false, items:[],
    fetch:async path => {
      if (path === '/queue') return {queue_running:[],queue_pending:[]};
      if (path === '/history/own-job') return ++historyReads === 1 ? {} : {'own-job':entry};
      throw Error(path);
    },
    stopPolling(){}, save(){}, render(){}, renderGallery(){}, renderHistory(){}, message(text){this.lastMessage=text;}, preview(){},
  });
  await ui.poll();
  assert.equal(ui.job.id,'own-job','job remains tracked when it completes between history and queue reads');
  await ui.poll();
  assert.equal(ui.job,null);
  assert.equal(ui.items[0].file.filename,'completed.mp4','completed result is retained on the next poll');
  ui.job={id:'own-job',config:{outputMode:'video'},started:Date.now()};let offline=true;
  ui.fetch=async()=>{if(offline){offline=false;throw Error('offline');}return {'own-job':entry};};
  await ui.poll();assert.ok(ui.job);assert.match(ui.lastMessage,/Reconnecting/);
  await ui.poll();assert.equal(ui.job,null);assert.doesNotMatch(ui.lastMessage,/Reconnecting/);
}
console.log('Image, first/last and paintout workspaces preserve jobs completing between queue and history checks.');
