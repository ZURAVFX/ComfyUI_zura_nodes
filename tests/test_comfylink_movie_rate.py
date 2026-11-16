import shutil,subprocess,tempfile,unittest
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
import numpy as np
import av
from comfylink.studio_rate import reinterpret_movie
from comfylink.studio_direct_video import prepare_video_delivery

@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
class MovieRateTests(unittest.TestCase):
    def test_all_source_frames_survive_model_clock_and_ae_return(self):
        for rate in (Fraction(24000,1001),Fraction(25),Fraction(30000,1001),Fraction(60)):
            with self.subTest(rate=rate),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'source.mkv';count=17
                with av.open(str(source),'w') as c:
                    s=c.add_stream('ffv1',rate=rate);s.width=64;s.height=48;s.pix_fmt='bgr0'
                    for n in range(count):
                        f=av.VideoFrame.from_ndarray(np.full((48,64,3),n*10,np.uint8),format='rgb24')
                        for packet in s.encode(f):c.mux(packet)
                    for packet in s.encode():c.mux(packet)
                audio=root/'audio.mkv'
                subprocess.run(['ffmpeg','-v','error','-i',str(source),'-f','lavfi','-i',f'sine=frequency=1000:sample_rate=48000:duration={float(count/rate)}','-map','0:v','-map','1:a','-c:v','copy','-c:a','pcm_s16le',str(audio)],check=True)
                model=reinterpret_movie(audio,root/'model.mkv',{'numerator':rate.numerator,'denominator':rate.denominator},24,count)
                with av.open(str(model)) as c:
                    self.assertEqual(Fraction(c.streams.video[0].average_rate.numerator,c.streams.video[0].average_rate.denominator),24)
                    frames=list(c.decode(video=0))
                    self.assertEqual([round(float(f.to_ndarray(format='rgb24').mean())/10) for f in frames],list(range(count)))
                with av.open(str(model)) as c:
                    samples=np.concatenate([f.to_ndarray().reshape(-1) for f in c.decode(audio=0)])
                    self.assertAlmostEqual(len(samples)/48000,count/24,delta=.025)
                    frequency=np.argmax(abs(np.fft.rfft(samples)))*48000/len(samples)
                    self.assertAlmostEqual(frequency,1000,delta=5)
                if rate==Fraction(30000,1001):
                    run=subprocess.run
                    def old_remux(command,**kwargs):
                        if '-c:v' in command and command[command.index('-c:v')+1]=='copy':
                            command=list(command);command[command.index('-r')+1]=str(rate)
                        return run(command,**kwargs)
                    with patch('comfylink.studio_rate.subprocess.run',side_effect=old_remux):
                        fallback=reinterpret_movie(audio,root/'fallback.mkv',{'numerator':rate.numerator,'denominator':rate.denominator},24,count)
                    with av.open(str(fallback)) as c:
                        self.assertEqual(Fraction(c.streams.video[0].average_rate.numerator,c.streams.video[0].average_rate.denominator),24)
                        self.assertEqual([round(float(f.to_ndarray(format='rgb24').mean())/10) for f in c.decode(video=0)],list(range(count)))
                result=prepare_video_delivery(model,root,precision='prores12',width=64,height=48,frame_count=count,frame_rate={'numerator':rate.numerator,'denominator':rate.denominator})
                with av.open(str(result)) as c:
                    self.assertEqual(Fraction(c.streams.video[0].average_rate.numerator,c.streams.video[0].average_rate.denominator),rate)
                    frames=list(c.decode(video=0));self.assertEqual(len(frames),count)
                    self.assertEqual([round(float(f.to_ndarray(format='rgb24').mean())/10) for f in frames],list(range(count)))

                with av.open(str(result)) as c:
                    samples=np.concatenate([f.to_ndarray().reshape(-1) for f in c.decode(audio=0)]).astype(np.float32)
                    self.assertAlmostEqual(len(samples)/48000,float(count/rate),delta=.025)
                    frequency=np.argmax(abs(np.fft.rfft(samples)))*48000/len(samples)
                    self.assertAlmostEqual(frequency,1000,delta=6)


class SourceRateEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_model_source_keeps_return_authority_and_is_cached(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer,TestClient
        from comfylink.studio_sessions import StudioSessions,Session
        import asyncio,time,json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mkv'
            with av.open(str(source),'w') as c:
                stream=c.add_stream('ffv1',rate=Fraction(30000,1001));stream.width=64;stream.height=48;stream.pix_fmt='bgr0'
                for n in range(17):
                    frame=av.VideoFrame.from_ndarray(np.full((48,64,3),n,np.uint8),format='rgb24')
                    for packet in stream.encode(frame):c.mux(packet)
                for packet in stream.encode():c.mux(packet)
            service=StudioSessions(root,root)
            session=Session('a'*32,'private','broker','token','',{'capabilities':{'source':True}},time.time()+300)
            session.source={'studioAsset':{'file':'source.mkv','id':'original'},'sourceTransfer':{'kind':'native_video','frameRate':{'numerator':30000,'denominator':1001}},'frameCount':17,'width':64,'height':48}
            service.sessions[session.id]=session;service.authorize=lambda request:session
            uploaded=[]
            async def upload(request):
                part=await (await request.multipart()).next();data=await part.read();uploaded.append(data)
                with av.open(__import__('io').BytesIO(data)) as movie:
                    self.assertEqual(movie.streams.video[0].average_rate,24)
                    self.assertEqual(sum(1 for _ in movie.decode(video=0)),17)
                return web.json_response({'id':'b'*32,'file':'working.mkv','preview_status':'ready','preview_url':'/model.mp4','duration':17/24})
            async def info(request):return web.json_response({'path':str(root/'working.mkv'),'frames':17,'fps':24})
            app=web.Application();app.router.add_post('/model-source',service.model_source);app.router.add_post('/zura/studio/upload',upload);app.router.add_post('/zura/studio/assets/{id}/ripple',info)
            async with TestServer(app) as server:
                session.origin=str(server.make_url('')).rstrip('/')
                async with TestClient(server) as client:
                    response=await client.post('/model-source',json={'frameRate':24});self.assertEqual(response.status,200,await response.text())
                    result=await response.json();self.assertEqual(result['studioAsset']['id'],'b'*32)
                    self.assertEqual(result['sourceTransfer']['frameRate'],{'numerator':30000,'denominator':1001})
                    self.assertEqual(session.source['studioAsset']['id'],'original')
                    self.assertEqual(result['modelFrameRate'],{'numerator':24,'denominator':1})
                    response=await client.post('/model-source',json={'frameRate':24});self.assertEqual(response.status,200);self.assertEqual(len(uploaded),1)
