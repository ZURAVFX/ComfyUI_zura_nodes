"""Raw-plane bounds, public decoder fallbacks and real native calibration."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import types
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


class FallbackTests(unittest.TestCase):
    def test_prores_422_stays_on_the_existing_decoder_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'422.mov'
            subprocess.run([fixture.tools.find_media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc=size=64x48:rate=25','-frames:v','2',
                '-c:v','prores_ks','-profile:v','3','-pix_fmt','yuv422p10le','-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709',str(path)],check=True)
            paint=fixture.importlib.import_module('ComfyUI_zura_nodes.paintout.paintout');info=paint.describe(str(path))
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
