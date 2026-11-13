"""Real ZIP64 records at small test thresholds, without multi-gigabyte files."""
from pathlib import Path
import io
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import archive_zip


def archive_bytes(limit=None, *, force=False, extra=b''):
    output=io.BytesIO()
    context=patch.object(zipfile,'ZIP64_LIMIT',limit) if limit is not None else patch.object(zipfile,'ZIP64_LIMIT',zipfile.ZIP64_LIMIT)
    with context, zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
        for index in range(3):
            info=zipfile.ZipInfo(f'frame_{index:05d}.exr');info.compress_type=zipfile.ZIP_STORED;info.extra=extra;info.file_size=100
            with archive.open(info,'w',force_zip64=force) as member:member.write(bytes([index+1])*100)
    return output.getvalue()


class ArchiveZIP64Tests(unittest.TestCase):
    def validate(self,data):
        source=io.BytesIO(data)
        directory=archive_zip.bounded_directory(source,len(data),max_entries=10,max_directory=4096)
        with zipfile.ZipFile(source) as archive:
            records=archive_zip.validate_infos(source,archive.infolist(),directory)
            ordered=sorted(records,key=lambda record:record['offset'])
            for index,record in enumerate(ordered):
                entry={**record,'end':ordered[index+1]['offset'] if index+1<len(ordered) else directory.offset}
                start=archive_zip.member_start(source,entry)
                self.assertLessEqual(start+record['size'],entry['end'])
            return directory,records

    def test_standard_archive_still_reads_identical_payload(self):
        data=archive_bytes();directory,records=self.validate(data)
        self.assertEqual(directory.count,3);self.assertTrue(all(not record['extra'] for record in records))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'native.zip';path.write_bytes(data)
            with archive_zip.bounded_stored_archive(path) as archive:
                self.assertEqual(archive.read('frame_00002.exr'),bytes([3])*100)
            self.assertEqual(path.read_bytes(),data)

    def test_python_zip64_before_uint32_overflow_with_offset_only_extras(self):
        data=archive_bytes(128);self.assertIn(b'PK\x06\x06',data)
        # Python emits the ZIP64 footer at its own threshold while ordinary
        # fields retain their small, non-sentinel real values.
        eocd=struct.unpack('<4s4H2LH',data[-22:])
        self.assertLess(eocd[6],0xffffffff);self.assertLess(eocd[5],0xffffffff)
        directory,records=self.validate(data)
        self.assertEqual(directory.count,3)
        self.assertEqual([len(record['extra']) for record in records],[0,12,12])
        self.assertTrue(all(record['offset']<0xffffffff for record in records))

    def test_python_zip64_sizes_and_offset_and_local_size_extensions(self):
        data=archive_bytes(64);directory,records=self.validate(data)
        self.assertEqual(directory.count,3)
        self.assertEqual([len(record['extra']) for record in records],[20,28,28])
        self.assertEqual([record['size'] for record in records],[100]*3)

    def test_zip64_footer_alone_when_last_payload_crosses_the_python_threshold(self):
        data=archive_bytes(300);self.assertIn(b'PK\x06\x06',data)
        directory,records=self.validate(data)
        self.assertGreater(directory.offset,300)
        self.assertTrue(all(not record['extra'] for record in records))

    def test_force_zip64_local_headers_with_ordinary_central_directory(self):
        data=archive_bytes(force=True);directory,records=self.validate(data)
        self.assertNotIn(b'PK\x06\x06',data)
        self.assertTrue(all(not record['extra'] for record in records))
        self.assertEqual(struct.unpack('<L',data[18:22])[0],0xffffffff)

    def test_zip64_and_ordinary_directory_fields_must_agree(self):
        data=bytearray(archive_bytes(128))
        struct.pack_into('<L',data,len(data)-22+16,1)
        with self.assertRaisesRegex(ValueError,'disagree'):self.validate(data)

    def test_locator_and_end_record_must_be_single_disk_and_bounded(self):
        original=archive_bytes(128);locator=original.rfind(b'PK\x06\x07');record=original.rfind(b'PK\x06\x06')
        for offset,fmt,value in [(locator+4,'<L',1),(locator+8,'<Q',len(original)),(locator+16,'<L',2),(record+4,'<Q',45),(record+16,'<L',1)]:
            data=bytearray(original);struct.pack_into(fmt,data,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ValueError):self.validate(data)

    def test_unknown_duplicate_or_unrequested_extension_fields_reject(self):
        for extra in [b'\x99\x99\0\0',struct.pack('<HHQ',1,8,1),struct.pack('<HH',1,0)*2]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.validate(archive_bytes(extra=extra))
        data=bytearray(archive_bytes(128));central=data.find(b'PK\x01\x02',data.find(b'PK\x01\x02')+1)
        name_size=struct.unpack_from('<H',data,central+28)[0];extra_start=central+46+name_size
        data[extra_start]=2
        with self.assertRaises(ValueError):self.validate(data)

    def test_local_zip64_sizes_and_crc_must_match_central_directory(self):
        original=archive_bytes(force=True)
        for offset,fmt,value in [(14,'<L',0),(30+len('frame_00000.exr')+4,'<Q',101)]:
            data=bytearray(original);struct.pack_into(fmt,data,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ValueError):self.validate(data)

    def test_bounds_comments_and_trailing_data_still_reject(self):
        data=archive_bytes(64)
        for maximum in [1,2]:
            with self.assertRaises(ValueError):archive_zip.bounded_directory(io.BytesIO(data),len(data),max_entries=maximum)
        with self.assertRaises(ValueError):archive_zip.bounded_directory(io.BytesIO(data),len(data),max_directory=1)
        with self.assertRaises(ValueError):self.validate(data+b'extra')


if __name__=='__main__':unittest.main()
