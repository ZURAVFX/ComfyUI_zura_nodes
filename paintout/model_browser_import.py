"""Install browser downloads using the same catalogue, storage and job controls."""
import hashlib, shutil, threading, uuid
from pathlib import Path
from .model_downloads import CATALOG, inspect, _check_publish_supported, _publish_verified, safetensors_header, DownloadError, Cancelled

def start_import(manager, model_id, filename, source):
    if model_id not in CATALOG: raise ValueError('Choose a model package from the list.')
    items = [item for item in inspect(model_id, manager.locations)['files'] if item['filename']==filename]
    if len(items)!=1: raise ValueError('Choose a file from the selected package.')
    item=items[0]
    if item['installed']: raise ValueError('This model is already installed. Check the model list.')
    if item['incomplete']: raise ValueError('An existing file needs attention. It will not be overwritten.')
    source=Path(source).resolve(strict=True)
    if not source.is_file() or source.stat().st_size!=item['size_bytes']:
        raise ValueError('The file has the wrong size or has not finished downloading. Choose the completed download.')
    destination=Path(item['destination']);root=destination.parent.resolve()
    if root!=Path(item['destination_root']) or destination.resolve().parent!=root:
        raise ValueError('The model destination changed. Check model storage and try again.')
    root.mkdir(parents=True,exist_ok=True);_check_publish_supported(root)
    if shutil.disk_usage(root).free<item['size_bytes']+64*1024*1024:
        raise ValueError('There is not enough free space in the selected models folder.')
    with manager._lock:
        if manager._active is not None: raise ValueError('A model install is already running. Wait for it or cancel it first.')
        identity=uuid.uuid4().hex
        manager._jobs[identity]=dict(id=identity,model_id=model_id,model_ids=[model_id],phase='queued',done_bytes=0,total_bytes=item['size_bytes'],current_file=filename,error='',auth_required=False,cancel=threading.Event())
        manager._active=identity
    threading.Thread(target=_run,args=(manager,identity,item,source),daemon=True).start()
    return identity

def _run(manager,identity,item,source):
    destination=Path(item['destination']);temporary=destination.parent/('.zura-import-'+identity+'.part')
    try:
        manager._update(identity,phase='verifying')
        digest=hashlib.sha256();count=0
        with source.open('rb') as incoming,temporary.open('xb') as outgoing:
            while block:=incoming.read(4*1024*1024):
                manager._cancelled(identity);count+=len(block)
                if count>item['size_bytes']: raise DownloadError('The file changed while installing. Choose a completed download.')
                digest.update(block);outgoing.write(block);manager._update(identity,done_bytes=count)
        if count!=item['size_bytes'] or digest.hexdigest()!=item['sha256']:
            raise DownloadError('The file does not match the verified model. Download the linked file again.')
        safetensors_header(temporary,item['size_bytes'])
        with manager._lock:
            manager._cancelled(identity)
            try: _publish_verified(temporary,destination)
            except FileExistsError: raise DownloadError('This model was installed elsewhere while copying. Existing files were kept.') from None
        manager.on_installed();manager._update(identity,phase='done',current_file='')
    except Cancelled: manager._update(identity,phase='cancelled',error='Import cancelled. Your browser download is kept.')
    except Exception as error: manager._update(identity,phase='failed',error=str(error) if isinstance(error,DownloadError) else 'Could not install the downloaded model. Check disk space and folder permissions.')
    finally:
        temporary.unlink(missing_ok=True)
        with manager._lock:
            if manager._active==identity: manager._active=None
