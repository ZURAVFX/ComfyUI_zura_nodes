"""Cache invalidation, bounded memory handoff and camera stage transitions."""
import asyncio
import tempfile
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import test_artist_studio as fixtures

s = fixtures.studio
from ComfyUI_zura_nodes.artist_studio.memory_policy import release_policy


class EfficiencyTests(fixtures.unittest.TestCase):
    def test_memory_policy_preserves_reusable_models_only_with_headroom(self):
        memory = types.SimpleNamespace(total=64*1024**3, available=24*1024**3)
        p = {'actions': [{'stage':'ltx25_stage1','state':'complete','next_stage':'ltx25_cleanup'},
                         {'stage':'ltx25_cleanup','next_stage':'ltx25_upscale'}],
             'ltx25_run': {'next_phase':'upscale'}}
        for previous, following in [('stage1','upscale'),('upscale','refine'),('refine','decode')]:
            p['actions'][0]['stage']='ltx25_'+previous
            p['actions'][1]['next_stage']='ltx25_'+following
            p['ltx25_run']['next_phase']=following
            with self.subTest(previous=previous):
                self.assertEqual(release_policy(p, memory), {'unload_models':False,
                    'purge_cache':False,'reason':'reuse_model_cache'})
        memory.available = 2*1024**3
        self.assertEqual(release_policy(p, memory)['reason'], 'system_memory_pressure')
        self.assertTrue(release_policy(p, memory)['unload_models'])
        memory.available = 24*1024**3
        for stage in ('ltx25_text','ltx25_motion', 'wan_prepare', 'wan_speech', 'design'):
            p['actions'][0]['stage'] = stage
            self.assertTrue(release_policy(p, memory)['purge_cache'])
            self.assertTrue(release_policy(p, memory)['unload_models'])

    def test_ambiguous_or_invalid_records_keep_conservative_release(self):
        memory = types.SimpleNamespace(total=64*1024**3, available=24*1024**3)
        previous={'stage':'ltx25_stage1','state':'complete','next_stage':'ltx25_cleanup'}
        handoff={'stage':'ltx25_cleanup','next_stage':'ltx25_upscale'}
        p={'actions':[previous,handoff],'ltx25_run':{'next_phase':'upscale'}}
        for mutate in (lambda:handoff.pop('next_stage',None),
                       lambda:handoff.update(next_stage='ltx25_refine'),
                       lambda:p.pop('ltx25_run',None),
                       lambda:p.update(ltx25_run={'next_phase':'decode'}),
                       lambda:previous.update(state='running'),
                       lambda:previous.pop('next_stage',None)):
            previous.update(stage='ltx25_stage1',state='complete',next_stage='ltx25_cleanup')
            handoff.update(stage='ltx25_cleanup',next_stage='ltx25_upscale')
            p['ltx25_run']={'next_phase':'upscale'}
            mutate()
            self.assertTrue(release_policy(p,memory)['unload_models'])
            self.assertTrue(release_policy(p,memory)['purge_cache'])
        previous.update(state='complete',next_stage='ltx25_cleanup')
        handoff['next_stage']='ltx25_upscale';p['ltx25_run']={'next_phase':'upscale'}
        for bad in (None, float('nan'), float('inf'), -1, True):
            memory.available=bad
            self.assertEqual(release_policy(p,memory)['reason'],'memory_unavailable')

    def test_reuse_waits_for_foreign_flags_then_queues_the_cpu_marker_once(self):
        from test_ltx25_studio_runtime import RuntimeTests, example
        p,_=example();controller=RuntimeTests().controller();queue=controller.server.prompt_queue
        p['actions']=[{'stage':'ltx25_stage1','state':'complete','next_stage':'ltx25_cleanup'},
            {'id':'cleanup','stage':'ltx25_cleanup','state':'waiting','next_stage':'ltx25_upscale',
             'graph':{'ack':{}},'output_nodes':['ack']}]
        p['ltx25_run']['next_phase']='upscale'
        memory=types.SimpleNamespace(total=64*1024**3,available=24*1024**3)
        # We cannot change flags while another job is pending.
        queue.pending=[(0,'other')]
        with patch('psutil.virtual_memory',return_value=memory):controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{});self.assertEqual(queue.submitted,[])
        queue.pending=[]
        # An independently requested release must be honoured, never cleared.
        queue.flags={'free_memory':True}
        with patch('psutil.virtual_memory',return_value=memory):controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{'free_memory':True})
        self.assertFalse(p['actions'][-1]['memory_policy']['unload_models'])
        controller.advance_wan_cleanup(p)
        self.assertEqual(queue.submitted,[])
        queue.flags={}
        with patch('psutil.virtual_memory',return_value=memory):controller.advance_wan_cleanup(p)
        self.assertEqual(len(queue.submitted),1)
        self.assertEqual(queue.submitted[0][1],'cleanup')
        self.assertEqual(p['actions'][-1]['state'],'queued')

    def test_no_release_flags_do_not_stall_a_compatible_handoff(self):
        from test_ltx25_studio_runtime import RuntimeTests, example
        p,_=example();controller=RuntimeTests().controller();queue=controller.server.prompt_queue
        p['actions']=[{'stage':'ltx25_upscale','state':'complete','next_stage':'ltx25_cleanup'},
            {'id':'cleanup','stage':'ltx25_cleanup','state':'waiting','next_stage':'ltx25_refine',
             'graph':{'ack':{}},'output_nodes':['ack']}]
        p['ltx25_run']['next_phase']='refine'
        memory=types.SimpleNamespace(total=64*1024**3,available=24*1024**3)
        with patch('psutil.virtual_memory',return_value=memory):controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{})
        self.assertEqual(queue.submitted,[])
        with patch('psutil.virtual_memory',return_value=memory):controller.advance_wan_cleanup(p)
        self.assertEqual(len(queue.submitted),1)
        self.assertEqual(p['actions'][-1]['state'],'queued')

    def test_memory_pressure_still_requests_complete_release(self):
        from test_ltx25_studio_runtime import RuntimeTests, example
        p,_=example();controller=RuntimeTests().controller();queue=controller.server.prompt_queue
        p['actions']=[{'stage':'ltx25_stage1','state':'complete','next_stage':'ltx25_cleanup'},
            {'id':'cleanup','stage':'ltx25_cleanup','state':'waiting','next_stage':'ltx25_upscale',
             'graph':{'ack':{}},'output_nodes':['ack']}]
        p['ltx25_run']['next_phase']='upscale'
        with patch('psutil.virtual_memory',return_value=types.SimpleNamespace(total=64*1024**3,available=2*1024**3)):
            controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{'unload_models':True,'free_memory':True})
        controller.advance_wan_cleanup(p)
        self.assertEqual(queue.submitted,[])

    def test_memory_is_rechecked_after_a_wait_before_reusing_models(self):
        from test_ltx25_studio_runtime import RuntimeTests, example
        p,_=example();controller=RuntimeTests().controller();queue=controller.server.prompt_queue
        p['actions']=[{'stage':'ltx25_stage1','state':'complete','next_stage':'ltx25_cleanup'},
            {'id':'cleanup','stage':'ltx25_cleanup','state':'waiting','next_stage':'ltx25_upscale',
             'graph':{'ack':{}},'output_nodes':['ack']}]
        p['ltx25_run']['next_phase']='upscale'
        generous=types.SimpleNamespace(total=64*1024**3,available=24*1024**3)
        pressured=types.SimpleNamespace(total=64*1024**3,available=2*1024**3)
        with patch('psutil.virtual_memory',return_value=generous):controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{})
        queue.running=[(0,'another-job')]
        with patch('psutil.virtual_memory',return_value=pressured):controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{})
        queue.running=[]
        with patch('psutil.virtual_memory',return_value=pressured):controller.advance_wan_cleanup(p)
        self.assertEqual(queue.flags,{'unload_models':True,'free_memory':True})
        self.assertEqual(queue.submitted,[])

    def test_store_reuses_unchanged_records_but_detects_external_edits(self):
        with tempfile.TemporaryDirectory() as root:
            store=s.Store(root); p={'id':'a'*32,'kind':'project','phase':'working'}
            store.save(p)
            first=store.load(p['id']);first['phase']='done'
            with patch.object(Path,'read_text',side_effect=AssertionError('Unchanged file was re-read')):
                self.assertEqual(store.load(p['id'])['phase'],'working')
                self.assertEqual(len(store.list(active_only=True)),1)
            other=s.Store(root);other.save({**p,'phase':'done','external':True})
            self.assertEqual(store.list(active_only=True),[])
            self.assertTrue(store.load(p['id'])['external'])


class CameraStageTests(fixtures.unittest.IsolatedAsyncioTestCase):
    async def test_camera_design_then_artist_approved_video_without_segmentation(self):
        with tempfile.TemporaryDirectory() as root:
            c=s.Studio.__new__(s.Studio); c.store=s.Store(root); c.server_address='test'
            c.collect=lambda p:p; c.start_watcher=Mock()
            q=Mock(); q.put=Mock()
            c.server=types.SimpleNamespace(number=0,prompt_queue=q,trigger_on_prompt=lambda v:v,
                node_replace_manager=types.SimpleNamespace(apply_replacements=lambda g:None))
            p=fixtures.SharedEngineTests().project()
            p.update(config=s.clean_config({'engine':'h3','workflow_mode':'camera'}),
                     review=None,approval=None,character=None,references=[],look_mode='build',
                     opening_input=None,opening_key=None,opening_approval=None,phase='new')
            stages=[]
            def graph(project,stage):
                stages.append(stage)
                return {'result':{'class_type':'TestOutput','inputs':{}}}
            execution=types.ModuleType('execution')
            execution.validate_prompt=AsyncMock(return_value=(True,None,['result'],{}))
            with patch.dict('sys.modules',{'execution':execution}),patch.object(s,'build_graph',side_effect=graph), \
                 patch.object(s,'validate_selection'),patch('ComfyUI_zura_nodes.artist_studio.h3_camera.selected_frame_count',return_value=48):
                await c.action(p,'create_look',{'request_key':str(uuid.uuid4())})
                self.assertEqual(stages,['design'])
                self.assertNotIn('next_stage',p['actions'][-1])
                p['actions'][-1]['state']='complete'
                p.update(phase='opening',opening_input={'file':'look.png'},opening_key='look')
                await c.action(p,'animate',{'request_key':str(uuid.uuid4())})
                self.assertEqual(stages,['design','h3'])
                self.assertEqual(p['opening_approval'],'look')
                self.assertEqual(p['actions'][-1]['h3_preset'],'camera_ref2va_8step')
                self.assertEqual(q.put.call_count,2)

    async def test_camera_direction_invalidates_previous_frame(self):
        with tempfile.TemporaryDirectory() as root:
            c=s.Studio.__new__(s.Studio);c.store=s.Store(root);c.collect=lambda p:p
            p=fixtures.SharedEngineTests().project()
            p['config']=s.clean_config({'engine':'h3','workflow_mode':'camera'})
            c.configure(p,{**p['config'],'camera_preset':'Right profile'})
            self.assertIsNone(p['opening_input'])
