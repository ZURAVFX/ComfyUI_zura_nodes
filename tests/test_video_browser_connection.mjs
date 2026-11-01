import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {BrowserImageConnection} from '../web/studio_browser_images.js';

const {document}=parseHTML('<html><body><div id="connection"></div></body></html>');
const calls=[];
let connection;
const owner={job:false,submitting:false,
  async fetch(path,body){calls.push({path,body});return body?{ok:true}:{state:'connected',message:'Browser account connected'};},
  render(){connection.sync(connection.model);}};
connection=new BrowserImageConnection(owner,document.querySelector('#connection'));
try{
  for(const provider of ['chatgpt','gemini']){
    connection.sync({provider,name:provider==='chatgpt'?'ChatGPT Image':'Gemini Image',ready:true});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(connection.host.hidden,false);
    assert.equal(connection.connected({provider}),true);
    assert.match(connection.host.textContent,/No API credits/);
    await connection.button.onclick();
    assert.deepEqual(calls.findLast(c=>c.body),{path:'/zura/browser_image_login',body:{provider}});
    owner.job=true;connection.sync(connection.model);
    assert.equal(connection.button.disabled,true,'Do not reconnect while a generation is working');
    owner.job=false;
  }
  connection.sync(null);
  assert.equal(connection.host.hidden,true);
  assert.equal(connection.timer,null,'Leaving the image stage stops connection polling');
  connection.close();
  assert.equal(connection.closed,true);
  console.log('Starting-frame browser connection: both providers, explicit sign-in, render lock and polling cleanup pass.');
}finally{connection.close();}
