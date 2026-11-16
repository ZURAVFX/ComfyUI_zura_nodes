"""AE Render Queue PNG16 keeps the same numeric SDR view as PNG8."""
import hashlib
import importlib
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
import zlib

import numpy as np
import OpenImageIO as oiio
from PIL import Image
import v2_bootstrap  # noqa: F401

studio=importlib.import_module('ComfyUI_zura_nodes.comfylink.studio_sessions')
float_io=importlib.import_module('ComfyUI_zura_nodes.comfylink.float_io')
processing=importlib.import_module('ComfyUI_zura_nodes.comfylink.studio_processing')
package='ComfyUI_zura_nodes.artist_studio'
if package not in sys.modules:
    stub=types.ModuleType(package);stub.__path__=[str(Path(__file__).resolve().parents[1]/'artist_studio')]
    sys.modules[package]=stub
hdr_sequence=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_sequence')


def write_rgba16(path,values):
    def chunk(name,payload):return struct.pack('>I',len(payload))+name+payload+struct.pack('>I',zlib.crc32(name+payload))
    rows=b''.join(b'\x00'+row.astype('>u2').tobytes() for row in values)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',values.shape[1],values.shape[0],16,6,0,0,0))
                     +chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))


class NativePNG16Tests(unittest.TestCase):
    def test_untagged_ae_exr_needs_separate_pixel_identical_colour_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=np.array([[[np.float32(-.125),np.float32(.25),np.float32(1.25),np.float32(1)]]],dtype='<f4')
            ae=root/'native-still-exr32_00000.exr';writer=oiio.ImageOutput.create(str(ae))
            spec=oiio.ImageSpec(1,1,4,oiio.FLOAT);spec.channelnames=['R','G','B','A']
            self.assertTrue(writer.open(str(ae),spec));self.assertTrue(writer.write_image(raw));writer.close()
            self.assertEqual(hdr_sequence.discover_colour([ae]),{},'The AE file has no ComfyLink colour header')
            for encoding,resolved in (('scene_linear_rec709','linear_rec709'),('acescg','acescg')):
                tagged=root/(encoding+'.exr')
                float_io.write_exr(tagged,raw,colour={'encoding':encoding,'sceneLinear':True},storage='float32')
                decoded,_=float_io.read_exr(tagged)
                np.testing.assert_array_equal(decoded.view('<u4'),raw.view('<u4'))
                self.assertEqual(hdr_sequence.discover_colour([tagged])['resolved_colour'],resolved)

    def test_native_png8_and_exr32_keep_their_actual_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);frame=root/'000001.rgba32f'
            raw=np.array([[[np.float32(-.125),np.float32(.25),np.float32(1.25),np.float32(1)]]],dtype='<f4')
            raw.tofile(frame)
            manifest={'width':1,'height':1}
            png=root/'native-still-png8_00000.png'
            expected=np.rint(np.clip(raw,0,1)*255).astype(np.uint8)
            Image.fromarray(expected,'RGBA').save(png)
            np.testing.assert_array_equal(studio.StudioSessions.verify_native_still(png,frame,manifest,'png8'),expected)
            exr=root/'native-still-exr32_00000.exr';writer=oiio.ImageOutput.create(str(exr))
            spec=oiio.ImageSpec(1,1,4,oiio.FLOAT);spec.channelnames=['R','G','B','A']
            self.assertTrue(writer.open(str(exr),spec));self.assertTrue(writer.write_image(raw));writer.close()
            self.assertIsNone(studio.StudioSessions.verify_native_still(exr,frame,manifest,'exr32'))

    def test_actual_render_codes_match_existing_numeric_eight_bit_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);png=root/'native-still-png16_00000.png';frame=root/'000001.rgba32f'
            raw=np.array([[[np.float32(-.2),np.float32(.18),np.float32(1.2),np.float32(1)],
                           [np.float32(.5),np.float32(.75),np.float32(1),np.float32(1)]]],dtype='<f4')
            raw.tofile(frame)
            codes=np.rint(np.clip(raw.astype(np.float64),0,1)*65535).astype(np.uint16)
            write_rgba16(png,codes)
            colour={'encoding':'ae_project_icc','management':'icc','sceneLinear':True,'profileSha256':'a'*64}
            manifest={'sampleType':'float32','sourceBitDepth':32,'alphaAssociation':'straight','colour':colour,
                      'width':2,'height':1,'frames':[{'index':0}],
                      'frameRate':{'numerator':30000,'denominator':1001},
                      'sourceStart':{'numerator':0,'denominator':30000}}
            expected8=processing.encode_sdr8(raw,derived=True,processor=None)
            np.testing.assert_array_equal(studio.StudioSessions.verify_native_png16(png,frame,manifest),expected8)
            tampered=codes.copy();tampered[0,0,1]=np.uint16(int(tampered[0,0,1])+1000)
            write_rgba16(png,tampered)
            with self.assertRaisesRegex(ValueError,'differs'):
                studio.StudioSessions.verify_native_png16(png,frame,manifest)
            descriptor={'schemaVersion':2,'kind':'native_still','profile':'png16','file':{'filename':png.name,'sha256':hashlib.sha256(png.read_bytes()).hexdigest(),
                        'byteLength':png.stat().st_size},'width':2,'height':1,'frameRate':manifest['frameRate'],
                        'sourceStart':manifest['sourceStart'],'sourceColour':colour,'sourceBitDepth':32,
                        'transferBitDepth':16,'storageBitDepth':16,'codec':'png','hasAlpha':True,'requestedPrecision':'prores12',
                        'preserveRGBQualified':False}
            self.assertEqual(studio.StudioSessions.validate_native_still_descriptor(descriptor,manifest),descriptor)
            for profile,requested,bits,suffix in (('png8','sdr8',8,'png'),('exr32','float32',32,'exr')):
                other={**descriptor,'profile':profile,'requestedPrecision':requested,'transferBitDepth':bits,
                       'storageBitDepth':bits,'codec':suffix,
                       'file':{**descriptor['file'],'filename':f'native-still-{profile}_00000.{suffix}'}}
                self.assertEqual(studio.StudioSessions.validate_native_still_descriptor(other,manifest),other)
            with self.assertRaisesRegex(ValueError,'identity'):
                studio.StudioSessions.validate_native_still_descriptor({**descriptor,'transferBitDepth':8},manifest)


if __name__=='__main__':unittest.main()
