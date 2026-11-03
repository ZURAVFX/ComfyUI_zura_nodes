"""Stream a browser-selected model into an allowlisted, verified destination."""
import asyncio
import hashlib
from pathlib import Path
import shutil
import threading
import uuid


def register(routes, prefix, manager, lookup, check_publish, publish, response=lambda fn: fn):
    from aiohttp import web
    from .media_source import require_same_origin

    @routes.post(prefix + '/import-file')
    @response
    async def import_file(request):
        require_same_origin(request)
        identity = None
        temporary = None
        try:
            if set(request.query) != {'model_id', 'filename'}:
                raise ValueError('Choose a model file from the package list.')
            model_id, filename = request.query['model_id'], request.query['filename']
            # lookup accepts only exact catalogue entries, never a user path/URL.
            item = await asyncio.to_thread(lookup, model_id, filename)
            if item['installed']:
                raise ValueError('This file is already installed. Refresh models to continue.')
            if item['incomplete']:
                raise ValueError('An existing file needs attention. It will not be overwritten.')
            if request.content_length != item['size_bytes']:
                raise ValueError('Choose the completed download with the exact size shown in the model list.')
            destination = Path(item['destination'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise ValueError('A model already exists at this destination. Refresh models; it will not be overwritten.')
            if shutil.disk_usage(destination.parent).free < item['size_bytes'] + 64 * 1024 * 1024:
                raise ValueError('There is not enough space in the selected models folder.')
            with manager._lock:
                if manager._active is not None:
                    raise ValueError('A model install is already running. Wait for it or cancel it first.')
                identity = uuid.uuid4().hex
                manager._jobs[identity] = dict(id=identity, model_id=model_id, model_ids=[model_id], phase='downloading',
                    current_file=filename, done_bytes=0, total_bytes=item['size_bytes'], error='', auth_required=False, cancel=threading.Event())
                manager._active = identity
            await asyncio.to_thread(check_publish, destination.parent, identity)
            temporary = destination.parent / ('.zura-browser-' + identity + '.part')
            digest, count = hashlib.sha256(), 0
            with temporary.open('xb') as output:
                async for block in request.content.iter_chunked(1024 * 1024):
                    if manager._jobs[identity]['cancel'].is_set():
                        raise ValueError('Import cancelled. Your browser download is kept.')
                    count += len(block)
                    if count > item['size_bytes']:
                        raise ValueError('This download is larger than the verified model.')
                    await asyncio.to_thread(output.write, block)
                    digest.update(block)
                    with manager._lock:
                        manager._jobs[identity]['done_bytes'] = count
            with manager._lock:
                manager._jobs[identity]['phase'] = 'verifying'
            if count != item['size_bytes'] or digest.hexdigest() != item['sha256']:
                raise ValueError('The file does not match the verified model. Download the linked file again.')
            with manager._lock:
                if manager._jobs[identity]['cancel'].is_set():
                    raise ValueError('Import cancelled. Your browser download is kept.')
                publish(temporary, destination)
                manager._jobs[identity].update(phase='done', current_file='')
            await asyncio.to_thread(getattr(manager, 'on_installed', lambda: None))
            return web.json_response({'id': identity}, headers={'Cache-Control': 'no-store'})
        except asyncio.CancelledError:
            if identity:
                with manager._lock:
                    manager._jobs[identity].update(phase='failed', error='The import connection closed. Your original download is kept; select it again to retry.')
            raise
        except (ValueError, OSError, ConnectionError) as error:
            message = str(error) if isinstance(error, ValueError) else 'Could not finish importing the model. Check the connection, disk space and folder permissions.'
            if identity:
                with manager._lock:
                    cancelled = manager._jobs[identity]['cancel'].is_set()
                    manager._jobs[identity].update(phase='cancelled' if cancelled else 'failed', error=message)
            return web.json_response({'error': message}, status=400, headers={'Cache-Control': 'no-store'})
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
            if identity:
                with manager._lock:
                    if manager._active == identity:
                        manager._active = None
