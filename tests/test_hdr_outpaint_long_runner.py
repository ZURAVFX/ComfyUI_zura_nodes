import importlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_artist_studio

planner = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_plan')
runner = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_runner')
inspect_video = importlib.import_module('ComfyUI_zura_nodes.artist_studio.enhancement').inspect_video


class HDRLongRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_review_assembles_exact_selected_range(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg required.')
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection,parts,_=planner.plan_hdr_windows(source,start=.517,duration=1.,width=192,height=192,
            left=32,top=32,right=32,bottom=32,colour_space='pq_rec2020')
        graphs=[];paths={}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            async def submit(sub,graph):
                index=len(graphs);graphs.append(graph);path=root/f'review{index}.mp4';paths[str(index)]=path
                subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=orange:s=192x192:r=24',
                    '-frames:v',str(sub['frames']),'-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True)
                return str(index)
            async def wait(identity):return paths[identity]
            async def cancel(identity):self.fail('Completed review children must not be cancelled.')
            result=await runner.run_long_hdr_review(source=source,selection=selection,review_key=selection['review_key'],
                submit=submit,wait=wait,cancel=cancel,update=lambda *args:None,ffmpeg=ffmpeg,
                output=root/'review.mp4',check_asset=lambda _:None)
            self.assertEqual(inspect_video(result,expected_frames=24,expected_width=192,expected_height=192,expected_fps=24)['frames'],24)
            self.assertEqual(len(graphs),len(parts))
            self.assertAlmostEqual(graphs[1]['hdr_source']['inputs']['start_seconds'],.517+parts[1].start/24)

    async def test_anchored_sections_assemble_full_range_and_hold_tail(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg: self.skipTest('FFmpeg is required.')
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection,parts,_=planner.plan_hdr_windows(source,start=.517,duration=1.,width=192,height=192,
            left=32,top=32,right=32,bottom=32,colour_space='pq_rec2020')
        self.assertGreater(len(parts),1)
        anchors=[]; graphs=[]; ids={}; updates=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            async def submit(subplan,graph):
                index=len(graphs); graphs.append(graph); path=root/f'section{index}.mp4'; ids[str(index)]=path
                subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=192x192:r=24',
                    '-frames:v',str(subplan['frames']),'-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True)
                return str(index)
            async def wait(identity): return ids[identity]
            async def cancel(identity): self.fail('Completed children must not be cancelled.')
            async def anchor(path,index): anchors.append((path,index)); return 'genj_studio/previous.png'
            result=await runner.run_long_hdr_sdr_pass(source=source,selection=selection,review_key=selection['review_key'],
                prompt='Extend',seed=42,submit=submit,wait=wait,cancel=cancel,update=lambda *args:updates.append(args),
                make_anchor=anchor,ffmpeg=ffmpeg,output=root/'assembled.mp4',check_asset=lambda asset:None)
            self.assertEqual(inspect_video(result,expected_frames=25,expected_width=192,expected_height=192,expected_fps=24)['frames'],25)
            self.assertEqual(len(graphs),len(parts));self.assertEqual(len(anchors),len(parts)-1)
            self.assertEqual(anchors[0][1],parts[0].count-parts[1].overlap)
            self.assertEqual(graphs[1]['guide']['inputs']['latent'],['zura_anchor_i2v',0])
            self.assertEqual(updates[-1][0],'assembling')
            with self.assertRaisesRegex(ValueError,'already exists'):
                await runner.run_long_hdr_sdr_pass(source=source,selection=selection,review_key=selection['review_key'],
                    prompt='',seed=42,submit=submit,wait=wait,cancel=cancel,update=lambda *args:None,
                    make_anchor=anchor,ffmpeg=ffmpeg,output=result,check_asset=lambda asset:None)
