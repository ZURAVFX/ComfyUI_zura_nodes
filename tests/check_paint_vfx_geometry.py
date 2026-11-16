"""Isolated real-canvas layout fixture; never connects to a running ComfyUI."""
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
repo=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for width,height in [(1280,900),(760,900)]:
        page=browser.new_page(viewport={'width':width,'height':height})
        def route(request):
            path=urlparse(request.request.url).path
            if path=='/':return request.fulfill(content_type='text/html',body='<html><head></head><body><main id="genj-studio" data-workspace="paint_vfx"></main></body></html>')
            file=(repo/'web'/path.lstrip('/')).resolve()
            if file.is_relative_to(repo/'web') and file.is_file():return request.fulfill(path=str(file),content_type='text/javascript' if file.suffix=='.js' else 'text/css' if file.suffix=='.css' else None)
            request.fulfill(status=404,body='Fixture resource unavailable')
        page.route('http://paint-vfx-fixture.test/**',route);page.goto('http://paint-vfx-fixture.test/')
        for name in ['studio.css','studio_create.css']:page.add_style_tag(content=(repo/'web'/name).read_text(encoding='utf-8'))
        page.evaluate("""async()=>{const {PaintVFXWorkspace}=await import('/studio_paint_vfx.js');const memory=new Map();const owner={root:document.querySelector('main'),studio:{},app:{},storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)},api:{apiURL:v=>v,fetchApi:async()=>({ok:true,json:async()=>({models:[],files:[]})})},fetch:async()=>({})};window.workspace=new PaintVFXWorkspace(owner);workspace.page.hidden=false;await workspace.loadKey();}""")
        page.wait_for_selector('.zvfx-canvas canvas');page.wait_for_function("getComputedStyle(document.querySelector('.zvfx-page')).display==='flex'")
        assert page.evaluate('workspace.viewer.tool')=='draw'
        canvas=page.locator('.zvfx-canvas').bounding_box();assert canvas['width']>500 and canvas['height']>=280,canvas
        assert page.locator('[data-vfx=generate]').is_visible()
        assert page.locator('[data-vfx=generate]').is_disabled()
        assert page.locator('.zvfx-page').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.locator('[data-tool=protect]').click();assert page.evaluate('workspace.viewer.tool')=='protect'
        page.locator('[data-tool=draw]').click();assert page.evaluate('workspace.viewer.tool')=='draw'
        page.close()
    browser.close()
print('Paint VFX headless real canvas: 1280/760 layout, immediate brush, tools, visible readiness and no horizontal overflow pass.')
