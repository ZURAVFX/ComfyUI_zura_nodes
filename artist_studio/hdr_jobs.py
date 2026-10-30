"""In-memory ownership for a long HDR job; no HTTP route is exposed here.

The browser may reconnect while Comfy remains running. A Comfy restart loses
the coordinator, so callers must report an unknown job rather than resubmit it.
"""
from __future__ import annotations

import asyncio
import re

from .hdr_chunk_store import HDRChunkCancelled

_ID = re.compile(r'^[a-f0-9]{32}$')


class HDRJobs:
    def __init__(self, max_jobs=64):
        self.jobs = {}
        self.tasks = {}
        self.max_jobs = max_jobs

    def start(self, job, details):
        identity = details.get('id') if isinstance(details,dict) else None
        if not isinstance(identity,str) or not _ID.fullmatch(identity) or identity in self.jobs:
            raise ValueError('Invalid or duplicate HDR job.')
        if any(task and not task.done() for task in self.tasks.values()):
            raise ValueError('An HDR conversion is already running.')
        while len(self.jobs) >= self.max_jobs:
            expired = next((key for key,task in self.tasks.items() if task.done()),None)
            if expired is None: raise ValueError('Too many HDR conversions.')
            self.jobs.pop(expired,None);self.tasks.pop(expired,None)
        self.jobs[identity] = (job,dict(details))
        self.tasks[identity] = asyncio.create_task(self._run(job))
        return identity

    async def _run(self, job):
        try:
            await job.run()
        except HDRChunkCancelled:
            pass
        except Exception:
            # HDRChunkRunner retains its own error for status; don't leak an
            # unhandled task exception or silently start a replacement job.
            pass

    def status(self, identity):
        if not isinstance(identity,str) or not _ID.fullmatch(identity) or identity not in self.jobs:
            raise ValueError('HDR conversion is no longer available. It was not restarted.')
        job,details = self.jobs[identity]
        return {**details,**job.snapshot()}

    async def cancel(self, identity):
        self.status(identity)
        job,_ = self.jobs[identity]
        return await job.cancel()
