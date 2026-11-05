"""Artist-selected shared model storage, registered through ComfyUI's path API."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import threading

CATEGORIES = ('diffusion_models', 'text_encoders', 'vae', 'loras', 'checkpoints',
              'clip_vision', 'embeddings', 'latent_upscale_models', 'model_patches',
              'detection', 'background_removal', 'upscale_models', 'geometry_estimation')


class ModelFolders:
    def __init__(self, folders, config):
        self.folders, self.config = folders, Path(config)
        self.root = ''
        self.roots = []
        self._added = []
        self._lock = threading.RLock()

    def info(self):
        return {'external': self.root, 'folders': list(self.roots), 'default': str(self.folders.models_dir),
                'download_to': self.root or str(self.folders.models_dir)}

    def _apply(self, roots, target):
        registry = self.folders.folder_names_and_paths
        for category, path, previous in reversed(self._added):
            current = registry.get(category)
            if current and path in current[0]:
                current[0].remove(path)
                if previous is not None:
                    current[0].insert(min(previous, len(current[0])), path)
        self._added = []
        ordered = ([target] + [root for root in roots if root != target]) if target else roots
        for root in reversed(ordered) if target else ordered:
            for category in CATEGORIES:
                child = Path(root) / category
                # Existing Comfy model collections can use the legacy names.
                if category == 'diffusion_models' and not child.exists() and (Path(root) / 'unet').is_dir():
                    child = Path(root) / 'unet'
                if category == 'text_encoders' and not child.exists() and (Path(root) / 'clip').is_dir():
                    child = Path(root) / 'clip'
                path = str(child)
                paths = registry.get(category, ([], set()))[0]
                previous = paths.index(path) if path in paths else None
                self.folders.add_model_folder_path(category, path, is_default=bool(target))
                extensions = registry[category][1]
                if not extensions:
                    extensions.update(getattr(self.folders, 'supported_pt_extensions', {'.safetensors', '.pt', '.pth'}))
                    if category == 'detection':
                        extensions.update({'.onnx', '.torchscript'})
                self._added.append((category, path, previous))
        self.root, self.roots = target, list(roots)
        getattr(self.folders, 'filename_list_cache', {}).clear()

    def _normalise(self, value):
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError('Enter the path to your models folder on the ComfyUI computer.')
        root = ''
        if value.strip():
            chosen = Path(value.strip()).expanduser()
            if not chosen.is_absolute() or not chosen.is_dir():
                raise ValueError('Choose an existing, absolute folder on the ComfyUI computer.')
            if (chosen / 'models').is_dir() and not any((chosen / name).is_dir() for name in CATEGORIES):
                chosen = chosen / 'models'
            root = str(chosen.resolve())
        return root

    def set(self, value):
        root = self._normalise(value)
        return self.configure([root] if root else [], root)

    def configure(self, values, download_to):
        if not isinstance(values, list) or len(values) > 32:
            raise ValueError('Choose up to 32 existing model folders.')
        roots = list(dict.fromkeys(self._normalise(value) for value in values))
        if '' in roots:
            raise ValueError('Enter a full path for each model folder.')
        target = self._normalise(download_to)
        if target and target not in roots:
            raise ValueError('Choose a download destination from your saved model folders.')
        with self._lock:
            self.config.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.config.with_suffix('.tmp')
            temporary.write_text(json.dumps({'folders': roots, 'download_to': target}), encoding='utf-8')
            temporary.replace(self.config)
            self._apply(roots, target)
        return self.info()

    def load(self):
        try:
            data = json.loads(self.config.read_text(encoding='utf-8'))
            if 'folders' in data:
                roots = data['folders']
                if not isinstance(roots, list) or len(roots) > 32:
                    raise ValueError('Invalid saved model folders')
                roots = list(dict.fromkeys(self._normalise(value) for value in roots if isinstance(value, str) and Path(value).is_absolute() and Path(value).is_dir()))
                target = data.get('download_to', '')
                target = str(Path(target).resolve()) if isinstance(target, str) and target else ''
                self._apply(roots, target if target in roots else '')
            else:
                value = data.get('external', '')
                if isinstance(value, str) and value and Path(value).is_absolute() and Path(value).is_dir():
                    root = self._normalise(value)
                    self._apply([root], root)
        except (OSError, ValueError, AttributeError):
            logging.getLogger(__name__).warning('Zura model storage could not be restored; using configured ComfyUI folders.')


def load_saved_folders(folders):
    if not hasattr(folders, '_zura_model_storage'):
        user = Path(folders.get_user_directory())
        store = ModelFolders(folders, user / 'zura' / 'model-folders.json')
        if store.config.exists():
            store.load()
        folders._zura_model_storage = store
    return folders._zura_model_storage


def register(routes, response):
    import folder_paths
    from aiohttp import web
    from .media_source import require_same_origin
    store = load_saved_folders(folder_paths)
    existing = {(route.method, route.path) for route in routes}

    @response
    async def get(request):
        require_same_origin(request)
        return web.json_response(store.info(), headers={'Cache-Control': 'no-store'})

    @response
    async def save(request):
        require_same_origin(request)
        data = await request.json()
        if not isinstance(data, dict) or set(data) not in ({'path'}, {'folders', 'download_to'}):
            raise ValueError('Choose a models folder.')
        try:
            result = await asyncio.to_thread(store.set, data['path']) if 'path' in data else await asyncio.to_thread(store.configure, data['folders'], data['download_to'])
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError) as error:
            return web.json_response({'error': str(error) if isinstance(error, ValueError) else 'Cannot save model storage. Check folder permissions.'}, status=400)

    for base in ('/zura/studio/model-folders', '/genj/studio/model-folders'):
        for method, handler in (('get', get), ('post', save)):
            if (method.upper(), base) not in existing:
                getattr(routes, method)(base)(handler)
