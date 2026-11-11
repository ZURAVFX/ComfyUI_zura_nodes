"""Bounded whole-shot policy and streaming tests. No models or AE process."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import float_io as fio

COLOUR = {"encoding": "acescg", "sceneLinear": True}
RATE = {"numerator": 25, "denominator": 1}


def shot_manifest(width=3840, height=2160, count=101):
    return {"schemaVersion": 1, "sampleType": "float32", "layout": "RGBA", "byteOrder": "little",
        "width": width, "height": height, "alphaAssociation": "straight", "sourceBitDepth": 32,
        "colour": copy.deepcopy(COLOUR), "frameRate": RATE.copy(), "frames": [
            {"index": i, "filename": f"{i+1:06d}.rgba32f", "byteLength": width*height*16,
             "sha256": "0"*64, "time": {"numerator": i, "denominator": 25}} for i in range(count)]}


def tiny_frames(count=101):
    for index in range(count):
        frame = np.full((2, 2, 4), np.float32(index / 32), dtype=np.float32)
        frame[0, 0] = (-0.0, 1/32768, 65504, 0)
        frame[0, 1] = (-4, 2.5, index, .5)
        yield frame


class LargeShotTests(unittest.TestCase):
    def test_exact_4k_101_frame_metadata_admitted_without_pixels(self):
        manifest = fio.validate_manifest(shot_manifest())
        self.assertEqual(sum(f['byteLength'] for f in manifest['frames']), 13_403_750_400)
        self.assertEqual(manifest['frameRate'], RATE)
        self.assertEqual((manifest['width'], manifest['height'], len(manifest['frames'])), (3840,2160,101))
        with self.assertRaisesRegex(ValueError, 'Transfer byte limit'):
            fio.validate_manifest(shot_manifest(count=130))

    def test_stream_verify_and_writer_never_stack_a_batch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(np, 'stack', side_effect=AssertionError('batch stack forbidden')):
            relative, manifest = fio.write_transfer_frames(temp, 'ComfyLink/' + 'a'*32, tiny_frames(),
                colour=COLOUR, frame_rate=RATE, expected_count=101)
            verified = fio.verify_transfer(temp, relative)
            self.assertEqual(verified, manifest)
            self.assertEqual(len({f['sha256'] for f in manifest['frames']}),101)
            for actual, expected in zip(fio.iter_transfer(temp, relative), tiny_frames()):
                self.assertEqual(actual.tobytes(), expected.tobytes())
            batch, _ = fio.load_transfer(temp, relative)
            self.assertEqual(batch.shape,(101,2,2,4))

    def test_batch_admission_uses_available_ram_before_allocation(self):
        with patch.object(fio, 'available_memory_bytes', return_value=1 << 30):
            with self.assertRaisesRegex(ValueError, 'currently available RAM'):
                fio.check_batch_memory(13_403_750_400)
        with patch.object(fio, 'available_memory_bytes', return_value=64 << 30):
            fio.check_batch_memory(13_403_750_400)

    def test_actual_ocio_identity_retained_without_inferred_encoding(self):
        colour={"encoding":"unknown","sceneLinear":False,"management":"ocio","ocioConfig":"ACES config identity",
            "ocioConfigPath":"C:/fixture/config.ocio","ocioWorkingSpace":"ACEScg",
            "ocioConfigHandleSha256":"a"*64,"ocioWorkingSpaceHandleSha256":"b"*64}
        self.assertEqual(fio.validate_colour(colour),colour)
        with tempfile.TemporaryDirectory() as temp:
            relative,manifest=fio.write_transfer_frames(temp,'ComfyLink/'+'c'*32,tiny_frames(1),colour=colour,frame_rate=RATE,expected_count=1)
            self.assertEqual(fio.verify_transfer(temp,relative)['colour'],colour)
            self.assertEqual(manifest['colour']['encoding'],'unknown')
        for change in ({"encoding":"acescg","sceneLinear":True},{"ocioConfig":"x"*32769},{"ocioConfigHandleSha256":"not-a-hash"}):
            with self.assertRaises(ValueError):fio.validate_colour({**colour,**change})

    def test_stream_failure_does_not_publish_partial_manifest(self):
        def incomplete():
            yield next(tiny_frames(1))
            raise ValueError('source ended')
        with tempfile.TemporaryDirectory() as temp:
            folder = 'ComfyLink/' + 'b'*32
            with self.assertRaisesRegex(ValueError,'source ended'):
                fio.write_transfer_frames(temp,folder,incomplete(),colour=COLOUR,frame_rate=RATE,expected_count=101)
            self.assertFalse((Path(temp)/folder).exists())
            self.assertEqual(list((Path(temp)/'ComfyLink').iterdir()),[])


def qualify_actual_4k_shot(evidence_directory):
    """Explicit manual disk qualification, never part of ordinary test discovery.

    Uses real 3840x2160 FLOAT files for all 101 unique frames, not sparse files
    or a model. Only one frame is generated/decoded at a time. The exclusively
    created temporary dataset is removed after its hashes and RSS are recorded.
    """
    import threading
    import time
    import shutil
    import psutil
    base=Path(evidence_directory).absolute();base.mkdir(parents=True,exist_ok=True)
    width,height,count=3840,2160,101
    raw_bytes=width*height*16*count
    free=shutil.disk_usage(base).free
    required=raw_bytes*3+8*1024**3
    if free<required:raise ValueError('Insufficient disk for actual whole-shot qualification and safety headroom')
    if fio.available_memory_bytes()<8*1024**3:raise ValueError('Insufficient available RAM for bounded frame buffers and OS/AE headroom')
    process=psutil.Process();baseline=process.memory_info().rss;peak=[baseline]
    stop=threading.Event()
    def monitor():
        while not stop.wait(.05):peak[0]=max(peak[0],process.memory_info().rss)
    sampler=threading.Thread(target=monitor,daemon=True);sampler.start()
    started=time.perf_counter();io_before=process.io_counters();phases={}
    report={'schemaVersion':1,'width':width,'height':height,'frameCount':count,'frameRate':RATE,
            'rawBytes':raw_bytes,'rawGiB':raw_bytes/2**30,'freeDiskBefore':free,'requiredDiskPreflight':required,
            'baselineRSS':baseline,'colour':COLOUR,'precision':'float32','alphaAssociation':'straight',
            'qualification':'synthetic disk transport and FLOAT EXR roundtrip; no model or AE/backend launch'}
    try:
        with tempfile.TemporaryDirectory(prefix='.large-shot-',dir=base) as temporary:
            root=Path(temporary).resolve()
            if not root.is_relative_to(base.resolve()):raise ValueError('Qualification workspace escaped its owned root')
            source=root/'source';output=root/'output';cache=root/'float-exr-cache'
            source.mkdir();output.mkdir();cache.mkdir()
            def originals():
                for index in range(count):
                    rng=np.random.default_rng(20261111+index)
                    rgba=rng.random((height,width,4),dtype=np.float32)
                    rgba[...,:3]*=8;rgba[...,:3]-=2
                    rgba[0,0]=(-0.0,1/32768,65504,0)
                    rgba[0,1]=(-4,2.5,index/16,.5)
                    yield rgba
                    if (index+1)%10==0 or index+1==count:print(json.dumps({'phase':'raw_write','frames':index+1,'total':count}),flush=True)
            tick=time.perf_counter()
            relative,manifest=fio.write_transfer_frames(source,'ComfyLink/'+'a'*32,originals(),colour=COLOUR,frame_rate=RATE,expected_count=count)
            phases['writeRawSeconds']=time.perf_counter()-tick
            tick=time.perf_counter();fio.verify_transfer(source,relative);phases['verifyRawSeconds']=time.perf_counter()-tick
            if len({entry['sha256'] for entry in manifest['frames']})!=count:raise ValueError('Source frames were repeated')
            tick=time.perf_counter()
            for index,rgba in enumerate(fio.iter_transfer(source,relative)):
                if fio.available_memory_bytes()<2*1024**3:raise ValueError('Available RAM dropped below streamed-frame safety headroom')
                path=cache/f'{index+1:06d}.exr'
                fio.write_exr(path,rgba,colour=COLOUR,storage='float32',alpha_association='straight')
                decoded,side=fio.read_exr(path)
                if side['storage']!='float32' or side['colour']!=COLOUR or hashlib.sha256(memoryview(decoded).cast('B')).hexdigest()!=manifest['frames'][index]['sha256']:
                    raise ValueError(f'FLOAT EXR changed actual RGBA bytes at frame {index}')
                del decoded
                if (index+1)%10==0 or index+1==count:print(json.dumps({'phase':'float_exr_cache','frames':index+1,'total':count,'rssMiB':process.memory_info().rss/2**20}),flush=True)
            phases['writeAndVerifyEXRSeconds']=time.perf_counter()-tick
            tick=time.perf_counter()
            def returned():
                for index in range(count):
                    decoded,side=fio.read_exr(cache/f'{index+1:06d}.exr')
                    yield decoded
                    if (index+1)%10==0 or index+1==count:print(json.dumps({'phase':'raw_return','frames':index+1,'total':count}),flush=True)
            result_relative,result=fio.write_transfer_frames(output,'ComfyLink/'+'b'*32,returned(),colour=COLOUR,frame_rate=RATE,expected_count=count)
            fio.verify_transfer(output,result_relative)
            phases['returnAndVerifySeconds']=time.perf_counter()-tick
            if [entry['sha256'] for entry in result['frames']]!=[entry['sha256'] for entry in manifest['frames']]:raise ValueError('Whole-shot raw return hashes differ')
            report.update(status='passed',allFrameSHA256Equal=True,all101FramesUnique=True,actualFloatEXRStorageVerified=True,
                frameHashes=[entry['sha256'] for entry in result['frames']],sourceBytes=sum(entry['byteLength'] for entry in manifest['frames']),
                returnedBytes=sum(entry['byteLength'] for entry in result['frames']))
    finally:
        stop.set();sampler.join();io_after=process.io_counters()
        report.update(peakRSS=peak[0],peakRSSMiB=peak[0]/2**20,elapsedSeconds=time.perf_counter()-started,phases=phases,
            ioReadBytes=io_after.read_bytes-io_before.read_bytes,ioWriteBytes=io_after.write_bytes-io_before.write_bytes,
            freeDiskAfterCleanup=shutil.disk_usage(base).free)
        (base/'large-shot-4k101-profile.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='frameHashes'}),flush=True)
    return report


if __name__ == '__main__':
    unittest.main()
