import importlib
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock

import test_artist_studio

module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_queue')
jobs_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_jobs')
outpaint = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
experiment = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_experiment')


class FakeQueue:
    def __init__(self): self.history = {}; self.running = []; self.pending = []; self.interrupted = []
    def get_history(self, identity): return {identity: self.history[identity]} if identity in self.history else {}
    def get_current_queue_volatile(self): return self.running, self.pending
    def interrupt_if_running(self, identity): self.interrupted.append(identity); self.running = [x for x in self.running if x[1] != identity]
    def delete_queue_item(self, predicate): self.pending = [x for x in self.pending if not predicate(x)]
    def put(self, item): self.pending.append(item)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.queue = FakeQueue()
        self.server = types.SimpleNamespace(prompt_queue=self.queue, number=0)
        self.server.trigger_on_prompt = lambda body: body
        self.server.node_replace_manager = types.SimpleNamespace(apply_replacements=lambda graph: None)
        self.client = module.ReviewedHDRQueue(self.server, self.root, client_id='artist', identity='job123',
            selection={'padded_width':192, 'padded_height':128, 'padded_frames':17}, has_audio=True, update=lambda stage: None)

    def tearDown(self): self.tmp.cleanup()

    async def test_hdr_setup_covers_both_generation_passes(self):
        with patch('folder_paths.get_full_path', return_value=None), patch('nodes.NODE_CLASS_MAPPINGS', {}):
            deps = jobs_module.hdr_expand_dependencies()
        self.assertIn('ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors', deps['missing_files'])
        self.assertIn('ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors', deps['missing_files'])
        self.assertIn('ltx-2.3-22b-ic-lora-outpaint.safetensors', deps['missing_files'])
        self.assertIn('ZuraHDRTemporalHold', deps['missing_nodes'])

    async def test_hdr_black_setup_checks_its_own_graphs_and_both_audio_cases(self):
        with patch('folder_paths.get_full_path', return_value=None), patch('nodes.NODE_CLASS_MAPPINGS', {}):
            deps = jobs_module.hdr_black_dependencies()
            long = jobs_module.hdr_long_dependencies('black')
        self.assertFalse(deps['ready'])
        self.assertIn('ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors', deps['missing_files'])
        self.assertNotIn('ltx-2.3-22b-ic-lora-outpaint.safetensors', deps['missing_files'])
        self.assertIn('ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors', deps['missing_files'])
        for node in ('ZuraLTXOutpaintHDRCanvas','ImageCompositeMasked','CropMask','EmptyAudio','ZuraHDRLoadTimedAudio'):
            self.assertIn(node, deps['missing_nodes'])
        self.assertIn('LTXVImgToVideoInplace',long['missing_nodes'])
        self.assertIn('ZuraHDRWriteChunk',long['missing_nodes'])

    async def test_hdr_black_review_dispatch_is_gated_and_checks_black_dependencies(self):
        import asyncio
        from aiohttp import web
        source={'file':'source.mp4','sha':'a'*64,'duration':10.,'width':190,'height':130,
                'asset_kind':'video','has_audio':True}
        fake=types.SimpleNamespace(lock=asyncio.Lock(),source=lambda identity:source,
            submit_hdr_review=AsyncMock(return_value={'id':'review'}),
            submit_long_hdr=AsyncMock(return_value={'id':'long-review'}))
        routes=web.RouteTableDef()
        with patch.object(jobs_module,'OutpaintJobs',return_value=fake):
            jobs_module.register(types.SimpleNamespace(),routes,lambda handler:handler)
        handlers={(entry.method,entry.path):entry.handler for entry in routes}
        body={'source':'id','hdr':True,'start':.5,'duration':.5,'mode':'black','width':190,'height':130,
              'left':0,'top':0,'right':0,'bottom':0,'black_threshold':.01,'colour_space':'pq_rec2020'}
        async def read_body():return body
        request=types.SimpleNamespace(json=read_body)
        with patch.dict('os.environ',{'ZURA_HDR_OUTPAINT_EXPERIMENT':'0'}):
            with self.assertRaisesRegex(ValueError,'not available'):
                await handlers[('POST','/zura/studio/outpaint/review')](request)
        missing={'ready':False,'missing_files':['inpaint.safetensors'],'missing_nodes':['CropMask']}
        ready={'ready':True,'missing_files':[],'missing_nodes':[]}
        with patch.dict('os.environ',{'ZURA_HDR_OUTPAINT_EXPERIMENT':'1','ZURA_HDR_OUTPAINT_LONG_EXPERIMENT':'1'}), \
             patch.object(jobs_module,'hdr_expand_dependencies',side_effect=AssertionError('wrong graph')), \
             patch.object(jobs_module,'hdr_black_dependencies',return_value=missing):
            with self.assertRaisesRegex(ValueError,'inpaint.safetensors.*CropMask'):
                await handlers[('POST','/zura/studio/outpaint/review')](request)
            self.assertEqual(fake.submit_hdr_review.await_count,0)
        with patch.dict('os.environ',{'ZURA_HDR_OUTPAINT_EXPERIMENT':'1','ZURA_HDR_OUTPAINT_LONG_EXPERIMENT':'1'}), \
             patch.object(jobs_module,'hdr_expand_dependencies',side_effect=AssertionError('wrong graph')), \
             patch.object(jobs_module,'hdr_black_dependencies',return_value=ready), \
             patch.object(jobs_module,'hdr_long_dependencies',return_value=ready) as long_deps:
            await handlers[('POST','/zura/studio/outpaint/review')](request)
            selected=fake.submit_hdr_review.await_args.args[1]
            self.assertEqual((selected['mode'],selected['black_threshold'],selected['width'],selected['height']),('black',.01,190,130))
            body['strategy']='hdr_long';body['duration']=5.
            await handlers[('POST','/zura/studio/outpaint/review')](request)
            long_deps.assert_called_once_with('black')
            selected=fake.submit_long_hdr.await_args.args[2]
            self.assertEqual((selected['mode'],selected['black_threshold'],selected['width'],selected['height']),('black',.01,190,130))

    async def test_success_validates_both_artifacts_before_return(self):
        stage = self.root / 'stage.mp4'; stage.write_bytes(b'video')
        self.queue.history['a'] = {'status': {'status_str':'success'}, 'outputs': {'stage_save': {'images':[{'filename':'stage'}]}}}
        self.queue.history['b'] = {'status': {'status_str':'success'}, 'outputs': {'final': 'metadata'}}
        with patch.object(module, 'checked_stage', return_value=stage) as check_stage, patch.object(module, 'checked_delivery', return_value={'hlg':'verified'}) as check_final:
            self.assertEqual(await self.client.wait('outpaint', 'a'), str(stage))
            self.assertEqual(await self.client.wait('hdr', 'b'), {'hlg':'verified'})
            self.assertEqual(check_stage.call_args.kwargs['frames'],17)
            self.assertTrue(check_final.call_args.kwargs['has_audio'])
        await self.client.cleanup(stage)
        self.assertFalse(stage.exists())

    async def test_failed_pass_and_unowned_cleanup(self):
        self.queue.history['bad'] = {'status': {'status_str':'error'}}
        with self.assertRaisesRegex(ValueError, 'did not complete'): await self.client.wait('hdr','bad')
        self.queue.history['bad']['status']['messages']=[['execution_error',{'exception_message':'HDR adapter missing'}]]
        with self.assertRaisesRegex(ValueError,'HDR adapter missing'):await self.client.wait('hdr','bad')
        unrelated = self.root / 'unrelated.mp4'; unrelated.write_bytes(b'video')
        await self.client.cleanup(unrelated)
        self.assertTrue(unrelated.exists())

    async def test_cancel_only_matching_prompt(self):
        self.queue.running = [(0, 'ours', {}), (1, 'other', {})]
        self.queue.pending = [(2, 'ours', {}), (3, 'other', {})]
        await self.client.cancel('ours')
        self.assertEqual([v[1] for v in self.queue.running], ['other'])
        self.assertEqual([v[1] for v in self.queue.pending], ['other'])
        self.assertEqual(self.queue.interrupted, ['ours'])

    async def test_submit_routes_progress_to_requesting_client(self):
        async def validate(identity, graph, extra): return (True, None, ['save'], {})
        with patch.dict('sys.modules', {'execution': types.SimpleNamespace(validate_prompt=validate)}):
            identity = await self.client.submit('outpaint', {'save': {'class_type':'SaveVideo', 'inputs':{}}})
        self.assertEqual(self.queue.pending[0][1], identity)
        self.assertEqual(self.queue.pending[0][3]['client_id'], 'artist')
        self.assertEqual(self.queue.pending[0][4], ['save'])

    async def test_private_job_requires_review_and_publishes_checked_result(self):
        source = {'file':'source.mp4', 'sha':'a'*64, 'duration':4, 'width':128, 'height':128, 'asset_kind':'video'}
        selection = outpaint.plan(source, start=.517, duration=.5, mode='expand', width=192, height=192,
                                  left=32, right=32, top=32, bottom=32)
        key = experiment.hdr_review_key(selection, 'pq_rec2020')
        review = {'kind':'review', 'state':'complete', 'approved':True, 'source':source, 'hdr_review_key':key}
        instance = jobs_module.OutpaintJobs(types.SimpleNamespace(server=self.server))
        result_paths = {name:self.root/'genj'/'hdr'/filename for name,filename in
                        [('hlg','final.mp4'),('preview','preview.mp4'),('exr','frames.zip')]}
        class Adapter:
            def __init__(self, *args, **kwargs): self.update = kwargs['update']
            async def run(self, **kwargs): self.update('hdr'); return result_paths
        with patch.object(jobs_module, 'check_asset', return_value=None), patch.object(module, 'ReviewedHDRQueue', Adapter), patch('folder_paths.get_output_directory', return_value=str(self.root)):
            with self.assertRaisesRegex(ValueError, 'approve'):
                await instance.submit_reviewed_hdr(source, selection, {**review,'approved':False}, colour_space='pq_rec2020', has_audio=True)
            public = await instance.submit_reviewed_hdr(source, selection, review, colour_space='pq_rec2020', has_audio=True)
            job = instance.jobs[public['id']]
            await job['task']
            self.assertEqual(instance.state(public['id'])['state'], 'complete')
            self.assertEqual(job['hdr_files']['exr']['filename'], 'frames.zip')
            self.assertEqual(job['artifact']['filename'], 'final.mp4')

    async def test_hdr_review_queues_bound_preview_and_rejects_colour_change(self):
        source = {'file':'source.mp4', 'sha':'a'*64, 'duration':4, 'width':128, 'height':128, 'asset_kind':'video'}
        selection = outpaint.plan(source, start=.517, duration=.5, mode='expand', width=192, height=192,
                                  left=32, right=32, top=32, bottom=32)
        instance = jobs_module.OutpaintJobs(types.SimpleNamespace(server=self.server))
        async def validate(identity, graph, extra): return (True, None, ['save'], {})
        with patch.dict('sys.modules', {'execution':types.SimpleNamespace(validate_prompt=validate)}), patch.object(jobs_module, 'check_asset', return_value=None):
            public = await instance.submit_hdr_review(source, selection, colour_space='pq_rec2020', client_id='artist')
            identity = public['id']
            self.assertEqual(self.queue.pending[-1][1], identity)
            self.assertEqual(self.queue.pending[-1][3]['client_id'], 'artist')
            self.queue.history[identity] = {'status':{'status_str':'success'}, 'outputs':{'save':{'images':[{
                'type':'output','subfolder':'genj/hdr_outpaint','filename':identity+'_00001_.mp4'}]}}}
            review = instance.state(identity)
            self.assertEqual(review['state'], 'complete')
            review['approved'] = True
            with self.assertRaisesRegex(ValueError, 'approve'):
                await instance.submit_reviewed_hdr(source, selection, review, colour_space='hlg_rec2020', has_audio=False)

    async def test_hdr_http_route_is_opt_in_and_detects_source_audio(self):
        from aiohttp import web
        source = {'file':'source.mp4', 'sha':'a'*64, 'duration':4, 'width':128, 'height':128, 'asset_kind':'video'}
        selection = outpaint.plan(source, start=.5, duration=.5, mode='expand', width=192, height=192,
                                  left=32, right=32, top=32, bottom=32)
        review = {'kind':'review', 'state':'complete', 'approved':True, 'source':source,
                  'selection':selection, 'hdr_review_key':'bound', 'hdr_colour_space':'pq_rec2020'}
        fake = types.SimpleNamespace(lock=__import__('asyncio').Lock(), source=lambda identity:source,
            state=lambda identity:review, public=lambda value:value,
            submit_hdr_review=AsyncMock(return_value={'id':'review'}),
            submit_reviewed_hdr=AsyncMock(return_value={'id':'render'}),
            submit_long_hdr=AsyncMock(return_value={'id':'long-review'}))
        routes = web.RouteTableDef()
        with patch.object(jobs_module, 'OutpaintJobs', return_value=fake):
            jobs_module.register(types.SimpleNamespace(), routes, lambda handler:handler)
        handlers = {(entry.method, entry.path):entry.handler for entry in routes}
        body = {'source':'id','hdr':True,'start':.5,'duration':.5,'mode':'expand','width':192,'height':192,
                'left':32,'top':32,'right':32,'bottom':32,'black_threshold':2/255,'colour_space':'pq_rec2020'}
        async def read_body(): return body
        request = types.SimpleNamespace(json=read_body, match_info={'identity':'review'})
        with patch.dict('os.environ', {'ZURA_HDR_OUTPAINT_EXPERIMENT':'0'}):
            with self.assertRaisesRegex(ValueError, 'not available'):
                await handlers[('POST','/zura/studio/outpaint/review')](request)
        with patch.dict('os.environ', {'ZURA_HDR_OUTPAINT_EXPERIMENT':'1'}), patch.object(jobs_module, 'source_has_audio', return_value=True), patch.object(jobs_module, 'hdr_expand_dependencies', return_value={'ready':True,'missing_files':[],'missing_nodes':[]}):
            await handlers[('POST','/zura/studio/outpaint/review')](request)
            self.assertEqual(fake.submit_hdr_review.await_count, 1)
            body = {'prompt':'extend', 'seed':42, 'has_audio':False}
            await handlers[('POST','/zura/studio/outpaint/jobs/{identity}/render')](request)
            self.assertTrue(fake.submit_reviewed_hdr.await_args.kwargs['has_audio'], 'audio is detected from the source, not the request')
        body={'source':'id','hdr':True,'strategy':'hdr_long','start':.5,'duration':.5,'mode':'expand','width':192,'height':192,
              'left':32,'top':32,'right':32,'bottom':32,'black_threshold':2/255,'colour_space':'pq_rec2020'}
        with patch.dict('os.environ',{'ZURA_HDR_OUTPAINT_EXPERIMENT':'1','ZURA_HDR_OUTPAINT_LONG_EXPERIMENT':'0'}):
            with self.assertRaisesRegex(ValueError,'Long HDR'):
                await handlers[('POST','/zura/studio/outpaint/review')](request)
        with patch.dict('os.environ',{'ZURA_HDR_OUTPAINT_EXPERIMENT':'1','ZURA_HDR_OUTPAINT_LONG_EXPERIMENT':'1'}), patch.object(jobs_module,'hdr_long_dependencies',return_value={'ready':True,'missing_files':[],'missing_nodes':[]}):
            await handlers[('POST','/zura/studio/outpaint/review')](request)
            self.assertEqual(fake.submit_long_hdr.await_count,1)

    async def test_job_handoff_validates_real_hdr_files(self):
        benchmark = Path(__file__).resolve().parents[2] / 'openjutsu-benchmark'
        out = benchmark / 'hdr-shared-long' / 'output' / 'genj'
        files = [out/'hdr_outpaint'/'sdr_first_precise9_00001_.mp4',
                 out/'hdr'/'sdrfirst_hdr_precise9_00001_.mp4',
                 out/'hdr'/'sdrfirst_hdr_precise9_preview_00001_.mp4',
                 out/'hdr'/'sdrfirst_hdr_precise9.zip']
        if not all(path.is_file() for path in files) or not shutil.which('ffprobe'):
            self.skipTest('Local HDR test render and ffprobe are required.')
        source = {'file':'source.mp4', 'sha':'a'*64, 'duration':1.5015, 'width':1920, 'height':1080, 'asset_kind':'video'}
        selection = outpaint.plan(source, start=.517, duration=9/24, mode='expand', width=1088, height=640,
                                  left=128, right=128, top=96, bottom=96)
        key = experiment.hdr_review_key(selection, 'pq_rec2020')
        review = {'kind':'review', 'state':'complete', 'approved':True, 'source':source, 'hdr_review_key':key}
        instance = jobs_module.OutpaintJobs(types.SimpleNamespace(server=self.server))
        async def submit(adapter, stage, graph):
            folder = self.root/'genj'/('hdr_outpaint' if stage=='outpaint' else 'hdr'); folder.mkdir(parents=True,exist_ok=True)
            ident = adapter.identity
            def ref(name): return {'type':'output','subfolder':'genj/'+folder.name,'filename':name}
            if stage=='outpaint':
                name = ident+'_00001_.mp4'; shutil.copyfile(files[0],folder/name)
                outputs = {'stage_save':{'images':[ref(name)]}}
            else:
                names = ['hdr_outpaint_'+ident+'_00001_.mp4','hdr_outpaint_'+ident+'_preview_00001_.mp4','hdr_outpaint_'+ident+'.zip']
                for source_file,name in zip(files[1:],names): shutil.copyfile(source_file,folder/name)
                outputs = {'zura_hdr_save_video':{'images':[ref(names[0])]},'zura_hdr_save_preview':{'images':[ref(names[1])]},'zura_hdr_archive':{'files':[ref(names[2])]}}
            prompt_id=stage+'-fixture'; self.queue.history[prompt_id]={'status':{'status_str':'success'},'outputs':outputs}
            adapter.on_prompt(prompt_id)
            return prompt_id
        with patch.object(jobs_module,'check_asset',return_value=None), patch('folder_paths.get_output_directory',return_value=str(self.root)), patch.object(module.ReviewedHDRQueue,'submit',submit):
            public = await instance.submit_reviewed_hdr(source,selection,review,colour_space='pq_rec2020',has_audio=True)
            job=instance.jobs[public['id']];await job['task']
            self.assertEqual(job['state'],'complete',job.get('error'))
            self.assertEqual(job['hdr_files']['hlg']['type'],'output')
            self.assertFalse((self.root/'genj'/'hdr_outpaint'/(public['id']+'_00001_.mp4')).exists(),'owned intermediate is cleaned after validation')
            self.assertTrue((self.root/'genj'/'hdr'/job['hdr_files']['exr']['filename']).is_file())

    async def test_long_hdr_reports_current_conversion_section(self):
        class Controller:
            def snapshot(self):return {'stage':'converting_hdr','active_prompt_id':'child','hdr':{'completed':1,'total':3}}
        instance=jobs_module.OutpaintJobs(types.SimpleNamespace(server=self.server))
        instance.jobs['running']={'id':'running','state':'running','long':True,'hdr_controller':Controller(),'windows':3}
        status=instance.state('running')
        self.assertEqual(status['window'],2)
        self.assertEqual(status['windows'],3)
        self.assertEqual(status['active_prompt_id'],'child')

    async def test_long_hdr_job_requires_full_review(self):
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection={'review_key':'abc','colour_space':'pq_rec2020'}
        instance=jobs_module.OutpaintJobs(types.SimpleNamespace(server=self.server))
        with self.assertRaisesRegex(ValueError,'approve'):
            await instance.submit_long_hdr('render',source,selection,reviewed={'approved':False})
        folder=self.root/'genj'/'hdr';folder.mkdir(parents=True)
        exr=folder/'result.zip';hlg=folder/'result.mp4';preview=folder/'preview.mp4'
        for path in (exr,hlg,preview):path.write_bytes(b'fixture')
        class Controller:
            conversion_details={'id':'owned','width':192,'height':128,'frames':9,'has_audio':True}
            def snapshot(self):return {'stage':'converting_hdr','active_prompt_id':'child','hdr':{'completed':1,'total':2}}
            async def run(self):return {'files':[str(exr),str(hlg)],'preview':str(preview)}
        def factory(*args,**kwargs):return Controller(),{'id':'longjob','sections':2}
        review={'kind':'review','state':'complete','approved':True,'hdr_long':True,'source':source,'selection':selection}
        with patch('folder_paths.get_output_directory',return_value=str(self.root)), patch('folder_paths.get_input_directory',return_value=str(self.root)), patch('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_comfy.create_long_hdr_outpaint_job',factory), patch('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_artifacts.checked_long_delivery',return_value={'hlg':hlg,'preview':preview,'exr':exr}):
            public=await instance.submit_long_hdr('render',source,selection,reviewed=review)
            job=instance.jobs[public['id']];await job['task']
            self.assertEqual(job['state'],'complete');self.assertEqual(job['stage'],'complete');self.assertIsNone(job['active_prompt_id']);self.assertEqual(job['hdr_files']['exr']['filename'],'result.zip')
