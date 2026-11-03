import hashlib, importlib, json, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest.mock import patch
from test_model_downloads import tensor_file
ROOT=Path(__file__).resolve().parents[2]
package=types.ModuleType('_watermark_import_test');package.__path__=[str(ROOT/'paintout')];sys.modules[package.__name__]=package
d=importlib.import_module(package.__name__+'.model_downloads')
b=importlib.import_module(package.__name__+'.model_browser_import')
class BrowserImport(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.target=self.root/'external'/'vae';self.target.mkdir(parents=True);self.data=tensor_file();self.source=self.root/'browser (1).safetensors';self.source.write_bytes(self.data)
        self.item=dict(folder='vae',filename='fixture.safetensors',repo='Example/fixture',revision='1'*40,remote_path='fixture.safetensors',size_bytes=len(self.data),sha256=hashlib.sha256(self.data).hexdigest(),gated=True)
        p=patch.object(d,'CATALOG',{'fixture':dict(name='Fixture',files=[self.item],license_url='https://huggingface.co/Example/fixture')});p.start();self.addCleanup(p.stop)
        # b imports the catalogue object, while inspect reads the current catalogue.
        p=patch.object(b,'CATALOG',d.CATALOG);p.start();self.addCleanup(p.stop)
        self.installed=[];self.manager=d.DownloadManager({'vae':[str(self.target),str(self.root/'other')]},on_installed=lambda:self.installed.append(True))
    def wait(self,identity):
        for _ in range(500):
            job=self.manager.status(identity)
            if job['phase'] in ('done','failed','cancelled'):return job
            time.sleep(.01)
        self.fail('Import did not finish')
    def test_verified_browser_download_installs_to_selected_external_folder(self):
        job=self.wait(b.start_import(self.manager,'fixture',self.item['filename'],self.source));self.assertEqual(job['phase'],'done');self.assertEqual((self.target/self.item['filename']).read_bytes(),self.data);self.assertTrue(self.source.exists());self.assertTrue(self.installed)
    def test_wrong_hash_never_publishes(self):
        self.source.write_bytes(self.data[:-1]+bytes([self.data[-1]^1]));job=self.wait(b.start_import(self.manager,'fixture',self.item['filename'],self.source));self.assertEqual(job['phase'],'failed');self.assertFalse((self.target/self.item['filename']).exists());self.assertFalse(list(self.target.glob('*.part')))
    def test_unknown_file_wrong_size_and_existing_file_are_rejected(self):
        with self.assertRaises(ValueError):b.start_import(self.manager,'fixture','unlisted.safetensors',self.source)
        self.source.write_bytes(b'short')
        with self.assertRaises(ValueError):b.start_import(self.manager,'fixture',self.item['filename'],self.source)
        self.source.write_bytes(self.data);(self.target/self.item['filename']).write_bytes(self.data)
        with self.assertRaisesRegex(ValueError,'already installed'):b.start_import(self.manager,'fixture',self.item['filename'],self.source)
if __name__=='__main__':unittest.main()
