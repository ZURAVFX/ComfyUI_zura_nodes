"""Optional read-only check of long HDR setup against a running ComfyUI."""
import importlib
import json
import os
import sys
import types
import unittest
from urllib.parse import quote
from urllib.request import urlopen

import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=package
setup=importlib.import_module(name+'.hdr_readiness')


@unittest.skipUnless(os.environ.get('ZURA_TEST_COMFY_URL'), 'Set ZURA_TEST_COMFY_URL for a running test instance')
class HDRLiveSetupTests(unittest.TestCase):
    def test_installed_continuation_nodes_and_models(self):
        base=os.environ['ZURA_TEST_COMFY_URL'].rstrip('/')
        def read(path):
            with urlopen(base+path,timeout=5) as response:return json.load(response)
        for mode in ('sdr','native'):
            with self.subTest(mode=mode):
                reported=read('/zura/studio/hdr/readiness?mode='+mode+'&output=hlg_and_exr')
                installed={(item['folder'],item['filename']) for item in reported['files'] if item['ready']}
                missing=setup.readiness(mode,'hlg_and_exr',lambda *key:key if key in installed else None,{},longer=True)
                nodes={node:object() for node in missing['missingNodes']
                       if node in read('/object_info/'+quote(node,safe=''))}
                result=setup.readiness(mode,'hlg_and_exr',lambda *key:key if key in installed else None,nodes,longer=True)
                self.assertTrue(result['ready'],f"{mode}: files={result['files']} nodes={result['missingNodes']}")


if __name__=='__main__': unittest.main()
