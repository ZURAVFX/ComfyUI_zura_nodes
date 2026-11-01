"""Real CPU media reload/export checks, with no diffusion or GPU use."""
import ast
from fractions import Fraction
import hashlib
import importlib
from pathlib import Path
import re
import subprocess
import tempfile
import sys
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import av
import numpy as np
import test_artist_studio as fixture

timing = importlib.import_module(fixture.studio.__package__ + '.source_timing')


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], check=True)


def inspect(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        frames = [float(frame.to_ndarray(format='rgb24').mean()) for frame in container.decode(video=0)]
        return stream.average_rate, frames, len(container.streams.audio)


class RelightTimingTests(unittest.TestCase):
    def test_original_cadence_survives_proxy_reload_model_padding_and_final_export(self):
        tree = ast.parse((Path(timing.__file__).parent / '__init__.py').read_text(encoding='utf-8'))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name in ('GenjLoadReviewedShot', 'GenjRestoreSoundtrack')]
        for fps in (Fraction(24), Fraction(25), Fraction(30), Fraction(60), Fraction(24000,1001), Fraction(30000,1001)):
            with self.subTest(fps=str(fps)), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                original = directory / 'original.mov'
                count = 30
                with av.open(str(original), 'w') as container:
                    stream = container.add_stream('libx264', rate=fps)
                    stream.width, stream.height, stream.pix_fmt = 64,48,'yuv420p'
                    stream.options = {'crf':'0'}
                    for index in range(count):
                        frame = av.VideoFrame.from_ndarray(np.full((48,64,3),index*6,np.uint8),format='rgb24')
                        frame.pts, frame.time_base = index, 1/fps
                        for packet in stream.encode(frame): container.mux(packet)
                    for packet in stream.encode(): container.mux(packet)
                source = directory / 'source_with_audio.mp4'
                ffmpeg('-i',original,'-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                       '-map','0:v:0','-map','1:a:0','-t',float(count/fps),'-c:v','copy','-c:a','aac',source)
                ffmpeg('-i',source,'-vf','fps=24','-c:v','libx264','-c:a','aac',directory/'source.mp4')
                for name in ('mask.mp4','guide.mp4'):
                    ffmpeg('-i',directory/'source.mp4','-c','copy',directory/name)
                details = dict(source=str(source),source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
                               start=0,duration=float(count/fps),selected_duration=float(count/fps),
                               frames=round(count/fps*24),fps=24,full_source=True)
                namespace = dict(CATEGORY='Test', __package__=fixture.studio.__package__,
                                 verify_review=lambda identity:(directory,{'clip':details,'files':{}}),
                                 Path=Path,av=av,Fraction=Fraction,np=np,re=re,ffmpeg=ffmpeg,
                                 digest_file=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                                 source_path=Path,root=lambda:directory,
                                 InputImpl=SimpleNamespace(VideoFromFile=lambda path:path))
                exec(compile(ast.Module(body=classes,type_ignores=[]),'native_relight_adapters','exec'),namespace)
                loaded = namespace['GenjLoadReviewedShot']().load('shot','shot',render_long_edge=256,
                                  preserve_aspect=True,preserve_source_timing=True)
                native = loaded[3]
                self.assertEqual(native['frames'],count)
                self.assertEqual((native['fps_num'],native['fps_den']),(fps.numerator,fps.denominator))
                for path in (loaded[0],loaded[1],loaded[2],loaded[4]):
                    rate,frames,_ = inspect(path)
                    self.assertEqual((rate,len(frames)),(fps,count))
                values=inspect(loaded[0])[1]
                self.assertTrue(all(b-a>2 for a,b in zip(values,values[1:])), 'Native frames must not be dropped and duplicated through the 24 fps proxy')
                padded = directory/'model_padded.mp4'
                ffmpeg('-i',loaded[0],'-vf','tpad=stop_mode=clone:stop=3','-an','-c:v','libx264',padded)
                result=namespace['GenjRestoreSoundtrack']().restore(str(padded),native,'native_relight',output_width=64,output_height=48)
                rate,frames,audios=inspect(result['result'][0])
                self.assertEqual((rate,len(frames),audios),(fps,count,1))
                self.assertAlmostEqual(len(frames)/float(rate),count/float(fps),places=8)
                # A selected subrange is counted on the original clock too.
                selected=timing.timeline(source,{**details,'start':float(5/fps),'selected_duration':float(17/fps)})
                self.assertEqual(selected['frames'],17)
                if fps == 30:
                    trimmed_details={**details,'start':float(5/fps),'selected_duration':float(17/fps)}
                    namespace['verify_review']=lambda identity:(directory,{'clip':trimmed_details,'files':{}})
                    trimmed=namespace['GenjLoadReviewedShot']().load('shot','shot',render_long_edge=256,
                                preserve_aspect=True,preserve_source_timing=True)
                    rate,values,_=inspect(trimmed[0])
                    self.assertEqual((rate,len(values)),(fps,17))
                    self.assertAlmostEqual(values[0],30,delta=3,msg='Trim must start on the fifth original frame')
                    final=namespace['GenjRestoreSoundtrack']().restore(trimmed[0],trimmed[3],'trimmed_relight')
                    self.assertEqual((inspect(final['result'][0])[0],len(inspect(final['result'][0])[1])),(fps,17))

    def test_invalid_or_empty_selections_are_rejected(self):
        with self.assertRaises(ValueError):
            timing.timeline('missing.mp4',{'duration':0})


class RelightQueueTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_records_native_frame_count_and_fractional_rate(self):
        import test_wan21_relight as recipe
        s=fixture.studio
        project=recipe.Wan21RelightTests().project()
        cleanup_id=str(uuid.uuid4())
        project['actions']=[{'id':cleanup_id,'stage':'wan_cleanup','state':'complete','next_stage':'wan21_relight'}]
        client=s.Studio.__new__(s.Studio)
        client.collect=lambda p:p
        client.store=SimpleNamespace(save=Mock())
        client.start_watcher=Mock()
        client.server_address='test'
        queued=Mock()
        client.server=SimpleNamespace(number=0,prompt_queue=SimpleNamespace(put=queued),
            trigger_on_prompt=lambda body:body,
            node_replace_manager=SimpleNamespace(apply_replacements=lambda graph:None))
        graph={'272:407:89':{'class_type':'Test','inputs':{'width':1280,'height':704}},
               'wan21_export':{'class_type':'TestOutput','inputs':{'output_width':1280,'output_height':720}}}
        execution=SimpleNamespace(validate_prompt=AsyncMock(return_value=(True,None,['wan21_export'],{})))
        native=dict(frames=90,fps=30000/1001,fps_num=30000,fps_den=1001)
        with patch.dict(sys.modules,{'execution':execution}), \
             patch.object(s,'build_graph',return_value=graph),patch.object(s,'validate_selection'), \
             patch.object(s,'check_asset',return_value=Path('source.mp4')), \
             patch.object(sys.modules[s.__package__],'verify_review',return_value=(None,{'clip':{'frames':72}}),create=True), \
             patch.object(timing,'timeline',return_value=native):
            await client.action(project,'wan21_relight',{'request_key':str(uuid.uuid5(uuid.NAMESPACE_URL,cleanup_id))})
        action=project['actions'][-1]
        self.assertEqual((action['expected_frames'],action['output_fps_num'],action['output_fps_den']),(90,30000,1001))
        self.assertEqual(action['segment_total'],2)
        queued.assert_called_once()

    def test_collector_accepts_source_rate_and_presents_exact_duration(self):
        import test_h3_enhanced1080 as enhanced
        s=fixture.studio
        client=s.Studio.__new__(s.Studio)
        client.store=SimpleNamespace(save=Mock())
        client.server_address='test'
        asset={'type':'output','subfolder':'genj/final','filename':'native.mp4'}
        history={'render':{'status':{'status_str':'success'},'outputs':{'wan21_export':{'gifs':[asset]}}}}
        client.server=SimpleNamespace(prompt_queue=enhanced.FakeQueue(history=history))
        project={'id':'b'*32,'config':{'engine':'wan21'},'phase':'working','results':[],
            'actions':[{'id':'render','stage':'wan21_relight','state':'queued','server_address':'test',
                'expected_frames':90,'output_fps':30000/1001,'output_raster':{'width':1280,'height':720}}]}
        actual={'width':1280,'height':720,'frames':90,'fps':30000/1001,'audio_tracks':1}
        with patch.object(enhanced.enhancement,'checked_output_path',return_value=Path('native.mp4')), \
             patch.object(enhanced.enhancement,'inspect_video',return_value=actual) as inspect_mock, \
             patch.object(s,'sha',return_value='verified'):
            client.collect(project)
        self.assertEqual(project['phase'],'done')
        self.assertEqual(inspect_mock.call_args.kwargs['expected_fps'],30000/1001)
        self.assertEqual(project['results'][0]['duration'],90/(30000/1001))


if __name__=='__main__': unittest.main()
