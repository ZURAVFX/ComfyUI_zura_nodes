"""Raw-plane bounds, public decoder fallbacks and real native calibration."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import types
import struct
from unittest.mock import patch
import unittest

import av
import numpy as np

import v2_bootstrap
import test_studio_media_import as fixture

decoder=fixture.importlib.import_module('ComfyUI_zura_nodes.artist_studio.prores444')
EVIDENCE=v2_bootstrap.ROOT.parent/'evidence/prores12-probe'


class Plane(bytearray):pass


def frame(values, *, matrix=6, code_range=1, alpha=4095):
    planes=[]
    for value in [*values,*([alpha] if alpha is not None else [])]:
        plane=Plane(2*10);plane.width=3;plane.height=2;plane.line_size=10;plane.buffer_size=len(plane)
        np.ndarray((2,3),dtype='<u2',buffer=plane,strides=(10,2))[:]=value
        planes.append(plane)
    return types.SimpleNamespace(format=types.SimpleNamespace(name='yuva444p12le' if alpha is not None else 'yuv444p12le'),
        width=3,height=2,colorspace=matrix,color_range=code_range,planes=planes)


class PlaneTests(unittest.TestCase):
    def test_limited_black_white_and_padded_stride(self):
        for code,expected in [(256,0),(3760,1)]:
            actual=decoder.frame_rgba(frame([code,2048,2048],alpha=1001))
            np.testing.assert_array_equal(actual[...,:3],expected)
            np.testing.assert_array_equal(actual[...,3],np.float32(1001/4095))
    def test_full_range_neutrals_and_opaque_three_plane(self):
        for matrix in (1,5,6,9):
            for code,expected in ((0,0),(4095,1)):
                actual=decoder.frame_rgba(frame([code,2048,2048],matrix=matrix,code_range=2,alpha=None))
                np.testing.assert_array_equal(actual[...,:3],expected);np.testing.assert_array_equal(actual[...,3],1)
    def test_headroom_and_matrix_are_preserved_without_gamma_or_clipping(self):
        source=frame([4095,2048,2048],alpha=0)
        actual=decoder.frame_rgba(source)
        self.assertGreater(float(actual[...,0].min()),1);np.testing.assert_array_equal(actual[...,3],0)
        source=frame([256,2048,0])
        actual=decoder.frame_rgba(source);self.assertLess(float(actual[...,0].max()),0)
        rec601=decoder.frame_rgba(frame([2048,2048,3000],matrix=6))
        rec709=decoder.frame_rgba(frame([2048,2048,3000],matrix=1))
        self.assertGreater(float(np.max(np.abs(rec601-rec709))),.04)
    def test_unknown_actual_frame_matrix_or_range_is_never_guessed(self):
        for matrix,code_range in ((0,1),(2,1),(10,1),(6,0)):
            with self.assertRaisesRegex(ValueError,'declared'):decoder.frame_rgba(frame([256,2048,2048],matrix=matrix,code_range=code_range))
    def test_invalid_stride_buffer_code_or_raster_is_rejected(self):
        for property,value in [('line_size',4),('line_size',-10),('line_size',9),('buffer_size',1),('width',2)]:
            source=frame([256,2048,2048]);setattr(source.planes[0],property,value)
            with self.assertRaisesRegex(ValueError,'stride'):decoder.frame_rgba(source)
        source=frame([4096,2048,2048])
        with self.assertRaisesRegex(ValueError,'twelve-bit samples'):decoder.frame_rgba(source)
        with self.assertRaisesRegex(ValueError,'bounded'):decoder.frame_rgba(frame([256,2048,2048]),max_pixels=5)


def _box(kind,body):return struct.pack('>I4s',len(body)+8,kind)+body


def _track(kind, *, matrix=1, full=False, declaration=b'nclx'):
    colour=declaration+struct.pack('>HHH',1,1,matrix)+(bytes([128 if full else 0]) if declaration==b'nclx' else b'')
    entry=_box(b'ap4h',b'\0'*78+_box(b'colr',colour))
    samples=_box(b'stsd',b'\0'*4+struct.pack('>I',1)+entry)
    handler=_box(b'hdlr',b'\0'*8+kind+b'\0'*12)
    return _box(b'trak',_box(b'mdia',handler+_box(b'minf',_box(b'stbl',samples))))


def _movie(path,*tracks,media_size=4):
    path=Path(path)
    with path.open('wb') as movie:
        movie.write(_box(b'ftyp',b'qt  '+b'\0'*4));movie.write(struct.pack('>I4s',media_size+8,b'mdat'))
        movie.seek(media_size,1);movie.write(_box(b'moov',b''.join(tracks)))
    return path


class ContainerDeclarationTests(unittest.TestCase):
    def test_explicit_video_zero_declaration_recovers_unspecified_frame_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path=_movie(Path(folder)/'declared.mov',_track(b'soun',matrix=6,full=True),_track(b'vide'),_track(b'vide',matrix=9,full=True))
            declared=decoder.mov_colour_declaration(path)
            self.assertEqual(declared,(1,1),'Only the first actual video track supplies pixel metadata')
            unknown=frame([4095,2048,3000],matrix=2,code_range=0,alpha=0)
            actual=decoder.frame_rgba(unknown,declared=declared)
            expected=decoder.frame_rgba(frame([4095,2048,3000],matrix=1,code_range=1,alpha=0))
            np.testing.assert_array_equal(actual,expected)
            self.assertGreater(float(actual[...,0].min()),1,'Hidden extended RGB stays unclipped')
            np.testing.assert_array_equal(actual[...,3],0)
            partial=frame([2048,2048,2048],matrix=1,code_range=0,alpha=1001)
            np.testing.assert_array_equal(decoder.frame_rgba(partial,declared=declared),decoder.frame_rgba(frame([2048,2048,2048],matrix=1,alpha=1001)))
    def test_nclc_and_untagged_frames_do_not_gain_a_guessed_range(self):
        with tempfile.TemporaryDirectory() as folder:
            path=_movie(Path(folder)/'nclc.mov',_track(b'vide',declaration=b'nclc'))
            self.assertIsNone(decoder.mov_colour_declaration(path))
            source=frame([2048,2048,2048],matrix=1,code_range=0)
            source.codec_context=types.SimpleNamespace(colorspace=1,color_range=1)
            with self.assertRaisesRegex(ValueError,'declared'):
                decoder.frame_rgba(source,declared=decoder.mov_colour_declaration(path))
            with self.assertRaisesRegex(ValueError,'declared'):decoder.frame_rgba(source)
    def test_explicit_container_and_known_frame_conflicts_are_rejected(self):
        for source in (frame([2048,2048,2048],matrix=6),frame([2048,2048,2048],matrix=1,code_range=2)):
            with self.assertRaisesRegex(ValueError,'conflicts'):decoder.frame_rgba(source,declared=(1,1))
        with self.assertRaisesRegex(ValueError,'declaration'):decoder.frame_rgba(frame([2048,2048,2048]),declared=(2,1))
    def test_media_payload_is_skipped_and_movie_metadata_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path=_movie(Path(folder)/'large-media.mov',_track(b'vide'),media_size=2*1024*1024)
            original_open=open;reads=[]
            class Watched:
                def __init__(self,stream):self.stream=stream
                def __enter__(self):return self
                def __exit__(self,*args):return self.stream.__exit__(*args)
                def __getattr__(self,name):return getattr(self.stream,name)
                def read(self,size=-1):reads.append(size);return self.stream.read(size)
            with patch('builtins.open',side_effect=lambda *args,**kwargs:Watched(original_open(*args,**kwargs))):
                self.assertEqual(decoder.mov_colour_declaration(path),(1,1))
            self.assertLess(sum(reads),1024,'No mdat payload should be read')
            oversized=Path(folder)/'oversized.mov'
            with oversized.open('wb') as stream:
                stream.write(struct.pack('>I4s',decoder._MAX_MOOV+9,b'moov'));stream.seek(decoder._MAX_MOOV+8);stream.write(b'\0')
            with self.assertRaisesRegex(ValueError,'16 MiB'):decoder.mov_colour_declaration(oversized)
    def test_selected_frames_reads_container_once_without_mutating_alpha_or_rgb(self):
        with tempfile.TemporaryDirectory() as folder:
            path=_movie(Path(folder)/'input.mov',_track(b'vide'))
            frames=[frame([256,2048,3000],matrix=2,code_range=0,alpha=0),frame([3760,2048,2048],matrix=1,code_range=0,alpha=1001)]
            clip=types.SimpleNamespace(streams=types.SimpleNamespace(video=[types.SimpleNamespace(codec_context=types.SimpleNamespace(name='prores'))]),decode=lambda **kwargs:iter(frames),close=lambda:None)
            with patch.object(av,'open',return_value=clip),patch.object(decoder,'mov_colour_declaration',wraps=decoder.mov_colour_declaration) as declaration:
                result=list(decoder.selected_frames({'path':str(path),'width':3,'height':2},0,2,lambda:None))
                declaration.assert_called_once_with(str(path))
            np.testing.assert_array_equal(result[0],decoder.frame_rgba(frame([256,2048,3000],matrix=1,code_range=1,alpha=0)))
            np.testing.assert_array_equal(result[1],decoder.frame_rgba(frame([3760,2048,2048],matrix=1,code_range=1,alpha=1001)))


class FallbackTests(unittest.TestCase):
    def test_real_alpha_planes_keep_pixels_when_decoder_omits_declared_range(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rgba.mov'
            pixels=np.full((48,64,4),128,np.uint8);pixels[...,:3]=[200,70,30]
            pixels[...,3]=np.tile(np.repeat([0,32,128,255],16),(48,1))
            subprocess.run([fixture.tools.find_media_tool('ffmpeg'),'-v','error','-f','rawvideo','-pixel_format','rgba','-video_size','64x48','-framerate','25','-i','-',
                '-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',
                '-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709','-color_range','tv',str(path)],input=pixels.tobytes(),check=True)
            fixture.declare_bt709_limited_mov(path)
            declared=decoder.mov_colour_declaration(path);self.assertEqual(declared,(1,1))
            with av.open(str(path)) as movie:
                decoded=next(movie.decode(video=0));expected=decoder.frame_rgba(decoded,declared=declared)
                try:
                    decoded.color_range=0
                    missing=decoded
                except (AttributeError,TypeError):
                    missing=types.SimpleNamespace(format=decoded.format,width=decoded.width,height=decoded.height,
                        planes=decoded.planes,colorspace=decoded.colorspace,color_range=0)
                self.assertEqual(int(missing.color_range),0)
                actual=decoder.frame_rgba(missing,declared=declared)
            np.testing.assert_array_equal(actual,expected)
            np.testing.assert_allclose(actual[...,3],pixels[...,3]/255,atol=.005)
            self.assertGreater(float(actual[0,0,:3].max()),.5,'Decoded RGB under zero alpha remains unchanged')

    def test_prores_422_stays_on_the_existing_decoder_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'422.mov'
            subprocess.run([fixture.tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25','-frames:v','2',
                '-c:v','prores_ks','-profile:v','3','-pix_fmt','yuv422p10le','-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709',str(path)],check=True)
            paint=fixture.importlib.import_module('ComfyUI_zura_nodes.paintout.paintout');info=paint.describe(str(path))
            with patch.object(decoder,'mov_colour_declaration',side_effect=AssertionError('422 must retain its existing decoder path')):
                self.assertIsNone(decoder.selected_frames(info,0,1,lambda:None))
            reader=fixture.media.model_view._video_frames(info,0,1,None)
            try:actual=next(reader)
            finally:reader.close()
            self.assertEqual(actual.shape,(48,64,4));self.assertTrue(np.isfinite(actual).all())
    def test_cancellation_fences_decoder_open(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaisesRegex(ValueError,'cancelled'):
            decoder.selected_frames({'path':'unopened.mov'},0,1,lambda:fixture.media.model_view._cancelled(cancel))


@unittest.skipUnless((EVIDENCE/'colour.mov').is_file() and (EVIDENCE/'ae-working-reference-dev20.json').is_file(),'Native MOV/FLOAT calibration fixture is not available')
class NativeCalibrationTests(unittest.TestCase):
    def test_native_mov_with_timecode_xmp_matches_declared_working_reference(self):
        movie=EVIDENCE/'colour.mov';identity=json.loads((EVIDENCE/'ae-working-reference-dev20.json').read_text())
        reference_path=Path(identity['framePath']);payload=reference_path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),identity['frame']['sha256'])
        shape=(identity['manifest']['height'],identity['manifest']['width'],4)
        reference=np.frombuffer(payload,dtype='<f4').reshape(shape)
        before=hashlib.sha256(movie.read_bytes()).hexdigest()
        paint=fixture.importlib.import_module('ComfyUI_zura_nodes.paintout.paintout');info=paint.describe(str(movie))
        with av.open(str(movie)) as clip:
            native=next(clip.decode(video=0));self.assertEqual(int(native.colorspace),6);self.assertEqual(int(native.color_range),1)
            self.assertTrue(any(stream.type=='data' for stream in clip.streams),'Routine native timecode data remains admitted')
        reader=fixture.media.model_view._video_frames(info,0,1,None)
        try:actual=next(reader)
        finally:reader.close()
        layout=json.loads((EVIDENCE/'precision-colour-opaque.json').read_text())
        patches=[]
        for patch in layout['colourPatches']:
            x,y,w,h=patch['sample'];delta=np.mean(actual[y:y+h,x:x+w,:3],axis=(0,1))-np.mean(reference[y:y+h,x:x+w,:3],axis=(0,1));patches.append(float(np.max(np.abs(delta))))
        # Ramp lies in the top 128 rows, away from encoded colour-patch edges.
        xs=layout['graySteps']['sampleCentersX'];rows=slice(16,112)
        grey_actual=np.array([actual[rows,x,:3].mean() for x in xs]);grey_reference=np.array([reference[rows,x,:3].mean() for x in xs])
        grey_mae=float(np.mean(np.abs(grey_actual-grey_reference)))
        self.assertLess(max(patches),.0006);self.assertLess(grey_mae,.00015)
        np.testing.assert_array_equal(actual[...,3],reference[...,3])
        owned=fixture.ImportTests();owned.setUp()
        try:
            asset_id,path=owned.asset('native.mov','video');shutil.copyfile(movie,path);owned.register(asset_id,path,'video')
            prepared=fixture.media.prepare_import({'asset_id':asset_id,'colour_space':'srgb_display','frame':0},owned.store,owned.check,owned.roots)
            self.assertEqual(prepared['processingInput']['studioAsset']['processingView']['sourceColour'],'srgb_display','Declared working sRGB is retained independently of the AE codec transfer tag')
            self.assertEqual(prepared['colour']['encoding'],'srgb_display')
            original=prepared['processingInput']['stills']['first']['processingView']['originalSource']['displaySelector']
            displayed,space,_=fixture.media.display.read_original(original,0,owned.store,owned.check,owned.roots)
            np.testing.assert_array_equal(displayed,actual);self.assertEqual(space,'srgb_display')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        finally:owned.tearDown()
        self.assertEqual(hashlib.sha256(movie.read_bytes()).hexdigest(),before)
        print(json.dumps({'publicProresCalibration':{'movieSha256':before,'referenceSha256':identity['frame']['sha256'],'actualFrameMatrix':6,'actualFrameRange':1,'greyMAE':grey_mae,'maxColourPatchError':max(patches),'opaqueAlphaExact':True,'routineDataTrackAdmitted':True,'sourceColourDeclared':'srgb_display','genuine12BitCertified':False}}))


if __name__=='__main__':unittest.main()
