"""Isolated headless CSS/controller fixture; no running Studio or user browser."""
import argparse
from pathlib import Path
import re
def contrast(fg,bg):
    def luminance(value):
        channels=[int(n)/255 for n in re.findall(r'\d+',value)[:3]]
        linear=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in channels]
        return sum(n*w for n,w in zip(linear,[.2126,.7152,.0722]))
    a,b=sorted([luminance(fg),luminance(bg)]);return (b+.05)/(a+.05)
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser();parser.add_argument('--vendor-css',required=True);args=parser.parse_args()
repo=Path(__file__).resolve().parents[1]
css='\n'.join((repo/'web'/name).read_text(encoding='utf-8') for name in ['studio.css','studio_create.css','studio_panorama.css'])+'\n'+Path(args.vendor_css).read_text(encoding='utf-8')
source=(repo/'web/studio_panorama_editor.js').read_text(encoding='utf-8');controller=source[source.index('export function installEnvironmentWorkspace'):source.index('/** Open the installed')].replace('export function','function')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for width,height in [(1280,800),(390,844)]:
        page=browser.new_page(viewport={'width':width,'height':height})
        page.set_content('<main id="genj-studio"><section class="zhe-viewport"><div class="pano-studio-backdrop zc-hdri-editor zc-panorama-inline"><div class="pano-studio"><button class="pano-studio-seg-item is-active">Selected</button><button class="pano-studio-icon-btn is-active">Icon</button><input type="file" data-add-picker><canvas></canvas></div></div></section></main>')
        page.add_style_tag(content=css+"\n*{transition:none!important}")
        page.evaluate('()=>{'+controller+';window.workspace=installEnvironmentWorkspace(document.querySelector(".zc-hdri-editor"),document.querySelector(".zhe-viewport"));window.addEventListener("keydown",workspace.onKeyDown,true);}')
        for dark in [False,True]:
            page.evaluate('(dark)=>document.documentElement.classList.toggle("dark-theme",dark)',dark)
            values=page.locator('.pano-studio-seg-item').evaluate('(e)=>{const s=getComputedStyle(e);return [s.color,s.backgroundColor]}')
            assert values[0]!=values[1],values
            expected=page.locator('.pano-studio').evaluate('(e)=>getComputedStyle(e).getPropertyValue("--studio-on-strong").trim()');assert values[0] in ({'#ffffff':'rgb(255, 255, 255)','#1b1b1d':'rgb(27, 27, 29)','#111112':'rgb(17, 17, 18)'}.get(expected,expected),),values
        icon=page.locator('.pano-studio-icon-btn').evaluate('(e)=>{const s=getComputedStyle(e);return [s.color,s.backgroundColor]}');assert contrast(*icon)>=4.5,icon
        page.locator('[data-environment-expand]').click()
        rect=page.locator('.zhe-viewport').bounding_box();inset=12 if width<=760 else 20
        assert abs(rect['x']-inset)<1 and abs(rect['width']-(width-inset*2))<2,rect
        bar=page.locator('.zc-environment-actions').bounding_box()
        buttons=page.locator('.zc-environment-actions button').all()
        for button in buttons:
            box=button.bounding_box();assert box['x']>=bar['x'] and box['x']+box['width']<=bar['x']+bar['width']+1,box
        page.keyboard.press('Escape');assert page.locator('[data-environment-expand]').evaluate('(e)=>document.activeElement===e');assert not page.locator('.zhe-viewport').evaluate('(e)=>e.classList.contains("is-expanded")')
        page.close()
    browser.close()
print('Headless Compose360: selected light/dark colours, desktop/mobile expanded geometry, actions and Escape pass.')
