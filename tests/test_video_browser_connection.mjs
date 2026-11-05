import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {BrowserImageConnection} from '../web/studio_browser_images.js';

const {document}=parseHTML('<html><body><div id="connection"></div></body></html>');
const calls=[];
let connection;
let activeBrowser='chrome',state='connected';
const browsers=[{id:'chrome',name:'Chrome'},{id:'edge',name:'Microsoft Edge'},{id:'safari',name:'Safari'}];
const owner={job:false,submitting:false,
  async fetch(path,body){calls.push({path,body});if(body){if(path.endsWith('_cancel'))state='disconnected';else {activeBrowser=body.browser;state='connected';}return {ok:true};}return {state,message:'Browser account connected',browser:activeBrowser,browsers};},
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
    assert.deepEqual(calls.findLast(c=>c.body),{path:'/zura/browser_image_login',body:{provider,browser:'chrome'}});
    owner.job=true;connection.sync(connection.model);
    assert.equal(connection.button.disabled,true,'Do not reconnect while a generation is working');
    owner.job=false;
  }
  assert.equal(connection.select.getAttribute('aria-label'),'Browser for website sign-in');
  connection.select.options[2].selected=true;connection.select.onchange();
  assert.equal(connection.connected(connection.model),false,'Changing browsers requires an explicit connection to that account');
  await connection.button.onclick();
  assert.equal(calls.findLast(c=>c.body).body.browser,'safari');
  assert.equal(connection.connected(connection.model),true);
  state='signing_in';await connection.refresh();
  assert.equal(connection.select.disabled,true);
  assert.equal(connection.button.textContent,'Cancel connection');
  await connection.button.onclick();
  assert.equal(calls.findLast(c=>c.body).path,'/zura/browser_image_cancel');
  assert.equal(connection.select.disabled,false);
  assert.equal(connection.connected(connection.model),false);
  let resolveOld;
  const realFetch=owner.fetch;
  owner.fetch=()=>new Promise(resolve=>{resolveOld=resolve;});
  const stale=connection.refresh();
  owner.fetch=realFetch;
  await connection.button.onclick();
  resolveOld({state:'error',message:'old response'});await stale;
  assert.equal(connection.connected(connection.model),true,'A late status response cannot overwrite the new connection');
  connection.sync(null);
  assert.equal(connection.host.hidden,true);
  assert.equal(connection.timer,null,'Leaving the image stage stops connection polling');
  connection.close();
  assert.equal(connection.closed,true);
  console.log('Starting-frame browser connection: both providers, explicit sign-in, render lock and polling cleanup pass.');
}finally{connection.close();}
