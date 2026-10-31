import asyncio
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_artist_studio as fixtures

runner = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_long_runner')
jobs_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_jobs')
anchor_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_anchor')
native_graph = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
masked_graph = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_long_masked')


class OutpaintLongPlanning(unittest.TestCase):
    def setUp(self):
        self.source = {'file':'genj_studio/a/source.mp4', 'sha':'a'*64, 'duration':20,
                       'width':768, 'height':432}
        self.options = dict(start=1., duration=8., mode='expand', width=1152,
                            height=640, left=128, right=128)

    def test_fractional_full_source_round_trip_keeps_last_frame(self):
        source = dict(self.source, duration=153/25)
        options = {**self.options, 'start': 0., 'duration': source['duration']}
        selection, parts, _ = runner.plan_long(source, **options)
        self.assertEqual(selection['frames'], 147)
        rebuilt, _, _ = runner.plan_long(source, **{**options, 'duration': selection['requested_duration']}, allow_partial_end=True)
        self.assertEqual(rebuilt['review_key'], selection['review_key'])
        rounded, _, _ = runner.plan_long(source, **{**options, 'duration': selection['duration']}, allow_partial_end=True)
        self.assertNotEqual(rounded['review_key'], selection['review_key'])
        with self.assertRaisesRegex(ValueError, 'valid range'):
            runner.plan_long(source, **{**options, 'duration': source['duration'] + .02})

    def test_full_range_key_and_chunk_validation(self):
        selection, parts, subplans = runner.plan_long(self.source, **self.options)
        self.assertEqual(selection['frames'], 192)
        self.assertEqual(sum(p.count-p.overlap for p in parts), 192)
        self.assertEqual(subplans[1]['start'], 1 + parts[1].start/24)
        self.assertTrue(all(p['frames'] <= 120 for p in subplans))
        changed = runner.plan_long(self.source, **{**self.options, 'duration':7.})[0]
        self.assertNotEqual(selection['review_key'], changed['review_key'])
        with self.assertRaises(ValueError):
            runner.plan_long(self.source, **{**self.options, 'duration':20.})

    def test_last_frame_anchor_is_time_aligned_and_keeps_source_mask_guide(self):
        selection, parts, subplans = runner.plan_long(self.source, **self.options, overlap=1)
        self.assertNotEqual(selection['review_key'], runner.plan_long(self.source, **self.options)[0]['review_key'])
        for previous, following in zip(parts, parts[1:]):
            self.assertEqual(previous.start + previous.count - 1, following.start)
            self.assertEqual(following.overlap, 1)
        graph = native_graph.build_test_graph('source.mp4', 'test', 49, 24, 1152, 640,
            left=128, right=128, top=0, bottom=0)
        anchored = anchor_module.attach_first_frame(graph, 'genj_studio/anchor/last.png')
        self.assertEqual(anchored['guide']['inputs']['latent'], ['zura_anchor_i2v', 0])
        self.assertEqual(anchored['zura_anchor_i2v']['inputs']['latent'], ['empty', 0])
        self.assertEqual(anchored['av_high']['inputs']['video_latent'], ['zura_anchor_i2v_high', 0])
        self.assertEqual(anchored['zura_anchor_i2v_high']['inputs']['latent'], ['encode_high', 0])
        self.assertEqual(anchored['guide']['inputs']['image'], graph['guide']['inputs']['image'])
        self.assertEqual(anchored['low_mask']['inputs'], graph['low_mask']['inputs'])
        self.assertEqual(anchored['blend_high']['inputs'], graph['blend_high']['inputs'])
        self.assertEqual(graph['guide']['inputs']['latent'], ['empty', 0])
        with self.assertRaises(ValueError):
            anchor_module.attach_first_frame(graph, '../outside.png')
        _, overlapping, _ = runner.plan_long(self.source, **self.options, overlap=9)
        for previous, following in zip(overlapping, overlapping[1:]):
            anchor_index = previous.count - following.overlap
            self.assertEqual(previous.start + anchor_index, following.start)

    def test_masked_window_uses_approved_geometry_source_and_original_audio(self):
        selection, _, subplans = runner.plan_long(self.source, **self.options, overlap=9)
        sub = subplans[0]
        graph = masked_graph.build_masked_expand_graph(self.source, sub, review_key=sub['review_key'],
            output_prefix='genj/outpaint/test')
        self.assertEqual(graph['source_range']['inputs']['start_seconds'], sub['start'])
        self.assertEqual(graph['canvas']['inputs']['left'], sub['left'])
        self.assertEqual(graph['low_mask']['inputs']['image'], ['low_mask_image', 0])
        self.assertEqual(graph['inpaint']['inputs']['mask'], ['low_mask', 0])
        self.assertEqual(graph['guide']['inputs']['image'], ['inpaint', 0])
        self.assertEqual(graph['blend_high']['inputs']['mask'], ['canvas', 1])
        self.assertEqual(graph['trim_result']['inputs']['length'], sub['frames'])
        self.assertEqual(graph['assemble']['inputs']['audio'], ['components', 1])
        with self.assertRaisesRegex(ValueError, 'Review'):
            masked_graph.build_masked_expand_graph(self.source, sub, review_key='bad', output_prefix='genj/outpaint/test')

    def test_dependency_preflight_reports_specific_files_and_nodes(self):
        import folder_paths
        import nodes
        available = {name: object() for name in jobs_module.LONG_REQUIRED_NODES}
        missing_name = jobs_module.LONG_REQUIRED_FILES[-1][1]
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, available, clear=True), \
             patch.object(folder_paths, 'get_full_path', side_effect=lambda folder, name: None if name == missing_name else name):
            result = jobs_module.long_dependencies()
        self.assertFalse(result['ready'])
        self.assertEqual(result['missing_files'], [missing_name])
        self.assertEqual(result['missing_nodes'], [])
        self.assertIn('ltx25_in_outpaint', result['packages'])

    def test_short_methods_check_their_actual_adapter_and_nodes(self):
        import folder_paths
        import nodes
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, {}, clear=True), \
             patch.object(folder_paths, 'get_full_path', return_value=None):
            expand = jobs_module.short_dependencies('expand')
            black = jobs_module.short_dependencies('black')
        self.assertIn('ltx-2.3-22b-ic-lora-outpaint.safetensors', expand['missing_files'])
        self.assertNotIn('ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors', expand['missing_files'])
        self.assertIn('ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors', black['missing_files'])
        self.assertNotIn('ltx-2.3-22b-ic-lora-outpaint.safetensors', black['missing_files'])
        self.assertIn('ZuraOutpaintReviewOverlay', expand['missing_nodes'])
        self.assertIn('LTXVInpaintPreprocess', black['missing_nodes'])


class OutpaintLongCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_rejects_insufficient_disk_before_job_submission(self):
        import folder_paths
        from types import SimpleNamespace
        source = {'file':'genj_studio/a/source.mp4', 'sha':'a'*64, 'duration':8,
                  'width':128, 'height':128}
        selection, _, _ = runner.plan_long(source, start=0, duration=6.25,
            mode='expand', width=128, height=128, left=16, right=16, overlap=9,
            strategy='anchored_masked')
        instance = jobs_module.OutpaintJobs(SimpleNamespace())
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(folder_paths, 'get_output_directory', return_value=folder), \
             patch.object(folder_paths, 'get_input_directory', return_value=folder), \
             patch.object(jobs_module.shutil, 'which', return_value='ffmpeg'), \
             patch.object(jobs_module.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, 'free working space'):
                await instance.submit_long('review', source, selection, anchor=True)
        self.assertEqual(instance.jobs, {})

    async def test_overlap_anchor_targets_the_same_source_timestamp(self):
        from ComfyUI_zura_nodes.artist_studio.outpaint_chunks import Window
        seen = []
        async def submit(kind, source, subplan, previous):
            seen.append(previous)
            if previous is not None:
                raise RuntimeError('stop after verifying the anchor')
            return 'first'
        async def wait(identity):
            return 'first-output.mp4'
        async def cancel(identity):
            pass
        with self.assertRaisesRegex(RuntimeError, 'verifying the anchor'):
            await runner.run_windows(kind='render', source={}, selection={'start':0},
                parts=[Window(0,49,0),Window(40,49,9)], subplans=[{},{}],
                submit=submit, wait=wait, cancel=cancel, update=lambda *args:None,
                ffmpeg='ffmpeg', output='unused', anchor=True)
        self.assertIsNone(seen[0])
        self.assertEqual(seen[1], (Path('first-output.mp4'), 40))

    async def test_cancel_during_submission_does_not_orphan_queued_prompt(self):
        queued, release = asyncio.Event(), asyncio.Event()
        cancelled = []
        async def submit(*args):
            queued.set()  # The prompt is in the queue before its ID is returned.
            await release.wait()
            return 'newly-queued'
        async def wait(job):
            self.fail('A cancelled submission must not enter the normal wait.')
        async def cancel(job):
            cancelled.append(job)
        task = asyncio.create_task(runner.run_windows(kind='render', source={}, selection={'start':0},
            parts=[object()], subplans=[{}], submit=submit, wait=wait, cancel=cancel,
            update=lambda *args: None, ffmpeg='ffmpeg', output='unused'))
        await queued.wait()
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(cancelled, ['newly-queued'])

    async def test_only_active_child_is_cancelled(self):
        entered = asyncio.Event()
        cancelled = []
        async def submit(*args):
            return 'current'
        async def wait(job):
            entered.set()
            await asyncio.Event().wait()
        async def cancel(job):
            cancelled.append(job)
        task = asyncio.create_task(runner.run_windows(kind='render', source={}, selection={'start':0},
            parts=[object()], subplans=[{}], submit=submit, wait=wait, cancel=cancel,
            update=lambda *args: None, ffmpeg='ffmpeg', output='unused'))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(cancelled, ['current'])

    async def test_progress_exposes_the_active_child_prompt_and_clears_on_cancel(self):
        import folder_paths
        from types import SimpleNamespace
        active = {'running': True}
        queue = SimpleNamespace(get_history=lambda identity: {},
            get_current_queue_volatile=lambda: ([(0, 'child')] if active['running'] else [], []),
            interrupt_if_running=lambda identity: None,
            delete_queue_item=lambda predicate: None)
        instance = jobs_module.OutpaintJobs(SimpleNamespace(server=SimpleNamespace(prompt_queue=queue)))
        source = {'file':'genj_studio/a/source.mp4', 'sha':'a'*64, 'duration':8,
                  'width':128, 'height':128}
        selection, _, _ = runner.plan_long(source, start=0, duration=6.25,
            mode='expand', width=128, height=128, left=16, right=16)
        async def fake_submit(kind, asset, subplan, prompt='', seed=42, client_id=None, anchor_file=None):
            instance.jobs['child'] = {'id':'child', 'kind':kind, 'state':'running',
                                      'selection':subplan, 'created':0}
            return {'id':'child'}
        instance.submit = fake_submit
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(folder_paths, 'get_output_directory', return_value=folder), \
             patch.object(folder_paths, 'get_input_directory', return_value=folder), \
             patch.object(jobs_module, 'check_asset', return_value=Path(folder)), \
             patch.object(jobs_module.shutil, 'which', return_value='ffmpeg'):
            public = await instance.submit_long('review', source, selection, client_id='studio-test')
            job = instance.jobs[public['id']]
            for _ in range(100):
                if job.get('active_prompt_id'):
                    break
                await asyncio.sleep(.01)
            self.assertEqual(instance.public(job)['active_prompt_id'], 'child')
            job['state'] = 'cancelling'
            job['task'].cancel()
            await asyncio.sleep(.05)
            self.assertFalse(job['task'].done(), 'do not report cancellation while the child is still running')
            self.assertEqual(instance.state(job['id'])['state'], 'cancelling')
            active['running'] = False
            with self.assertRaises(asyncio.CancelledError):
                await job['task']
            self.assertIsNone(instance.public(job)['active_prompt_id'])
            self.assertEqual(instance.public(job)['state'], 'cancelled')

    async def test_executor_reviews_and_renders_entire_range_with_audio(self):
        ffmpeg = shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        if not Path(ffmpeg).is_file():
            self.skipTest('FFmpeg is required for this integration test.')
        import folder_paths
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root/'genj'/'outpaint'
            out.mkdir(parents=True)
            audio = root/'source.wav'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=8', str(audio)], check=True)
            source = {'file':'genj_studio/a/source.mp4', 'sha':'a'*64, 'duration':153/25,
                      'width':128, 'height':128}
            selection, _, _ = runner.plan_long(source, start=0, duration=153/25,
                mode='expand', width=128, height=128, left=16, right=16, overlap=9,
                strategy='anchored_masked')
            self.assertEqual(selection['frames'], 147)
            instance = jobs_module.OutpaintJobs(SimpleNamespace())
            serial = 0
            anchors = []; selected_loras=[]
            async def fake_submit(kind, asset, subplan, prompt='', seed=42, client_id=None, anchor_file=None, strategy=None, custom_loras=None):
                nonlocal serial
                self.assertEqual(strategy, 'anchored_masked')
                selected_loras.append((kind,custom_loras))
                if anchor_file:
                    from PIL import Image
                    anchor_path = root / anchor_file
                    with Image.open(anchor_path) as image:
                        self.assertEqual(image.size, (128, 128))
                    anchors.append(anchor_path)
                serial += 1
                name = f'child_{serial}.mp4'
                subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                    'color=blue:s=128x128:r=24', '-frames:v', str(subplan['frames']),
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(out/name)], check=True)
                identity = f'child_{serial}'
                instance.jobs[identity] = {'id': identity, 'kind': kind, 'state':'complete',
                    'selection':subplan, 'artifact':{'filename':name}}
                return {'id':identity}
            instance.submit = fake_submit
            with patch.object(folder_paths, 'get_output_directory', return_value=str(root)), \
                 patch.object(folder_paths, 'get_input_directory', return_value=str(root)), \
                 patch.object(jobs_module, 'check_asset', return_value=audio), \
                 patch('ComfyUI_zura_nodes.artist_studio.custom_loras.apply_installed_ltx_loras', side_effect=lambda graph, selected:graph), \
                 patch.object(jobs_module.shutil, 'which', return_value=ffmpeg):
                review = await instance.submit_long('review', source, selection, anchor=True)
                await instance.jobs[review['id']]['task']
                reviewed = instance.state(review['id'])
                self.assertEqual(reviewed['state'], 'complete', reviewed.get('error'))
                self.assertAlmostEqual(reviewed['selection']['requested_duration'], 153/25)
                with self.assertRaisesRegex(ValueError, 'approve'):
                    await instance.submit_long('render', source, selection, reviewed=reviewed, anchor=True)
                reviewed['approved'] = True
                choice=[{'name':'style.safetensors','strength':.6,'confirm_unknown':True}]
                final = await instance.submit_long('render', source, selection, reviewed=reviewed, anchor=True, custom_loras=choice)
                await instance.jobs[final['id']]['task']
                result = instance.state(final['id'])
                self.assertEqual(result['state'], 'complete', result.get('error'))
                self.assertEqual(instance.public(result)['artifact'], result['artifact'], 'HDR can select the completed output directly')
                from ComfyUI_zura_nodes.artist_studio.enhancement import inspect_video
                media = inspect_video(out/result['artifact']['filename'], expected_frames=153, expected_fps=24)
                self.assertEqual(media['audio_tracks'], 1)
                import array
                pcm = subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(out/result['artifact']['filename']),
                                               '-map', '0:a:0', '-f', 'f32le', '-ac', '1', '-ar', '24000', '-'])
                wave = array.array('f'); wave.frombytes(pcm)
                self.assertGreater(sum(map(abs,wave[24000:48000]))/24000, .01)
                self.assertLess(max(map(abs,wave[round(6.14*24000):])), .002)
                self.assertTrue(all(items==choice for kind,items in selected_loras if kind=='render'), 'Every rendered window receives the same custom LoRA')
                self.assertTrue(all(items is None for kind,items in selected_loras if kind=='review'), 'Review graphs do not load user LoRAs')
                self.assertEqual(len(anchors), 1, 'Only the second render window needs the previous last frame.')
                self.assertTrue(all(not path.exists() for path in anchors), 'Temporary anchor frames must be removed.')


if __name__ == '__main__':
    unittest.main()
