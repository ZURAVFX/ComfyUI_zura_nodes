import {app} from '/scripts/app.js';
import {openZuraStudio} from '../studio.js';

// Integrated entry. The contest package retains its independent shell;
// both use the same editor and project document format.
export function openPaintout(){return openZuraStudio('paintout');}

app.registerExtension({
  name:'Zura.Paintout.Studio',
  commands:[{id:'zura.paintout.open',label:'Open Paintout Studio',function:openPaintout}],
  menuCommands:[{path:['Zura'],commands:['zura.paintout.open']}],
});
