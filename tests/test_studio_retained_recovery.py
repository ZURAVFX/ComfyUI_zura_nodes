"""Exact-source retained image recovery; real files, no model or AE process."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import float_io
from comfylink.frame_contract import prepare_frame_contract_graph
from comfylink import studio_recovery
from comfylink.studio_recovery import retained_images, MAX_HISTORY, MAX_CANDIDATES, MAX_SOURCE_CHECKS
from comfylink.studio_sessions import StudioSessions, Session, register, PREFIX, SESSION_HEADER, _image_container


class Files:
    def __init__(self, root):
        self.input, self.output = root/'input', root/'output'
        self.input.mkdir(); self.output.mkdir(); (self.output/'zura_images').mkdir()
        self.current, self.old = 'a'*32, 'b'*32
        self.pixels = np.array([[[[-.25, 2., .375, .5], [4., -.5, .1234567, 0]],
                                 [[.2, .3, .4, 1], [.5, .6, .7, .25]]]], dtype=np.float32)
        self.options = dict(colour={'encoding':'unknown','sceneLinear':False},
            frame_rate={'numerator':30000,'denominator':1001}, source_start={'numerator':7007,'denominator':30000})
        _, self.manifest = self.write(self.current)
        self.write(self.old)
        self.service = StudioSessions(input_root=self.input, output_root=self.output)
        self.history = {'prompt-one': self.entry(self.old)}

    def write(self, identity, **changes):
        return float_io.write_transfer(self.input, 'ComfyLink/'+identity, self.pixels, **{**self.options, **changes})

    def entry(self, identity, filename='retained.png', number=1):
        path = self.output/'zura_images'/filename
        if not path.exists(): Image.new('RGB',(2,2),(210,80,40)).save(path)
        contract={'schemaVersion':1,'frameCount':1,'modelFrames':1,'trimFrames':1,'width':2,'height':2,
                  'frameRate':self.options['frame_rate'],'sessionId':identity}
        graph=prepare_frame_contract_graph({'load':{'class_type':'LoadImage','inputs':{'image':'input.png'}},
            'save':{'class_type':'SaveImage','inputs':{'images':['load',0],'filename_prefix':'zura_images/retained'}}},contract,'image')
        return {'prompt':[number,'prompt-one',graph,{'zura_image':True,'ae_frame_contract':contract},['save']],
                'status':{'completed':True,'status_str':'success'},
                'outputs':{'save':{'images':[{'filename':filename,'subfolder':'zura_images','type':'output',
                    'metadata':{'kind':'image','width':2,'height':2},'id':'display-asset-id','role':'image'}]}}}

    def find(self, history=None):
        return retained_images(self.input,self.current,self.manifest,self.history if history is None else history,
            self.service.resolve_master,lambda path:_image_container(path,'.png'),self.output)

    def saved_png(self, *, folder='zura_images', filename='klein9b_00009_.png', prefix=None, change=None, raw=None, compressed=False):
        entry=self.entry(self.old,filename)
        graph=entry['prompt'][2]
        graph['save']['inputs']['filename_prefix']=prefix or folder+'/klein9b'
        if change:change(graph)
        meta=PngInfo();meta.add_text('prompt',json.dumps(graph) if raw is None else raw,zip=compressed)
        path=self.output/folder/filename;path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(2,2),(210,80,40)).save(path,pnginfo=meta)
        entry['outputs']['save']['images'][0]['subfolder']=folder
        return path,entry


class RecoveryFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.f=Files(Path(self.temp.name))
    def tearDown(self): self.temp.cleanup()

    def test_exact_original_float_source_recovers_clean_reference_without_mutation(self):
        f=self.f; before=copy.deepcopy(f.history)
        original=(f.input/'ComfyLink'/f.current/'000001.rgba32f').read_bytes()
        found=f.find()
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['master'],{'filename':'retained.png','subfolder':'zura_images','type':'output'})
        self.assertEqual(found[0]['frameRate'],{'numerator':30000,'denominator':1001})
        self.assertEqual(found[0]['sourceManifestSha256'],hashlib.sha256(float_io.canonical_manifest_bytes(f.manifest)).hexdigest())
        self.assertEqual(f.history,before)
        self.assertEqual((f.input/'ComfyLink'/f.current/'000001.rgba32f').read_bytes(),original)

    def test_changed_source_pixels_cadence_colour_or_source_start_are_not_offered(self):
        f=self.f
        for i,changes in enumerate([
            {'frame_rate':{'numerator':25,'denominator':1}},
            {'source_start':{'numerator':8008,'denominator':30000}},
            {'colour':{'encoding':'acescg','sceneLinear':True}},
        ],3):
            identity=format(i,'032x');f.write(identity,**changes)
            self.assertEqual(f.find({'old':f.entry(identity)}),[])
        raw=f.input/'ComfyLink'/f.old/'000001.rgba32f'; raw.write_bytes(b'\0'*raw.stat().st_size)
        self.assertEqual(f.find(),[])
        current=f.input/'ComfyLink'/f.current/'000001.rgba32f';current.write_bytes(b'\0'*current.stat().st_size)
        with self.assertRaises(ValueError):f.find()

    def test_only_successful_guarded_final_image_history_is_eligible(self):
        f=self.f
        mutations=[lambda e:e['status'].update(completed=False),lambda e:e['status'].update(status_str='error'),
            lambda e:e['prompt'][3].update(zura_image=False),
            lambda e:e['prompt'][3].update(ae_intermediate_image={'kind':'ripple_keyframe'}),
            lambda e:e['prompt'][3]['ae_frame_contract'].update(ae_intermediate_image={}),
            lambda e:e['prompt'][2]['save'].update(class_type='PreviewImage'),
            lambda e:e['prompt'][2]['save']['inputs'].update(images=['load',0]),
            lambda e:e['outputs']['save']['images'].append(copy.deepcopy(e['outputs']['save']['images'][0]))]
        for mutate in mutations:
            entry=copy.deepcopy(f.history['prompt-one']);mutate(entry)
            self.assertEqual(f.find({'bad':entry}),[])

    def test_traversal_intermediate_missing_wrong_raster_and_hardlinks_are_rejected(self):
        f=self.f
        for change in [{'filename':'../retained.png'},{'subfolder':'../zura_images'},
                       {'subfolder':'ComfyLink/intermediate/'+f.old+'/guide'}, {'type':'input'},
                       {'filename':'missing.png'}]:
            entry=copy.deepcopy(f.history['prompt-one']);entry['outputs']['save']['images'][0].update(change)
            self.assertEqual(f.find({'bad':entry}),[])
        image=f.output/'zura_images/retained.png';Image.new('RGB',(3,2)).save(image)
        self.assertEqual(f.find(),[])
        Image.new('RGB',(2,2)).save(image);os.link(image,f.output/'zura_images/linked.png')
        self.assertEqual(f.find(),[])

    def test_bounds_and_newest_first_do_not_scan_unbounded_sources(self):
        f=self.f;history={}
        for i in range(12):
            identity=format(100+i,'032x');f.write(identity)
            history['prompt-'+str(i)]=f.entry(identity,'result-'+str(i)+'.png',i)
        with patch.object(float_io,'verify_transfer',wraps=float_io.verify_transfer) as verify:
            found=f.find(history)
        self.assertEqual(len(found),MAX_CANDIDATES)
        self.assertEqual(found[0]['master']['filename'],'result-11.png')
        self.assertLessEqual(verify.call_count,MAX_SOURCE_CHECKS+1)
        oversized={'outside-limit':f.history['prompt-one'],**{str(i):{} for i in range(MAX_HISTORY)}}
        self.assertEqual(f.find(oversized),[])

    def test_restart_empty_history_uses_saved_png_only_after_exact_source_verification(self):
        f=self.f;path,entry=f.saved_png()
        original=path.read_bytes();source=(f.input/'ComfyLink'/f.current/'000001.rgba32f').read_bytes()
        from_history=f.find({'prompt-one':entry})
        recovered=f.find({})
        self.assertEqual(len(recovered),1)
        self.assertEqual(recovered,from_history,'Candidate identity survives loss of the in-memory prompt ID')
        self.assertEqual(recovered[0]['master'],{'filename':path.name,'subfolder':'zura_images','type':'output'})
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual((f.input/'ComfyLink'/f.current/'000001.rgba32f').read_bytes(),source)
        (f.input/'ComfyLink'/f.old/'000001.rgba32f').write_bytes(b'\0'*f.pixels.nbytes)
        self.assertEqual(f.find({}),[],'Embedded metadata never replaces the original FLOAT byte check')

    def test_saved_png_accepts_the_second_native_root_and_rejects_forged_guard_or_prefix(self):
        f=self.f
        path,_=f.saved_png(folder='ZURA STUDIO/images')
        self.assertEqual(f.find({})[0]['master']['subfolder'],'ZURA STUDIO/images')
        path.unlink()
        mutations=[
            lambda g:g['save'].update(class_type='PreviewImage'),
            lambda g:g['save']['inputs'].update(images=['load',0]),
            lambda g:g['save'].update(_meta={'ae_intermediate_image':{}}),
            lambda g:g['zura_ae_match_frames_0']['inputs'].update(frame_count=2),
            lambda g:g['zura_ae_match_frames_0']['inputs'].update(width=3),
            lambda g:g['zura_ae_match_frames_0']['inputs'].update(metadata=json.dumps({**json.loads(g['zura_ae_match_frames_0']['inputs']['metadata']),'ae_intermediate_image':{}})),
            lambda g:g['save']['inputs'].update(filename_prefix='zura_images/../klein9b'),
            lambda g:g['save']['inputs'].update(filename_prefix='ComfyLink/intermediate/'+f.old+'/klein9b'),
            lambda g:g['save']['inputs'].update(filename_prefix='zura_images/not-this-file'),
        ]
        for change in mutations:
            path,_=f.saved_png(change=change)
            self.assertEqual(f.find({}),[])
            path.unlink()

    def test_saved_png_rejects_oversized_compressed_or_duplicate_json_and_source_time_changes(self):
        f=self.f
        path,_=f.saved_png(compressed=True);self.assertEqual(f.find({}),[]);path.unlink()
        path,_=f.saved_png(raw=' '* (studio_recovery.MAX_PROMPT_BYTES+1));self.assertEqual(f.find({}),[]);path.unlink()
        path,_=f.saved_png(raw='{"save":{},"save":{}}');self.assertEqual(f.find({}),[]);path.unlink()
        path,_=f.saved_png()
        old=f.input/'ComfyLink'/f.old/'manifest.json';manifest=json.loads(old.read_text())
        manifest['sourceStart']={'numerator':8008,'denominator':30000};old.write_bytes(float_io.canonical_manifest_bytes(manifest))
        self.assertEqual(f.find({}),[])

    def test_saved_png_limits_metadata_reads_and_never_promotes_known_failed_history(self):
        f=self.f
        for i in range(6):f.saved_png(filename=f'klein9b_{i:05d}_.png')
        with patch.object(studio_recovery,'MAX_METADATA_READS',2),patch.object(studio_recovery,'_png_prompt',wraps=studio_recovery._png_prompt) as read:
            found=f.find({})
        self.assertEqual(read.call_count,2);self.assertLessEqual(len(found),2)
        failed=copy.deepcopy(f.history['prompt-one']);failed['status']['status_str']='error'
        self.assertEqual(f.find({'failed':failed}),[])


class RecoveryHTTPTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.f=Files(Path(self.temp.name));self.reads=[]
        def read(limit):self.reads.append(limit);return self.f.history
        self.server=types.SimpleNamespace(routes=web.RouteTableDef(),prompt_queue=types.SimpleNamespace(get_history=lambda **kw:read(kw['max_items'])))
        self.service=register(self.server,input_root=self.f.input,output_root=self.f.output)
        app=web.Application();app.add_routes(self.server.routes)
        self.client=TestClient(TestServer(app,host='127.0.0.1'));await self.client.start_server()
        origin=str(self.client.make_url('/')).rstrip('/')
        self.session=Session(self.f.current,'c'*64,'http://127.0.0.1:1/studio-bridge/'+'d'*32,'e'*64,origin,
                             {'capabilities':{'source':True,'transfer':True}},time.time()+600)
        self.session.source={'manifest':self.f.manifest}
        self.service.sessions[self.session.id]=self.session
        self.url=PREFIX+'/sessions/'+self.session.id+'/retained-images'
        self.headers={SESSION_HEADER:self.session.capability}
    async def asyncTearDown(self):
        await self.client.close();self.temp.cleanup()

    async def test_authentication_source_and_bounded_shape_before_history(self):
        response=await self.client.post(self.url,json={})
        self.assertEqual(response.status,403);self.assertEqual(self.reads,[])
        response=await self.client.post(self.url,json={'filename':'retained.png'},headers=self.headers)
        self.assertEqual(response.status,400);self.assertEqual(self.reads,[])
        self.session.source={}
        response=await self.client.post(self.url,json={},headers=self.headers)
        self.assertEqual(response.status,409);self.assertEqual(self.reads,[])

    async def test_recheck_candidate_and_keep_transfer_a_separate_action(self):
        response=await self.client.post(self.url,json={},headers=self.headers)
        self.assertEqual(response.status,200);body=await response.json();candidate=body['results'][0]
        self.assertEqual(self.reads,[MAX_HISTORY]);self.assertNotIn(self.session.capability,json.dumps(body));self.assertNotIn(self.session.token,json.dumps(body))
        response=await self.client.post(self.url,json={'candidateId':candidate['id']},headers=self.headers)
        self.assertEqual(response.status,200);self.assertEqual((await response.json())['result'],candidate)
        self.assertEqual(self.session.result_files,[]);self.assertEqual(self.session.download_capability,'')
        Image.new('RGB',(2,2),(1,2,3)).save(self.f.output/'zura_images/retained.png')
        response=await self.client.post(self.url,json={'candidateId':candidate['id']},headers=self.headers)
        self.assertEqual(response.status,409)

    async def test_departure_during_lookup_cannot_publish_a_recovery(self):
        started,release=threading.Event(),threading.Event()
        def read(limit):started.set();release.wait(2);return self.f.history
        self.service.history_reader=read
        pending=asyncio.create_task(self.client.post(self.url,json={},headers=self.headers))
        await asyncio.to_thread(started.wait,2)
        self.service.close_local(self.session);release.set()
        response=await pending;self.assertEqual(response.status,410)

    async def test_empty_history_restart_rechecks_saved_png_before_selection(self):
        self.f.saved_png();self.f.history={}
        response=await self.client.post(self.url,json={},headers=self.headers)
        self.assertEqual(response.status,200);candidate=(await response.json())['results'][0]
        response=await self.client.post(self.url,json={'candidateId':candidate['id']},headers=self.headers)
        self.assertEqual(response.status,200)
        self.assertEqual(self.session.result_files,[],'Selecting recovery does not send or regenerate anything')
        Image.new('RGB',(2,2),(1,2,3)).save(self.f.output/'zura_images/klein9b_00009_.png')
        response=await self.client.post(self.url,json={'candidateId':candidate['id']},headers=self.headers)
        self.assertEqual(response.status,409)


if __name__=='__main__':unittest.main()
