"""HDR source provenance and the first reviewed CFR frame, without a GPU."""
import copy
from fractions import Fraction
import hashlib
import importlib
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image
import v2_bootstrap

for name, path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=package
NAME='ComfyUI_zura_nodes.artist_studio'
hdr=importlib.import_module(NAME+'.ltx_hdr_performance')
studio=importlib.import_module(NAME+'.studio')
colour=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.file=self.root/'genj_studio/original/input.mp4';self.file.parent.mkdir(parents=True);self.file.write_bytes(b'original hdr footage')
        self.sha=hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.original={'id':'a'*32,'kind':'asset','asset_kind':'video','file':'genj_studio/original/input.mp4',
            'sha':self.sha,'name':'input.mp4','duration':3,'width':1920,'height':1080}
        self.records={self.original['id']:self.original}
        self.store=types.SimpleNamespace(load=lambda key:copy.deepcopy(self.records[key]),save=lambda a:self.records.update({a['id']:copy.deepcopy(a)}))
        self.config={'engine':'local','workflow_mode':'motion','edit_area':'scene','ltx_output':'hlg_and_exr'}
        self.info={'kind':'video','fps_rational':'30000/1001','count':90,'transfer':'smpte2084','primaries':'bt2020','matrix':'bt2020nc','range':'tv'}
        self.env=patch.dict(os.environ,{'ZURA_LTX_HDR_PERFORMANCE':'1'});self.env.start();self.addCleanup(self.env.stop)
        self.describe=patch.object(colour,'describe',return_value=self.info);self.describe.start();self.addCleanup(self.describe.stop)

    def check(self, asset):
        path=self.root/asset['file']
        if asset.get('sha')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('changed')
        return path

    def make(self):return hdr.make_source_asset(self.store,self.check,self.original['id'],'auto')

    def test_original_is_preserved_and_interval_binds_colour_and_trim(self):
        source=self.make();self.assertEqual(source['file'],self.original['file']);self.assertEqual(source['sha'],self.sha)
        self.assertNotEqual(source['id'],self.original['id'])
        result=hdr.source_interval(source,self.store,self.check,self.config,{'start':.3,'frames':24,'fps':24})
        self.assertEqual((result['first_source_frame'],result['frames'],result['fps']),(9,24,24))
        self.assertEqual(result['resolved_colour_space'],'pq_rec2020')
        self.assertEqual(result['sha'],self.sha)
        project={'source':source,'config':studio.clean_config(self.config)}
        first=studio.prep_key(project)
        changed=copy.deepcopy(project);changed['source']['native_hdr_video']['colour_space']='pq_rec2020'
        self.assertNotEqual(studio.prep_key(changed),first,'Changing colour requires a fresh source review')

    def test_original_mutation_wrong_identity_and_sdr_routes_fail_closed(self):
        source=self.make()
        for config in ({**self.config,'engine':'h3'},{**self.config,'edit_area':'mask'},
                       {**self.config,'ltx_output':'sdr'}):
            with self.subTest(config=config),self.assertRaises(ValueError):hdr.verify_source(source,self.store,self.check,config)
        bad=copy.deepcopy(source);bad['file']='genj_studio/other.mp4'
        with self.assertRaisesRegex(ValueError,'no longer matches'):hdr.verify_source(bad,self.store,self.check,self.config)
        self.file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):hdr.verify_source(source,self.store,self.check,self.config)

    def test_sdr_tag_and_disabled_feature_rejected(self):
        self.info['transfer']='bt709'
        with self.assertRaisesRegex(ValueError,'tagged SDR'):self.make()
        with patch.dict(os.environ,{'ZURA_LTX_HDR_PERFORMANCE':'0'}),self.assertRaisesRegex(ValueError,'opt-in'):self.make()

    def test_explicit_source_frame_look_needs_no_dummy_reference(self):
        appearance=importlib.import_module(NAME+'.appearance')
        source=self.make()
        result=appearance.resolve_appearance({'look_mode':'source_hdr','references':[], 'config':self.config},
            self.store.load,self.check,source=source)
        self.assertEqual(result,{'look_mode':'source_hdr','references':[],'starting_asset':None,'character':None})
        with self.assertRaisesRegex(ValueError,'imported HDR video'):
            appearance.resolve_appearance({'look_mode':'source_hdr','config':self.config},self.store.load,self.check,source=self.original)
        with self.assertRaisesRegex(ValueError,'without additional'):
            appearance.resolve_appearance({'look_mode':'source_hdr','references':['a'*32],'config':self.config},self.store.load,self.check,source=source)
        with patch.dict(os.environ,{'ZURA_LTX_HDR_PERFORMANCE':'0'}),self.assertRaisesRegex(ValueError,'opt-in'):
            appearance.resolve_appearance({'look_mode':'source_hdr','config':self.config},self.store.load,self.check,source=source)

    def test_source_frame_choice_cannot_auto_approve_or_start_image_generation(self):
        import asyncio
        source=self.make()
        project={'source':source,'config':studio.clean_config(self.config),'look_mode':'source_hdr',
            'phase':'new','actions':[]}
        controller=studio.Studio.__new__(studio.Studio)
        controller.store=self.store;controller.collect=lambda p:p
        with patch.object(studio,'check_asset',side_effect=self.check),self.assertRaisesRegex(ValueError,'Review and approve'):
            asyncio.run(controller.action(project,'create_look',{'request_key':'a'*36}))
        self.assertEqual(project['phase'],'new');self.assertEqual(project['actions'],[])

    def test_source_opening_stays_first_when_configured_but_uploaded_exr_keeps_anchor(self):
        source=self.make(); controller=studio.Studio.__new__(studio.Studio)
        controller.store=self.store
        for position in ("last", "frame"):
            with self.subTest(position=position):
                cfg=studio.clean_config({**self.config, "finished_frame_position":position, "finished_frame_number":17})
                project={"id":"b"*32,"source":source,"config":cfg,"phase":"opening",
                         "opening_input":{"native_hdr":{"source_id":source["id"]}}}
                with patch.object(studio,"check_asset",side_effect=self.check):
                    updated=controller.configure(project,cfg)
                self.assertEqual((updated["config"]["finished_frame_position"],updated["config"]["finished_frame_number"]),("first",1))
                project={"id":"c"*32,"source":source,"config":cfg,"phase":"opening",
                         "opening_input":{"native_hdr":{"exr_id":"d"*32}}}
                with patch.object(studio,"check_asset",side_effect=self.check):
                    updated=controller.configure(project,cfg)
                self.assertEqual((updated["config"]["finished_frame_position"],updated["config"]["finished_frame_number"]),(position,17))

    def test_original_hdr_frame_is_the_approved_appearance_and_rejects_stale_review(self):
        import torch
        native=importlib.import_module(NAME+'.hdr_native_source')
        inputs=importlib.import_module(NAME+'.ltx25_hdr_input')
        source=self.make();project={'id':'b'*32,'source':source,'config':self.config,'review':'review'}
        review={'clip':{'start':.3,'frames':24,'fps':24,'source_hash':self.sha}}
        with patch.object(native,'resample_native_hdr_frames',return_value=(torch.full((1,16,32,3),.4),24)) as loader:
            asset=hdr.make_source_opening(project,self.store,self.check,lambda _:('dir',review),lambda _:None,self.root)
        loader.assert_called_once_with(str(self.file),.3,1,24,'auto')
        self.assertEqual(asset['native_hdr']['source_id'],source['id'])
        endpoint=inputs.resolve_asset(asset,self.config,self.store,self.check)
        self.assertEqual((endpoint['kind'],endpoint['path'],endpoint['start_seconds']),('video',str(self.file),.3))
        stale={'clip':{**review['clip'],'source_hash':'0'*64}}
        with self.assertRaisesRegex(ValueError,'Review this HDR source'):
            hdr.make_source_opening(project,self.store,self.check,lambda _:('dir',stale),lambda _:None,self.root)
        self.file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):inputs.resolve_asset(asset,self.config,self.store,self.check)


class FirstFrameParityTests(unittest.TestCase):
    def test_review_seek_first_frame_matches_cfr_rule(self):
        import av
        import shutil
        ffmpeg=shutil.which('ffmpeg') or 'C:/Users/ellio/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe'
        if not Path(ffmpeg).is_file():self.skipTest('FFmpeg is not installed')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for index in range(36):
                Image.new('RGB',(32,32),(index*4,)*3).save(root/f'{index:04d}.png')
            for rate_text in ('25','30000/1001'):
                with self.subTest(rate=rate_text):
                    source=root/'source.mkv';review=root/'review.mkv'
                    subprocess.run([ffmpeg,'-loglevel','error','-y','-framerate',rate_text,'-i',str(root/'%04d.png'),
                        '-c:v','ffv1','-pix_fmt','rgb24',str(source)],check=True)
                    subprocess.run([ffmpeg,'-loglevel','error','-y','-ss','0.3','-i',str(source),'-t','0.5',
                        '-vf','setpts=PTS-STARTPTS,fps=24','-frames:v','12','-c:v','ffv1','-pix_fmt','rgb24',str(review)],check=True)
                    with av.open(str(review)) as video:
                        first=round(next(video.decode(video=0)).to_ndarray(format='rgb24')[0,0,0]/4)
                    target=Fraction('0.3')*Fraction(rate_text)
                    self.assertEqual(first,math.ceil(target))
                    self.assertNotEqual(first,math.floor(target),'The old floor selector chooses the preceding frame')


if __name__=='__main__':unittest.main()

