"""Isolated real-controller/CSS selection rendering; no ComfyUI, AE or GPU."""
import html,json,os,re,subprocess,tempfile
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
chrome=os.environ['CHROME_EXECUTABLE']
styles=['studio.css','studio_components.css','studio_create.css','studio_composer.css','paintout_studio/paintout_editor.css','studio_polish.css','studio_image_area.css']
script=r"""
import {ImageEditArea} from 'MODULE';
const root=document.querySelector('#genj-studio'),picture=document.createElement('canvas');picture.width=320;picture.height=192;const pc=picture.getContext('2d');
for(const [x,w,c]of [[0,107,'#1554b8'],[107,106,'#eeeeee'],[213,107,'#151515']]){pc.fillStyle=c;pc.fillRect(x,0,w,192);}
const image=picture.toDataURL(),source={filename:'fixture.png',file:'fixture.png',width:320,height:192};
let area;const owner={root,mode:'image',imageOperation:'edit',references:[source],items:[],selectedImage:-1,draft:{},editInputs:{source:root.querySelector('.zc-image-source'),showSource:true},api:{apiURL:()=>image},$(id){return root.querySelector('#zc-'+id);},save(){},render(){area?.sync();},message(){}};
area=new ImageEditArea(owner);area.sync();area.openEditor('brush');
while(!area.viewer||!area.loading.hidden)await new Promise(r=>setTimeout(r,10));
const viewer=area.viewer;viewer.maskCtx.fillStyle='white';for(const x of [24,128,232])viewer.maskCtx.fillRect(x,48,64,64);viewer.maskPresent=true;viewer.maskVersion++;area.state.enabled=true;
const before=viewer.maskCanvas.toDataURL(),sketchBefore=viewer.sketchCanvas.toDataURL();viewer.cursor=null;viewer.draw();
const sample=(x,y)=>{const t=viewer.transform();return [...viewer.ctx.getImageData(Math.round(t.x+x*t.scale),Math.round(t.y+y*t.scale),1,1).data].slice(0,3);};
const marked=[56,160,264].map(x=>sample(x,80));viewer.opacity=0;viewer.draw();const unmarked=[56,160,264].map(x=>sample(x,80));viewer.opacity=.45;viewer.draw();
const boxes=[...area.host.querySelectorAll('.zia-paint-rail button:not([hidden]),.zia-toolbar button,.zia-toolbar summary,.zia-toolbar input')].filter(e=>!e.closest('[hidden]')&&(!e.closest('details:not([open])')||e.tagName==='SUMMARY')).map(e=>({label:e.getAttribute('aria-label')||e.textContent.trim(),rect:e.getBoundingClientRect().toJSON(),scrollWidth:e.scrollWidth,clientWidth:e.clientWidth}));
const report={width:innerWidth,height:innerHeight,host:area.host.getBoundingClientRect().toJSON(),rail:area.host.querySelector('.zia-paint-rail').getBoundingClientRect().toJSON(),stage:area.stage.getBoundingClientRect().toJSON(),prompt:document.querySelector('.zc-image-composer').getBoundingClientRect().toJSON(),mode:area.host.querySelector('.zia-editor-title').textContent,entryHidden:area.button.hidden&&area.guideButton.hidden,boxes,marked,unmarked,maskUnchanged:before===viewer.maskCanvas.toDataURL(),sketchUnchanged:sketchBefore===viewer.sketchCanvas.toDataURL()};
document.body.dataset.report=JSON.stringify(report);
"""
with tempfile.TemporaryDirectory(prefix='zura-image-area-') as folder:
    fixture=Path(folder)/'fixture.html'
    links=''.join('<link rel="stylesheet" href="'+(repo/'web'/path).as_uri()+'">' for path in styles)
    markup='<main id="genj-studio" data-workspace="image"><header class="gs-top">Zura Studio · Edit image</header><section class="zc-image-page"><main class="zc-image-main"><div class="zc-image-scroll"><header class="zc-image-heading"><h2>Edit image</h2><div class="zc-image-tools"></div></header><div class="zc-image-source"></div><div id="zc-gallery" class="zc-gallery"></div><div id="zc-image-empty"></div></div><form class="zc-image-composer"><textarea placeholder="Describe your edit"></textarea></form></main></section></main>'
    fixture.write_text('<html><head>'+links+'</head><body>'+markup+'<script>addEventListener("error",e=>document.body.dataset.fixtureError=e.message);addEventListener("unhandledrejection",e=>document.body.dataset.fixtureError=String(e.reason));</script><script type="module">'+script.replace('MODULE',(repo/'web/studio_image_area.js').as_uri())+'</script></body></html>',encoding='utf-8')
    reports=[]
    evidence=Path(os.environ['IMAGE_AREA_UI_EVIDENCE']) if os.environ.get('IMAGE_AREA_UI_EVIDENCE') else None
    if evidence:evidence.mkdir(parents=True,exist_ok=True)
    for width,height in [(1280,900),(1280,760),(390,760)]:
        wrapper=Path(folder)/f'viewport-{width}-{height}.html'
        wrapper.write_text('<html><body style="margin:0"><iframe id="viewport" style="border:0;width:'+str(width)+'px;height:'+str(height)+'px" src="'+fixture.as_uri()+'"></iframe><script>async function check(){const frame=document.querySelector("iframe");try{if(frame.contentDocument.body.dataset.report){document.body.dataset.report=frame.contentDocument.body.dataset.report;return;}}catch{}setTimeout(check,10);}check();</script></body></html>',encoding='utf-8')
        screenshot=[f'--screenshot={evidence / (str(width)+"x"+str(height)+".png")}'] if evidence and (width,height) in ((1280,900),(390,760)) else []
        result=subprocess.run([chrome,*screenshot,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--allow-file-access-from-files',f'--user-data-dir={folder}/profile-{width}-{height}',f'--window-size={max(600,width+32)},{height+150}','--virtual-time-budget=2500','--dump-dom',wrapper.as_uri()],capture_output=True,text=True,encoding='utf-8',check=True)
        match=re.search(r'data-report="([^"]+)"',result.stdout)
        assert match,'Real image editor did not finish loading'
        report=json.loads(html.unescape(match.group(1)))
        assert [report['width'],report['height']]==[width,height],report
        assert report['maskUnchanged'] and report['sketchUnchanged'],report
        assert report['entryHidden'] and report['mode']=='Select area',report
        for selected,base in zip(report['marked'],report['unmarked']):assert max(abs(a-b) for a,b in zip(selected,base))>=15,(selected,base)
        for box in report['boxes']:
            rect=box['rect']
            assert rect['width']>0 and rect['height']>0,box
            assert rect['left']>=report['host']['left']-1 and rect['right']<=report['host']['right']+1,box
            if box['label']=='Select area':assert box['scrollWidth']<=box['clientWidth']+1,box
        assert report['prompt']['top']>=report['host']['bottom']-1,report
        assert abs(report['prompt']['width']-report['host']['width'])<=2,report
        reports.append({'viewport':[report['width'],report['height']],'stage':report['stage'],'selection':report['marked'],'original':report['unmarked'],'maskUnchanged':True})
    if evidence:(evidence/'geometry-pixels.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports))
