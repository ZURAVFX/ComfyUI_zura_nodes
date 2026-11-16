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


def default_models_dir(folders, ignore=()):
    fallback = str(getattr(folders, 'models_dir', '') or '')
    registry = getattr(folders, 'folder_names_and_paths', None)
    ignored = {(category, str(Path(path))) for category, path in ignore}
    for category in ('checkpoints', 'vae', 'loras', 'diffusion_models', 'text_encoders'):
        paths = list(registry.get(category, ([],))[0]) if isinstance(registry, dict) else []
        if not paths and hasattr(folders, 'get_folder_paths'):
            try:
                paths = list(folders.get_folder_paths(category))
            except KeyError:
                paths = []
        for path in paths:
            if (category, str(Path(path))) in ignored:
                continue
            candidate = Path(path)
            if candidate.name.lower() in (category, 'unet', 'clip'):
                parent = candidate.parent
                if fallback and parent == Path(fallback):
                    return fallback
                return str(parent)
    return fallback


def preferred_category_roots(folders, category, roots=None):
    if roots is None:
        try:
            roots = list(folders.get_folder_paths(category))
        except KeyError:
            roots = []
    else:
        roots = list(roots)
    base = default_models_dir(folders)
    if base and category in CATEGORIES:
        canonical = str(Path(base) / category)
        # The Downloads root is already selected by ComfyUI's is_default path
        # ordering. A missing category directory is created by the downloader.
        if Path(base).is_dir() or canonical in roots:
            roots = [canonical] + [root for root in roots if str(Path(root)) != canonical]
            if hasattr(folders, 'add_model_folder_path'):
                folders.add_model_folder_path(category, canonical, is_default=True)
    if not roots and category == 'embeddings' and base:
        roots = [str(Path(base) / 'embeddings')]
    if not roots:
        return roots
    if base:
        base_path = Path(base)
        if Path(roots[0]).parent != base_path:
            for index, candidate in enumerate(roots):
                if Path(candidate).parent == base_path:
                    roots.insert(0, roots.pop(index))
                    break
            else:
                target_dir = base_path / category
                if base_path.is_dir() and target_dir.is_dir():
                    if hasattr(folders, 'add_model_folder_path'):
                        folders.add_model_folder_path(category, str(target_dir), is_default=True)
                    roots.insert(0, str(target_dir))
    if category in ('diffusion_models', 'text_encoders'):
        first = Path(roots[0])
        if first.name.lower() != category:
            canonical = first.parent / category
            for index, candidate in enumerate(roots):
                if Path(candidate) == canonical:
                    roots.insert(0, roots.pop(index))
                    break
    return roots


class ModelFolders:
    def __init__(self, folders, config):
        self.folders, self.config = folders, Path(config)
        self.root = ''
        self.roots = []
        self._added = []
        self._lock = threading.RLock()

    def info(self):
        default = default_models_dir(self.folders, [(category, path) for category, path, previous in self._added if previous is None])
        return {'external': self.root, 'folders': list(self.roots), 'default': default,
                'download_to': self.root or default}

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
