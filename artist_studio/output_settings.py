"""User-facing delivery copies. Comfy's original assets keep their stable URLs."""
import asyncio
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import uuid

from aiohttp import web


def assets_in(value):
    if isinstance(value, dict):
        if value.get('type') == 'output' and isinstance(value.get('filename'), str):
            yield value
        for item in value.values():
            yield from assets_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from assets_in(item)


class OutputSettings:
    def __init__(self, output_directory, settings_directory):
        self.source = Path(output_directory).resolve()
        self.directory = Path(settings_directory)
        self.default = self.source / 'ZURA STUDIO'
        self.lock = threading.RLock()
        self.error = None
        self.pending = set()
        self.tasks = set()

    def schedule_export(self, value):
        """Delivery copies must not delay previews or the next generation stage."""
        assets, keys = [], []
        for asset in assets_in(value):
            key = json.dumps([asset.get('subfolder'), asset.get('filename')])
            if key not in self.pending:
                self.pending.add(key)
                keys.append(key)
                assets.append(asset)
        if not assets:
            return

        async def deliver():
            try:
                await self.export_safely(assets)
            finally:
                self.pending.difference_update(keys)

        task = asyncio.create_task(deliver())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def describe(self):
        with self.lock:
            try:
                data = json.loads((self.directory / 'output.json').read_text(encoding='utf-8'))
            except FileNotFoundError:
                data = {}
            folder = data.get('folder') or str(self.default)
            return {'folder': folder, 'default_folder': str(self.default),
                    'is_default': os.path.normcase(folder) == os.path.normcase(str(self.default)),
                    'error': self.error}

    def save(self, value):
        if not isinstance(value, str):
            raise ValueError('Enter a full folder path, or choose Use default.')
        folder = Path(value.strip()).expanduser() if value.strip() else self.default
        if not folder.is_absolute():
            raise ValueError('Enter a full folder path, such as D:\\Renders\\ZURA STUDIO.')
        folder = folder.resolve()
        # Keep delivery copies out of the internal asset tree to avoid collisions.
        if folder == self.source or (folder.is_relative_to(self.source) and not folder.is_relative_to(self.default)):
            raise ValueError('Choose ZURA STUDIO or a folder outside ComfyUI’s output folder.')
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as probe:
            probe.write(b'Zura Studio')
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / (uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_text(json.dumps({'folder': str(folder)}, indent=2), encoding='utf-8')
                os.replace(temporary, self.directory / 'output.json')
            finally:
                temporary.unlink(missing_ok=True)
            self.error = None
        return self.describe()

    def source_file(self, asset):
        name = asset.get('filename')
        if asset.get('type') != 'output' or not isinstance(name, str) or not name or '/' in name or '\\' in name:
            return None
        subfolder = asset.get('subfolder', '')
        if not isinstance(subfolder, str):
            return None
        subfolder = subfolder.replace('\\', '/')
        allowed = ('genj/final', 'genj/hdr', 'genj/hdr_outpaint', 'genj/outpaint',
                   'zura_images', 'paintout', 'zura_paintout', 'genj/frames', 'genj/references',
                   'genj/reference_video', 'genj/studio_images', 'zura/ltx25',
                   'zura/first_last', 'zura/reference')
        if subfolder == 'genj/panorama':
            if not name.startswith('take'):
                return None
        elif not any(subfolder == root or subfolder.startswith(root + '/') for root in allowed):
            return None
        if any(part in name.lower() for part in ('_preview', '_unverified', '.partial')):
            return None
        if subfolder.startswith('zura/ltx25/') and not name.startswith('result'):
            return None
        file = (self.source / subfolder / name).resolve()
        if not file.is_relative_to(self.source) or not file.is_file():
            return None
        return file

    def export(self, assets):
        saved = []
        with self.lock:
            folder = Path(self.describe()['folder'])
            self.directory.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.directory / 'deliveries.sqlite3')) as db:
                db.execute('CREATE TABLE IF NOT EXISTS deliveries (identity TEXT PRIMARY KEY, destination TEXT)')
                for asset in assets:
                    source = self.source_file(asset)
                    if source is None:
                        continue
                    suffix = source.suffix.lower()
                    category = ('Videos' if suffix in ('.mp4', '.mov', '.webm', '.mkv') else
                                'Images' if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff') else
                                'Sequences' if suffix == '.zip' else None)
                    if category is None:
                        continue
                    info = source.stat()
                    identity = json.dumps([str(source), info.st_size, info.st_mtime_ns, str(folder)])
                    record = db.execute('SELECT destination FROM deliveries WHERE identity=?', (identity,)).fetchone()
                    if record and Path(record[0]).is_file() and Path(record[0]).stat().st_size == info.st_size:
                        saved.append(record[0])
                        continue
                    target = folder / category / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Never overwrite an artist's existing file, including from another machine.
                    while True:
                        try:
                            handle = target.open('xb')
                            break
                        except FileExistsError:
                            target = target.with_name(source.stem + '_' + uuid.uuid4().hex[:8] + source.suffix)
                    try:
                        with handle, source.open('rb') as reader:
                            shutil.copyfileobj(reader, handle, length=1024 * 1024)
                        if source.stat().st_size != info.st_size or target.stat().st_size != info.st_size:
                            raise OSError('The output changed while saving. Try Save again when the render finishes.')
                    except Exception:
                        target.unlink(missing_ok=True)
                        raise
                    db.execute('INSERT OR REPLACE INTO deliveries VALUES (?, ?)', (identity, str(target)))
                    saved.append(str(target))
                db.commit()
            self.error = None
        return saved

    async def export_safely(self, value):
        assets = list(assets_in(value))
        if not assets:
            return []
        try:
            return await asyncio.to_thread(self.export, assets)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.error = 'Could not save the delivery copy: ' + str(error)
            logging.warning('Zura Studio output folder: %s', error)
            return []  # A failed delivery copy must never invalidate a finished render.


def register(server, routes, response):
    import folder_paths
    service = OutputSettings(folder_paths.get_output_directory(),
                             Path(folder_paths.get_user_directory()) / 'default' / 'zura_studio')
    # Ignore old history. New successful native image/video graphs also get delivery copies.
    seen = set(server.prompt_queue.get_history(map_function=lambda item: None))
    task = None

    async def watch():
        while True:
            history = server.prompt_queue.get_history(max_items=100, map_function=lambda item: {
                'outputs': item.get('outputs', {}), 'status': item.get('status', {})})
            for key, item in history.items():
                if key not in seen:
                    seen.add(key)
                    if item['status'].get('status_str') == 'success':
                        await service.export_safely(item['outputs'])
            await asyncio.sleep(3)

    def start():
        nonlocal task
        if task is None or task.done():
            task = asyncio.create_task(watch())

    @routes.get('/zura/studio/output-settings')
    @response
    async def get_settings(request):
        start()
        return web.json_response(service.describe())

    @routes.post('/zura/studio/output-settings')
    @response
    async def save_settings(request):
        data = await request.json()
        return web.json_response(await asyncio.to_thread(service.save, data.get('folder')))

    @routes.post('/zura/studio/save-output')
    @response
    async def save_output(request):
        data = await request.json()
        assets = data.get('assets')
        if not isinstance(assets, list) or not 1 <= len(assets) <= 32 or not all(isinstance(a, dict) for a in assets):
            raise ValueError('Choose a finished image or video to save.')
        saved = await asyncio.to_thread(service.export, assets)
        if not saved:
            raise ValueError('This finished file is no longer available in ComfyUI.')
        return web.json_response({'saved': saved, **service.describe()})

    service.start = start
    return service
