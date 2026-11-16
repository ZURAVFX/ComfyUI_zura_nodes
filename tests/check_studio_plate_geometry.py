"""CPU-only browser geometry regression for the real compact Paintout DOM and CSS.
Run with CHROME_EXECUTABLE set to a headless Chromium executable. No live app is used.
"""
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[1]
chrome = os.environ.get('CHROME_EXECUTABLE')
if not chrome:
    raise SystemExit('Set CHROME_EXECUTABLE to run the isolated Paintout geometry check.')
with tempfile.TemporaryDirectory(prefix='zura-layout-') as directory:
    fixture = Path(directory) / 'paintout.html'
    reports = []
    for scenario in ('clean', 'mask-generating', 'inline-tools'):
        subprocess.run(['node', 'tests/test_studio_plate_compact.mjs'], cwd=repo,
                       env={**os.environ, 'PAINT_LAYOUT_FIXTURE': str(fixture),
                            'PAINT_LAYOUT_STAGE': 'mask' if scenario.startswith('mask') else 'clean',
                            'PAINT_LAYOUT_GENERATING': '1' if scenario.startswith('mask') else '0',
                            'PAINT_LAYOUT_TOOLS': '1' if scenario == 'inline-tools' else '0'}, check=True)
        # Windows headless Chromium reserves 95 px of window chrome. Check the
        # actual innerHeight, so this cannot accidentally test another viewport.
        for width, height in tuple((width, height) for width in (1280, 1920, 2560) for height in (900, 760)):
            window_height = height + 95
            for attempt in range(3):
                result = subprocess.run([chrome, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                                         '--allow-file-access-from-files', f'--user-data-dir={Path(directory) / (scenario+str(width)+'x'+str(height))}',
                                         f'--window-size={width},{window_height}', '--virtual-time-budget=1500', '--dump-dom', fixture.as_uri()],
                                        capture_output=True, text=True, encoding='utf-8', check=True)
                match = re.search(r'data-geometry="([^"]+)"', result.stdout)
                if not match:
                    continue
                geometry = json.loads(html.unescape(match.group(1)))
                if geometry['height'] == height:
                    break
                window_height += height - geometry['height']
            assert match, 'The production DOM fixture must finish layout'
            assert geometry['height'] == height, geometry
            assert geometry['page']['left'] == 16, geometry
            assert abs(geometry['page']['right'] - (geometry['width'] - 16)) <= 1, geometry
            assert geometry['timeline']['bottom'] <= height - 8, geometry
            assert geometry['readout']['bottom'] < geometry['timeline']['bottom'], geometry
            assert geometry['ruler']['height'] >= 40, geometry
            assert all(handle['height'] >= 40 and handle['bottom'] < geometry['timeline']['bottom']
                       for handle in geometry['handles']), geometry
            assert geometry['view']['height'] >= 180, geometry
            if scenario == 'inline-tools':
                rail = geometry['rail']
                assert len(geometry['inlineTools']) == 8, geometry['inlineTools']
                for control in geometry['inlineTools']:
                    rect = control['rect']
                    assert rect['width'] > 0 and rect['height'] > 0, control
                    assert rect['left'] >= rail['left'] and rect['right'] <= rail['right'], control
                    assert rect['bottom'] <= rail['bottom'], control
            if scenario == 'clean':
                appearance = geometry['cleanAppearance']
                assert appearance['ready'] == appearance['input'], appearance
                assert appearance['fresh'] == appearance['accent'], appearance
                assert appearance['ready'] != appearance['fresh'], appearance
            if scenario.startswith('mask'):
                appearance = geometry['cleanAppearance']
                assert appearance['track'] == appearance['input'], appearance
                assert appearance['track'] != appearance['accent'], appearance
                ancestry = geometry['continueAncestors']
                assert ancestry[0]['disabled'] is False, ancestry
                assert ancestry[0]['rect']['width'] > 100 and ancestry[0]['rect']['height'] >= 32, ancestry
                assert all(not item['hidden'] and item['display'] != 'none' and item['visibility'] == 'visible'
                           for item in ancestry), ancestry
            reports.append({'scenario': scenario, 'viewport': [width, height], 'viewer': geometry['view']['height'],
                            'timeline_bottom': geometry['timeline']['bottom'],
                            'readout_bottom': geometry['readout']['bottom']})
    print(json.dumps(reports))
