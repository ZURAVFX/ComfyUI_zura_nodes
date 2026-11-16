"""Workflow installation and persistent external storage, without real downloads."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

downloads = module('install_downloads', 'artist_studio/model_downloads.py')
storage = module('install_storage', 'model_folders.py')


class Folders:
    models_dir = '/comfy/models'
    supported_pt_extensions = {'.safetensors', '.pt'}
    def __init__(self):
        self.folder_names_and_paths = {'vae': (['/comfy/models/vae'], {'.safetensors'})}
        self.filename_list_cache = {'vae': ['stale']}
    def add_model_folder_path(self, category, path, is_default=False):
        roots = self.folder_names_and_paths.setdefault(category, ([], set()))[0]
        if path in roots: roots.remove(path)
        roots.insert(0 if is_default else len(roots), path)


class WorkflowInstallTests(unittest.TestCase):
    def test_one_job_deduplicates_files_and_only_installs_workflow_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = lambda name: {'folder': 'vae', 'filename': name, 'size_bytes': 32, 'sha256': hashlib.sha256(b'x'*32).hexdigest(), 'repo': 'test/models', 'revision': 'a'*40, 'remote_path': name}
            a, b, extra = item('shared.safetensors'), item('needed.safetensors'), item('unused.safetensors')
            catalogue = {name: {'name': name, 'gated': False, 'license_url': '', 'files': files} for name, files in [('first', [a, extra]), ('second', [a, b])]}
            with patch.dict(downloads.CATALOG, catalogue, clear=True), patch.object(downloads.threading, 'Thread') as thread:
                manager = downloads.DownloadManager({'vae': [tmp]})
                job = manager.start(['first', 'second'], ['vae/shared.safetensors', 'vae/needed.safetensors'])
                self.assertEqual(manager.status(job)['total_bytes'], 64)
                recipe = thread.call_args.kwargs['args'][1]
                self.assertEqual([f['filename'] for f in recipe['files']], ['shared.safetensors', 'needed.safetensors'])
                self.assertEqual(len(manager.status(job)['model_ids']), 2)
                thread.return_value.start.assert_called_once()
                with self.assertRaisesRegex(ValueError, 'already running'):
                    manager.start('first')
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_arbitrary_file_selection_and_non_catalogue_packages_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = {'folder': 'vae', 'filename': 'ok.safetensors', 'size_bytes': 32}
            with patch.dict(downloads.CATALOG, {'test': {'name':'Test','gated':False,'license_url':'','files':[item]}}, clear=True), patch.object(downloads.threading, 'Thread') as thread:
                manager = downloads.DownloadManager({'vae': [tmp]})
                for ids, keys in [(['test'], ['vae/../../outside']), (['test'], []), (['url'], None), ([], None)]:
                    with self.assertRaises(ValueError): manager.start(ids, keys)
                thread.assert_not_called()

    def test_registered_external_subfolder_is_reused_without_redownloading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root/'collection').mkdir();(root/'collection/model.safetensors').write_bytes(b'x'*32)
            recipe = {'name':'Test','gated':False,'license_url':'','files':[{'folder':'vae','filename':'model.safetensors','size_bytes':32}]}
            with patch.dict(downloads.CATALOG, {'test':recipe}, clear=True):
                state = downloads.inspect('test', {'vae':[tmp]}, {'vae':['collection/model.safetensors']})
            self.assertEqual(state['remaining_bytes'], 0)
            self.assertTrue(state['files'][0]['installed'])


class ExternalStorageTests(unittest.TestCase):
    def test_multiple_folders_are_searched_and_chosen_destination_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'first';b=root/'second';a.mkdir();b.mkdir()
            folders=Folders();config=root/'storage.json';setting=storage.ModelFolders(folders,config)
            setting.configure([str(a),str(b),str(a)],str(b))
            self.assertEqual(setting.info()['folders'],[str(a),str(b)])
            self.assertEqual(folders.folder_names_and_paths['vae'][0],[str(b/'vae'),str(a/'vae'),'/comfy/models/vae'])
            restored=storage.ModelFolders(Folders(),config);restored.load()
            self.assertEqual(restored.info()['folders'],[str(a),str(b)])
            self.assertEqual(restored.info()['download_to'],str(b))
            setting.configure([str(a),str(b)],'')
            self.assertEqual(folders.folder_names_and_paths['vae'][0],['/comfy/models/vae',str(a/'vae'),str(b/'vae')])
            setting.configure([str(a)],str(a))
            self.assertNotIn(str(b/'vae'),folders.folder_names_and_paths['vae'][0])
            setting.configure([],'')
            self.assertEqual(folders.folder_names_and_paths['vae'][0],['/comfy/models/vae'])

    def test_invalid_destination_is_rejected_and_legacy_single_folder_is_restored(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'first';b=root/'second';a.mkdir();b.mkdir()
            folders=Folders();config=root/'storage.json';setting=storage.ModelFolders(folders,config)
            with self.assertRaises(ValueError):setting.configure([str(a)],str(b))
            self.assertFalse(config.exists())
            config.write_text(json.dumps({'external':str(a)}),encoding='utf-8')
            setting.load()
            self.assertEqual(setting.info()['folders'],[str(a)])
            self.assertEqual(setting.info()['download_to'],str(a))

    def test_external_model_root_is_preferred_persisted_and_reversible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);external=root/'shared';external.mkdir();config=root/'user/storage.json';folders=Folders()
            setting=storage.ModelFolders(folders,config)
            setting.set(str(external))
            self.assertEqual(folders.folder_names_and_paths['vae'][0], [str(external/'vae'), '/comfy/models/vae'])
            self.assertEqual(folders.filename_list_cache,{})
            self.assertFalse((external/'vae').exists(), 'Selecting storage does not create model folders or download files')
            other=Folders();restored=storage.ModelFolders(other,config);restored.load()
            self.assertEqual(restored.root,str(external.resolve()))
            restored.set('')
            self.assertEqual(other.folder_names_and_paths['vae'][0], ['/comfy/models/vae'])
            self.assertEqual(restored.info()['download_to'], '/comfy/models')

    def test_comfy_root_and_legacy_model_folder_names_are_understood(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'models/unet').mkdir(parents=True);(root/'models/clip').mkdir()
            folders=Folders();setting=storage.ModelFolders(folders,root/'settings.json');setting.set(str(root))
            self.assertEqual(setting.root,str((root/'models').resolve()))
            self.assertEqual(folders.folder_names_and_paths['diffusion_models'][0][0],str(root/'models/unet'))
            self.assertEqual(folders.folder_names_and_paths['text_encoders'][0][0],str(root/'models/clip'))

    def test_invalid_folder_does_not_modify_config_or_search_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.json';folders=Folders();setting=storage.ModelFolders(folders,config)
            for path in ['relative/path',str(root/'missing'),None,42]:
                with self.assertRaises(ValueError):setting.set(path)
            self.assertFalse(config.exists());self.assertEqual(folders.folder_names_and_paths['vae'][0],['/comfy/models/vae'])

    def test_comfy_desktop_default_downloads_folder_and_canonical_subfolders_are_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop_models = root / 'desktop_downloads' / 'models'
            instance_models = root / 'instance' / 'models'
            for sub in ('checkpoints', 'vae', 'diffusion_models', 'unet', 'text_encoders', 'clip', 'latent_upscale_models'):
                (desktop_models / sub).mkdir(parents=True, exist_ok=True)
                (instance_models / sub).mkdir(parents=True, exist_ok=True)
            folders = Folders()
            folders.models_dir = str(instance_models)
            folders.folder_names_and_paths = {
                'checkpoints': ([str(desktop_models / 'checkpoints'), str(instance_models / 'checkpoints')], {'.safetensors'}),
                'vae': ([str(desktop_models / 'vae'), str(instance_models / 'vae')], {'.safetensors'}),
                'diffusion_models': ([str(desktop_models / 'unet'), str(desktop_models / 'diffusion_models'), str(instance_models / 'diffusion_models')], {'.safetensors'}),
                'text_encoders': ([str(desktop_models / 'clip'), str(desktop_models / 'text_encoders'), str(instance_models / 'text_encoders')], {'.safetensors'}),
                'latent_upscale_models': ([str(instance_models / 'latent_upscale_models')], {'.safetensors'}),
            }
            folders.get_folder_paths = lambda name: list(folders.folder_names_and_paths[name][0])
            setting = storage.ModelFolders(folders, root / 'storage.json')
            self.assertEqual(setting.info()['default'], str(desktop_models))
            self.assertEqual(setting.info()['download_to'], str(desktop_models))
            locations = downloads.folder_locations(folders, {'diffusion_models', 'text_encoders', 'latent_upscale_models', 'vae'})
            self.assertEqual(locations['diffusion_models'][0], str(desktop_models / 'diffusion_models'))
            self.assertEqual(locations['text_encoders'][0], str(desktop_models / 'text_encoders'))
            # Categories absent from the instance registry still download under
            # Desktop's chosen root, without creating directories during lookup.
            for category in storage.CATEGORIES:
                preferred = storage.preferred_category_roots(folders, category)
                self.assertEqual(preferred[0], str(desktop_models / category))
            self.assertFalse((desktop_models / 'geometry_estimation').exists())
            self.assertEqual(locations['latent_upscale_models'][0], str(desktop_models / 'latent_upscale_models'))


if __name__ == '__main__': unittest.main()
