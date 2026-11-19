"""Inspect the real compact surface DOM/CSS in isolated Chromium, never live apps."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get('CHROME_EXECUTABLE', 'C:/Program Files/Google/Chrome/Application/chrome.exe')
POSITION = subprocess.check_output(['node', '--input-type=module', '-e', "import {positionStudioPopover} from './web/studio_popovers.js';process.stdout.write(positionStudioPopover.toString());"], cwd=ROOT, text=True)
reports = []
with tempfile.TemporaryDirectory(prefix='plate-source-menu-') as directory:
    path = Path(directory) / 'fixture.html'
    subprocess.run(['node', 'tests/test_studio_plate_compact.mjs'], cwd=ROOT, env={**os.environ, 'PAINT_LAYOUT_FIXTURE': str(path), 'PAINT_LAYOUT_STAGE': 'mask'}, check=True)
    script = '''
addEventListener('load',()=>requestAnimationFrame(()=>requestAnimationFrame(()=>{
 const root=document.querySelector('#genj-studio'),surface=root.querySelector('.zplate-surface');surface.classList.add('is-side-open');
 const menu=[...root.querySelectorAll('.zp-editor-action-menu')].find(node=>node.querySelector('summary')?.textContent==='Mask options');
 const side=menu.closest('.zpx-side');side.scrollTop=menu.offsetTop;
 menu.open=true;POSITION(menu,root);const panel=menu.querySelector(':scope>.zc-tool-panel');
 const rect=element=>{const r=element.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
 const box=rect(panel),hit=document.elementFromPoint(Math.max(box.left+2,Math.min(box.right-2,box.left+box.width/2)),Math.max(box.top+2,Math.min(box.bottom-2,box.top+20)));
 document.documentElement.dataset.menuGeometry=JSON.stringify({width:innerWidth,height:innerHeight,source:rect(root.querySelector('[data-plate-source]')),spec:rect(root.querySelector('[data-plate-spec]')),panel:box,position:getComputedStyle(panel).position,withinClip:panel.contains(hit),items:[...panel.children].map(rect)});
})));
'''.replace('POSITION', '(' + POSITION + ')')
    path.write_text(path.read_text(encoding='utf-8') + '<script>' + script + '</script>', encoding='utf-8')
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, executable_path=CHROME, args=['--allow-file-access-from-files'])
        for width in (1920, 1280, 390):
            page = browser.new_page(viewport={'width': width, 'height': 760})
            page.goto(path.as_uri(), wait_until='load')
            page.wait_for_function('document.documentElement.dataset.menuGeometry')
            data = json.loads(page.locator('html').get_attribute('data-menu-geometry'))
            panel = data['panel']
            assert data['position'] == 'fixed', data
            assert panel['left'] >= 12 and panel['right'] <= width - 12, data
            assert panel['top'] >= 12 and panel['bottom'] <= 748, data
            assert panel['width'] >= 200 and panel['height'] > 40 and data['withinClip'], data
            assert all(item['left'] >= panel['left'] and item['right'] <= panel['right'] for item in data['items']), data
            assert data['source']['left'] < data['spec']['left'], data
            reports.append({'viewport': [width, 760], 'menu': panel, 'source': data['source']})
            page.close()
        browser.close()
print(json.dumps(reports))
