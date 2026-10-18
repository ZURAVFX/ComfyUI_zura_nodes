"""Create a frame in one request, but never automatically render a video."""
import asyncio
import tempfile
import types
import uuid
from unittest.mock import Mock, AsyncMock, patch
import test_artist_studio as fixtures
s=fixtures.studio

class CreateLookTests(fixtures.unittest.IsolatedAsyncioTestCase):
    async def test_prepare_resume_design_stops_for_artist_and_replay_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=s.Studio.__new__(s.Studio);c.store=s.Store(tmp);c.server_address='test'
            c.start_watcher=Mock();c.schedule_resume=Mock();c.lock=asyncio.Lock()
            queue=Mock();queue.put=Mock();queue.get_history.return_value={};queue.get_current_queue_volatile.return_value=([],[])
            c.server=types.SimpleNamespace(number=0,prompt_queue=queue,
                trigger_on_prompt=lambda value:value,node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None))
            p=fixtures.SharedEngineTests().project()
            p.update(phase='new',review=None,approval=None,prepared_key=None,opening_input=None,opening_key=None,opening_url=None,look_mode='build')
            first=str(uuid.uuid4());stages=[]
            def graph(project,stage):
                stages.append(stage);return {'output':{'class_type':'TestOutput','inputs':{}}}
            validation=AsyncMock(return_value=(True,None,['output'],{}))
            execution=types.ModuleType('execution');execution.validate_prompt=validation
            review=__import__('importlib').import_module(fixtures.NAME)
            with patch.dict('sys.modules',{'execution':execution}),patch.object(s,'build_graph',side_effect=graph),patch.object(s,'validate_selection'),patch.object(s,'check_asset'),patch.object(review,'verify_review',return_value=(None,{'clip':{}}),create=True):
                await c.action(p,'create_look',{'request_key':first})
                self.assertEqual(stages,['prepare']);self.assertEqual(p['actions'][-1]['next_stage'],'create_look')
                await c.action(p,'create_look',{'request_key':first})
                self.assertEqual(queue.put.call_count,1)
                action=p['actions'][-1]
                queue.get_history.return_value={action['id']:{'status':{'status_str':'success'},'outputs':{'output':{'text':['shot_'+'a'*16]}}}}
                c._collect(p)
                self.assertEqual(p['phase'],'working',p.get('error'));self.assertEqual(action['state'],'complete')
                c.schedule_resume.assert_called_with(p['id'],action['id'])
                c.store.save(p)
                await c.resume_text(p['id'],action['id'])
                result=c.store.load(p['id'])
                self.assertEqual(stages,['prepare','design'])
                self.assertEqual(queue.put.call_count,2)
                self.assertEqual(result['actions'][-1]['stage'],'design')
                self.assertEqual(result['approval'],result['prepared_key'])
                # Persisted request replay cannot move a finished frame back
                # into approval or schedule a video render.
                result.update(phase='opening',opening_input={'file':'frame.png'},opening_key='look')
                result['actions'][-1]['state']='complete'
                await c.action(result,'create_look',{'request_key':first})
                self.assertEqual(result['phase'],'opening');self.assertEqual(stages,['prepare','design'])

    async def test_direct_head_recipe_stays_out_of_image_generation(self):
        c=s.Studio.__new__(s.Studio);c.collect=lambda p:p
        p=fixtures.SharedEngineTests().project();p['actions']=[]
        p['config'].update(engine='h3',scope='head',h3_head_swap=True,remove_text=False)
        with self.assertRaises(ValueError):await c.action(p,'create_look',{'request_key':str(uuid.uuid4())})
