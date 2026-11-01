import importlib
import sys
import types
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

import test_artist_studio as fixture
import test_studio_opening as uploaded

s = fixture.studio
opening = importlib.import_module(s.__package__ + '.opening')


class FinishedFrameTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assets = uploaded.StartingImageTests()
        self.assets.setUp()
        self.addCleanup(self.assets.tearDown)
        self.project = fixture.SharedEngineTests().project()
        self.project.update(look_mode='ready', starting_asset=self.assets.uploaded,
                            approval=None, prepared_key=None, review=None, opening_input=None,
                            opening_key=None, opening_approval=None, phase='new')
        self.controller = s.Studio.__new__(s.Studio)
        self.controller.collect = lambda p: p
        self.controller.store = types.SimpleNamespace(save=Mock())

    async def test_finished_frame_binds_without_queue_mask_depth_or_generation(self):
        for engine, mode in [('wan','motion'),('h3','viewport'),('h3','relight')]:
            with self.subTest(engine=engine, mode=mode):
                p=self.project.copy()
                p['config']=s.clean_config({**p['config'],'engine':engine,'workflow_mode':mode})
                with patch('folder_paths.get_input_directory',return_value=str(self.assets.input_root)), \
                     patch.object(s,'check_asset',side_effect=self.assets.check_asset), \
                     patch.object(s,'require_verified_setup'), \
                     patch.object(s,'build_graph') as build, \
                     patch.object(s,'assert_approved',side_effect=AssertionError('No preparation approval yet')):
                    await self.controller.action(p,'create_look',{'request_key':str(uuid.uuid4())})
                build.assert_not_called()
                self.assertTrue(p['opening_input']['file'].startswith('genj_studio/'))
                self.assertTrue(p['opening_needs_preparation'])
                self.assertIsNone(p['approval'],'Viewing the finished frame does not pretend a mask is approved')
                self.assertEqual(p['actions'],[])

    async def test_generate_starts_preparation_and_records_verified_continuation(self):
        p=self.project
        p.update(opening_input={'file':'opening.png','sha':'opening'}, opening_key='opening',
                 opening_needs_preparation=True, phase='opening')
        c=self.controller
        c.server_address='test'
        c.start_watcher=Mock()
        queued=Mock()
        c.server=types.SimpleNamespace(number=0,prompt_queue=types.SimpleNamespace(put=queued),
            trigger_on_prompt=lambda body:body,node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None))
        execution=types.SimpleNamespace(validate_prompt=AsyncMock(return_value=(True,None,['prepare'],{})))
        with patch.dict(sys.modules,{'execution':execution}),patch.object(s,'validate_selection'), \
             patch.object(s,'build_graph',return_value={'prepare':{'class_type':'TestOutput','inputs':{}}}) as build:
            await c.action(p,'animate',{'request_key':str(uuid.uuid4())})
        self.assertEqual(build.call_args.args[1],'prepare')
        self.assertEqual(p['actions'][-1]['next_stage'],'finished_animate')
        self.assertIsNone(p['opening_approval'])
        self.assertEqual(queued.call_count,1)

    async def test_continuation_rejects_unverified_or_replayed_preparation(self):
        p=self.project
        p['opening_needs_preparation']=True
        p['actions']=[{'id':str(uuid.uuid4()),'stage':'prepare','state':'complete','next_stage':'finished_animate'}]
        with self.assertRaisesRegex(ValueError,'could not be verified'):
            await self.controller.action(p,'finished_animate',{'request_key':str(uuid.uuid4())})
        original=self.controller.action
        self.controller.action=AsyncMock(return_value=p)
        await original(p,'finished_animate',{'request_key':str(uuid.uuid5(uuid.NAMESPACE_URL,p['actions'][-1]['id']))})
        self.assertEqual([call.args[1] for call in self.controller.action.await_args_list],['approve','animate'])

    def test_motion_prompt_change_preserves_the_uploaded_finished_frame(self):
        p=self.project
        p.update(opening_input={'file':'opening.png','sha':'opening'},opening_key='opening',phase='opening')
        p['config']['image_prompt']=''
        self.controller.configure(p,{**p['config'],'prompt':'A new camera movement'})
        self.assertEqual(p['opening_input']['file'],'opening.png')


if __name__=='__main__':
    unittest.main()
