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
        p = {'actions': [{'stage':'ltx25_stage1','state':'complete'}, {'stage':'ltx25_cleanup'}]}
        self.assertFalse(release_policy(p, memory)['purge_cache'])
        memory.available = 2*1024**3
        self.assertTrue(release_policy(p, memory)['purge_cache'])
        memory.available = 24*1024**3
        for stage in ('ltx25_motion', 'wan_prepare', 'wan_speech', 'design'):
            p['actions'][0]['stage'] = stage
            self.assertTrue(release_policy(p, memory)['purge_cache'])

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
