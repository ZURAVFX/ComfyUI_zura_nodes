import {app} from '/scripts/app.js';
import {openZuraStudio} from './studio.js';

const launchers={
  ZuraStudioLauncher:{label:'Open Zura Studio',open:openZuraStudio},
  ZuraPaintoutStudioLauncher:{label:'Open Zura Studio',open:()=>openZuraStudio('paintout')},
};

app.registerExtension({
  name:'Zura.Studio.Launchers',
  commands:[
    {id:'zura.studio.open',label:'Open Zura Studio',function:openZuraStudio},
    {id:'zura.paintout.open',label:'Open Zura Studio: Paintout',function:()=>openZuraStudio('paintout')},
  ],
  menuCommands:[{path:['Zura'],commands:['zura.studio.open']}],
  setup(){
    if(document.getElementById('zura-studio-shortcuts'))return;
    const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('./studio_launchers.css',import.meta.url).href;document.head.append(css);
    const shortcuts=document.createElement('nav');shortcuts.id='zura-studio-shortcuts';shortcuts.setAttribute('aria-label','Zura Studio');
    for(const [label,open] of [['Zura Studio',openZuraStudio]]){
      const button=document.createElement('button');button.type='button';button.textContent=label;button.title=`Open ${label}`;
      button.onclick=()=>Promise.resolve(open()).catch(error=>console.error(`Could not open ${label}`,error));shortcuts.append(button);
    }
    document.body.append(shortcuts);
  },
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
