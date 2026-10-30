"""Private bounded disk staging for experimental long HDR conversions.

This module is not an HTTP endpoint and does not submit Comfy jobs. Its root
and immutable job ID must be supplied by a trusted Studio job coordinator.
No output is published until every chunk and the final mux have succeeded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

import numpy as np
import torch

from .hdr_chunks import stitch_acescct_batches

_ID = re.compile(r'^[a-f0-9]{32}$')


class HDRChunkCancelled(RuntimeError):
    pass


def _sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024*1024), b''):
            digest.update(data)
    return digest.hexdigest()


class HDRChunkStore:
    """Stage float32 ACEScct frames atomically, then read them lazily."""
    def __init__(self, root, identity, plan, width, height, *, create=False):
        if not isinstance(identity,str) or not _ID.fullmatch(identity):
            raise ValueError('Invalid HDR staging ID.')
        if not plan or any(type(v) is not int or v <= 0 for v in (width,height)):
            raise ValueError('Invalid HDR staging dimensions or plan.')
        self.root=Path(root).resolve()
        self.directory=self.root/identity
        self.identity=identity
        self.plan=list(plan)
        self.width,self.height=width,height
        self.cancelled=threading.Event()
        self._owned=create
        if create:
            self.root.mkdir(parents=True,exist_ok=True)
            self.directory.mkdir(exist_ok=False)
        elif self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError('HDR staging directory is missing or invalid.')

    def cancel(self):
        self.cancelled.set()

    def cleanup(self):
        """Remove only expected files from this instance's freshly created job."""
        if not self._owned:raise ValueError('Only the creating job can clean HDR staging.')
        if self.directory.is_symlink() or not self.directory.is_dir() or self.directory.resolve().parent!=self.root:
            raise ValueError('HDR staging directory changed or is invalid.')
        for index in range(len(self.plan)):
            for suffix in ('npy','json','partial'):
                path=self._path(index,suffix)
                if not path.is_symlink() and path.is_file():path.unlink()
        # Never recursively remove unknown files, directories or symlinks.
        if not any(self.directory.iterdir()):self.directory.rmdir()

    def _check_cancelled(self):
        if self.cancelled.is_set(): raise HDRChunkCancelled('HDR conversion cancelled.')

    def _path(self, index, suffix):
        if type(index) is not int or not 0 <= index < len(self.plan):
            raise ValueError('Invalid HDR chunk index.')
        if self.directory.is_symlink() or not self.directory.is_dir() or self.directory.resolve().parent != self.root:
            raise ValueError('HDR staging directory changed or is invalid.')
        return self.directory/f'{index:06d}.{suffix}'

    def write(self, index, frames):
        self._check_cancelled()
        target=self._path(index,'npy'); metadata=self._path(index,'json')
        if not isinstance(frames,torch.Tensor) or tuple(frames.shape)!=(self.plan[index].count,self.height,self.width,3):
            raise ValueError('Rendered HDR chunk dimensions or frame count differ from its plan.')
        if not torch.isfinite(frames).all(): raise ValueError('Rendered HDR frames contain non-finite values.')
        temporary=self._path(index,'partial')
        if target.exists() or metadata.exists() or temporary.exists():
            raise ValueError('HDR chunk is already staged or incomplete; it will not be overwritten.')
        try:
            with temporary.open('xb') as stream:
                np.save(stream,frames.detach().to(device='cpu',dtype=torch.float32).numpy(),allow_pickle=False)
                stream.flush(); os.fsync(stream.fileno())
            self._check_cancelled()
            digest=_sha256(temporary)
            # Exclusive publication prevents overwriting an earlier run.
            from .model_downloads import _publish_verified
            _publish_verified(temporary,target)
            record={'sha256':digest,'start':self.plan[index].start,'count':self.plan[index].count,
                    'width':self.width,'height':self.height}
            with metadata.open('x',encoding='utf8') as out:
                json.dump(record,out,separators=(',',':'))
                out.flush(); os.fsync(out.fileno())
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, index):
        self._check_cancelled()
        path=self._path(index,'npy'); metadata=self._path(index,'json')
        if path.is_symlink() or metadata.is_symlink() or not path.is_file() or not metadata.is_file():
            raise ValueError('A staged HDR chunk is missing.')
        record=json.loads(metadata.read_text(encoding='utf8'))
        expected={'start':self.plan[index].start,'count':self.plan[index].count,
                  'width':self.width,'height':self.height}
        if any(record.get(key)!=value for key,value in expected.items()) or record.get('sha256')!=_sha256(path):
            raise ValueError('A staged HDR chunk changed or does not match its plan.')
        array=np.load(path,allow_pickle=False,mmap_mode='c')
        if array.dtype!=np.float32 or array.shape!=(self.plan[index].count,self.height,self.width,3):
            raise ValueError('A staged HDR chunk has invalid dimensions or precision.')
        # Copy one bounded chunk and close the mapping promptly. On Windows a
        # live mapping otherwise locks staging files after cancellation.
        return torch.from_numpy(np.array(array,copy=True))

    def stitched(self, *, strategy='blend'):
        def batches():
            for index in range(len(self.plan)):
                self._check_cancelled()
                yield self.read(index)
        for output in stitch_acescct_batches(self.plan,batches(),strategy=strategy):
            self._check_cancelled()
            yield output
