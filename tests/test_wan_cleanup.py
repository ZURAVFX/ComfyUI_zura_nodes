"""Serial Wan model hand-off contracts, without inference or user projects."""
import asyncio
import copy
import importlib
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

import v2_bootstrap

NAME = 'ComfyUI_zura_nodes.artist_studio'
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / 'artist_studio')]
    sys.modules[NAME] = package
studio = importlib.import_module(NAME + '.studio')


class Queue:
    def __init__(self):
        self.mutex = threading.RLock()
        self.running, self.pending, self.flags, self.history = [], [], {}, {}
        self.insertions = []

    def get_current_queue_volatile(self):
        return self.running, self.pending

    def set_flag(self, key, value):
        self.flags[key] = value

    def get_flags(self, reset=True):
        value = dict(self.flags)
        if reset:
            self.flags.clear()
        return value

    def get_history(self, identity):
        return {identity: self.history[identity]} if identity in self.history else {}

    def put(self, item):
        self.insertions.append(item)
        self.pending.append(item)


class WanCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.queue = Queue()
        self.obj = studio.Studio.__new__(studio.Studio)
        self.obj.store = studio.Store(self.directory.name)
        self.obj.lock = asyncio.Lock()
        self.obj.resuming = set()
        self.obj.server_address = 'test:8188'
        self.obj.server = types.SimpleNamespace(prompt_queue=self.queue, number=0,
            last_prompt_id=None, trigger_on_prompt=lambda data: data,
            node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph: None))
        self.obj.start_watcher = Mock()
        self.obj.resume_text = AsyncMock()
        self.p = {'id': 'a' * 32, 'phase': 'working', 'config': studio.clean_config({'engine': 'wan'}),
            'actions': [{'id': '11111111-1111-4111-8111-111111111111', 'stage': 'wan_cleanup',
                'state': 'waiting', 'created': time.time(), 'next_stage': 'wan',
                'server_address': self.obj.server_address,
                'graph': {'ack': {'class_type': 'PreviewAny', 'inputs': {'source': 'synthetic marker'}}},
                'output_nodes': ['ack']}]}
        self.obj.store.save(self.p)

    def test_unknown_running_or_pending_jobs_are_left_untouched(self):
        for field in ('running', 'pending'):
            with self.subTest(field=field):
                setattr(self.queue, field, [(0, 'unrelated-job', {}, {}, [], {})])
                before = copy.deepcopy(getattr(self.queue, field))
                self.obj.collect(self.p)
                self.assertEqual(getattr(self.queue, field), before)
                self.assertEqual(self.queue.flags, {})
                self.assertEqual(self.queue.insertions, [])
                self.assertEqual(self.p['actions'][-1]['state'], 'waiting')
                setattr(self.queue, field, [])

    def test_flags_must_be_consumed_before_acknowledgement_is_queued(self):
        self.obj.collect(self.p)
        self.assertEqual(self.queue.flags, {'unload_models': True, 'free_memory': True})
        self.obj.collect(self.p)
        self.assertEqual(self.queue.insertions, [])
        self.assertEqual(self.queue.get_flags(reset=False), self.queue.flags)
        # The serial native worker consumes the flags before loading its next prompt.
        self.queue.get_flags(reset=True)
        self.obj.collect(self.p)
        self.assertEqual(len(self.queue.insertions), 1)
        self.assertEqual(self.queue.insertions[0][2], self.p['actions'][-1]['graph'])
        self.assertEqual(self.p['actions'][-1]['state'], 'queued')
        self.obj.collect(self.p)
        self.assertEqual(len(self.queue.insertions), 1)

    async def test_only_completed_exact_cpu_marker_resumes_wan(self):
        self.obj.collect(self.p)
        self.queue.flags.clear()
        self.obj.collect(self.p)
        action = self.p['actions'][-1]
        self.assertEqual(action['state'], 'queued')
        self.assertEqual(self.obj.resume_text.await_count, 0)
        self.queue.pending.clear()
        self.queue.history[action['id']] = {'status': {'status_str': 'success'},
            'prompt': [0, action['id'], copy.deepcopy(action['graph'])], 'outputs': {}}
        self.obj.collect(self.p)
        await asyncio.sleep(0)
        self.assertEqual(action['state'], 'complete')
        self.obj.resume_text.assert_awaited_once_with(self.p['id'], action['id'])

    def test_wrong_acknowledgement_fails_without_queuing_a_model(self):
        action = self.p['actions'][-1]
        action['state'] = 'queued'
        self.queue.history[action['id']] = {'status': {'status_str': 'success'},
            'prompt': [0, action['id'], {'ack': {'class_type': 'PreviewAny', 'inputs': {'source': 'wrong'}}}],
            'outputs': {}}
        self.obj.collect(self.p)
        self.assertEqual(self.p['phase'], 'error')
        self.assertEqual(self.queue.insertions, [])

    def test_stalled_cleanup_has_a_bounded_error(self):
        self.p['actions'][-1]['cleanup_requested'] = time.time() - 121
        self.queue.flags['free_memory'] = True
        self.obj.collect(self.p)
        self.assertEqual(self.p['phase'], 'error')
        self.assertEqual(self.queue.insertions, [])
        self.assertIn('did not finish', self.p['error'])

    def test_ambiguous_submitting_marker_is_never_resubmitted(self):
        self.p['actions'][-1]['state'] = 'submitting'
        self.obj.collect(self.p)
        self.assertEqual(self.queue.insertions, [])
        self.assertEqual(self.p['actions'][-1]['state'], 'submitting')

    async def test_double_click_during_waiting_does_not_duplicate_action(self):
        before = len(self.p['actions'])
        await self.obj.action(self.p, 'animate', {'request_key': '22222222-2222-4222-8222-222222222222'})
        self.assertEqual(len(self.p['actions']), before)
        self.assertEqual(self.queue.insertions, [])

    async def run_action(self, *, reference=True, speech=True, cached=False, ready=True, previous=None):
        self.p['actions'] = [previous] if previous else []
        self.p.update(phase='opening', opening_input={'file': 'look.png', 'sha': 'look'}, opening_key='look')
        self.p['config'].update(audio_id='b' * 32 if reference else '', lip_sync=reference and speech)
        self.p['audio'] = {'file': 'reference.wav', 'sha': 'reference'} if reference else None
        module = types.ModuleType(NAME + '.wan_speech')
        module.enabled = lambda p: bool(p.get('audio') and p['config']['lip_sync'])
        module.guide_ready = Mock(return_value=cached)
        module.readiness = Mock(return_value={'ready': ready})
        executor = types.ModuleType('execution')
        executor.validate_prompt = AsyncMock(return_value=(True, None, ['ack'], {}))
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, previous['id'])) if previous else str(uuid.uuid4())
        built = []
        def graph(project, stage):
            built.append(stage)
            return {'ack': {'class_type': 'PreviewAny', 'inputs': {'source': stage}}}
        with patch.dict(sys.modules, {NAME + '.wan_speech': module, 'execution': executor}), \
                patch.object(studio, 'build_graph', side_effect=graph):
            await self.obj.action(self.p, 'animate', {'request_key': key})
        return module, built

    async def test_cold_reference_runs_cleanup_before_the_native_speech_stage(self):
        _, built = await self.run_action(cached=False)
        self.assertEqual(built, ['wan_cleanup'])
        self.assertEqual(self.p['actions'][-1]['next_stage'], 'wan_speech')
        self.assertEqual(self.p['actions'][-1]['state'], 'waiting')
        self.assertEqual(self.queue.insertions, [])

    async def test_warm_reference_clears_memory_and_skips_speech_inference(self):
        module, built = await self.run_action(cached=True, ready=False)
        self.assertEqual(built, ['wan_cleanup'])
        self.assertEqual(self.p['actions'][-1]['next_stage'], 'wan')
        module.readiness.assert_not_called()

    async def test_cleanup_resume_queues_wan_without_another_cleanup_loop(self):
        previous = copy.deepcopy(self.p['actions'][-1])
        previous.update(state='complete', next_stage='wan')
        _, built = await self.run_action(cached=True, previous=previous)
        self.assertEqual(built, ['wan'])
        self.assertEqual(self.p['actions'][-1]['stage'], 'wan')
        self.assertEqual(len(self.queue.insertions), 1)

    async def test_original_and_soundtrack_only_keep_the_source_performance_path(self):
        for reference, speech in ((False, False), (True, False)):
            with self.subTest(reference=reference):
                self.queue.insertions.clear()
                self.queue.pending.clear()
                module, built = await self.run_action(reference=reference, speech=speech, ready=False)
                self.assertEqual(built, ['wan'])
                module.guide_ready.assert_not_called()
                module.readiness.assert_not_called()

    async def test_missing_speech_setup_fails_before_memory_flags_or_inference(self):
        with self.assertRaisesRegex(ValueError, 'Setup_Wan_Speech'):
            await self.run_action(cached=False, ready=False)
        self.assertEqual(self.queue.flags, {})
        self.assertEqual(self.queue.insertions, [])


if __name__ == '__main__':
    unittest.main()
