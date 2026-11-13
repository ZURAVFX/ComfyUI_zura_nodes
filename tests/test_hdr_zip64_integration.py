"""Stored native EXR ZIP64 through original-pixel display and AE transfer."""
from pathlib import Path
import copy
import importlib
import struct
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import test_hdr_archive_display as display_tests
import test_comfylink_studio as bridge_tests


class HDRZIP64DisplayTests(unittest.TestCase):
    def test_actual_hdr_frames_with_offset_only_and_size_zip64_extensions(self):
        fixture=display_tests.NativeArchiveDisplayTests();fixture.setUp()
        try:
            original,pixels=fixture.exr();payload=original.read_bytes()
            for label,limit,forced in [('offset',len(payload)*2,False),('sizes',64,False),('local',None,True)]:
                with self.subTest(label=label):
                    path=fixture.output/(label+'.zip')
                    if limit is None:limit=zipfile.ZIP64_LIMIT
                    with patch.object(zipfile,'ZIP64_LIMIT',limit),zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
                        for index in range(3):
                            info=zipfile.ZipInfo(f'frame_{index:05d}.exr');info.file_size=len(payload)
                            with archive.open(info,'w',force_zip64=forced) as target:target.write(payload)
                    before=path.read_bytes()
                    if label!='local':
                        self.assertIn(b'PK\x06\x06',before)
                        self.assertNotEqual(struct.unpack('<4s4H2LH',before[-22:])[6],0xffffffff)
                    actual,metadata=display_tests.archive_display.read_archive_frame(path,2)
                    np.testing.assert_array_equal(actual[...,:3],pixels)
                    self.assertEqual(metadata['frame_count'],3);self.assertEqual(path.read_bytes(),before)
        finally:fixture.tearDown()


class HDRZIP64TransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_half_float_zip64_originals_transfer_without_reencoding(self):
        fixture=bridge_tests.StudioHTTPTest(methodName='runTest');await fixture.asyncSetUp()
        try:
            native=fixture.native_module('hdr_package')
            paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
            session,headers=await fixture.create()
            source=copy.deepcopy(fixture.manifest);source['frameRate']={'numerator':30000,'denominator':1001}
            fixture.service.sessions[session['id']].source={'manifest':source}
            for storage in ('half','float32'):
                with self.subTest(storage=storage):
                    prefix='zip64_'+storage;directory=fixture.outputs/'genj/hdr'/prefix;directory.mkdir(parents=True)
                    paintout.save_exr(directory/'frame_00000.exr',np.ascontiguousarray(fixture.payload[0,:,:,:3]),'acescg',storage=='half')
                    with patch.object(zipfile,'ZIP64_LIMIT',64):path=native.package_sequence(fixture.outputs,prefix,1)
                    before=path.read_bytes();self.assertIn(b'PK\x06\x06',before)
                    with patch('comfylink.studio_sessions._studio_module',side_effect=fixture.native_module):
                        response=await fixture.client.post(fixture.route(session,'/result'),headers=headers,json={'kind':'hdr_sequence','master':{'filename':path.name,'subfolder':'genj/hdr','type':'output'}})
                    self.assertEqual(response.status,200,await response.text())
                    self.assertEqual(fixture.received_originals[-1][1],before)
                    self.assertEqual(fixture.received[-1]['manifest']['frameRate'],source['frameRate'])
                    self.assertEqual(path.read_bytes(),before)
        finally:await fixture.asyncTearDown()


if __name__=='__main__':unittest.main()
