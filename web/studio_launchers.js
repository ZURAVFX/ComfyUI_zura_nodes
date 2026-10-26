import {app} from '/scripts/app.js';
import {openZuraStudio} from './studio.js';
import {openPaintout} from './paintout_studio/paintout_app.js';

const launchers={
  ZuraStudioLauncher:{label:'Open Zura Studio',open:openZuraStudio},
  ZuraPaintoutStudioLauncher:{label:'Open Paintout Studio',open:openPaintout},
};

app.registerExtension({
  name:'Zura.Studio.Launchers',
  commands:[{id:'zura.studio.open',label:'Open Zura Studio',function:openZuraStudio}],
  menuCommands:[{path:['Zura'],commands:['zura.studio.open']}],
  beforeRegisterNodeDef(nodeType,nodeData){
    const launcher=launchers[nodeData.name];
    if(!launcher)return;
    const previous=nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated=function(...args){
      const result=previous?.apply(this,args);
      const button=this.addWidget('button',launcher.label,null,()=>launcher.open(),{serialize:false});
      button.options.serialize=false;
      this.setSize([240,82]);
      return result;
    };
  },
});
