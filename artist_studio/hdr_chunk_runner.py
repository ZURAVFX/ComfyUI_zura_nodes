"""Cancellable sequential job coordination for a long LTX HDR conversion.

Adapters must submit exactly one native Comfy prompt at a time, validate that
its returned frames correspond to the submitted range, and export staged
frames without publishing partial results. This coordinator is deliberately
not registered as a Studio route until those adapters are verified together.
"""
from __future__ import annotations

import asyncio
import logging

from .hdr_chunk_store import HDRChunkCancelled


class HDRChunkRunner:
    def __init__(self, store, render, export, cancel_prompt):
        self.store=store
        self.render=render
        self.export=export
        self.cancel_prompt=cancel_prompt
        self.state='ready'
        self.current_prompt=None
        self.completed=0
        self.error=None
        self.result=None
        self._running=False
        self.cancelling=False

    def snapshot(self):
        """Describe the current stage without inventing an overall ETA."""
        state='cancelling' if self.cancelling and self.state not in ('complete','failed','cancelled') else self.state
        return {'state':state,'completed':self.completed,'total':len(self.store.plan),
                'active_prompt_id':self.current_prompt,'error':self.error,'result':self.result}

    def _check(self):
        if self.store.cancelled.is_set(): raise HDRChunkCancelled('HDR conversion cancelled.')

    async def cancel(self):
        if self.state in ('complete','failed','cancelled'):return False
        self.cancelling=True
        self.store.cancel()
        prompt=self.current_prompt
        if prompt is not None:
            await self.cancel_prompt(prompt)
        return True

    async def run(self):
        """Render, stage and export once; never automatically resubmit a job."""
        if self._running or self.state!='ready':
            raise ValueError('This HDR conversion has already started.')
        self._running=True
        try:
            for index,part in enumerate(self.store.plan):
                self._check()
                self.state='rendering'
                # render returns (prompt ID, coroutine). Record the ID before
                # awaiting so cancellation can target this job specifically.
                prompt,completion=await self.render(index,part)
                self.current_prompt=prompt
                if self.store.cancelled.is_set():
                    # Cancellation may have arrived while submission was in
                    # flight, before there was a prompt ID to interrupt.
                    await self.cancel_prompt(prompt)
                    if asyncio.isfuture(completion): completion.cancel()
                    elif hasattr(completion,'close'): completion.close()
                    self._check()
                try: frames=await completion
                finally:self.current_prompt=None
                self._check()
                self.state='staging'
                # Native Comfy adapters can persist the chunk in their output
                # node and return None to avoid copying a large GPU result.
                if frames is None:
                    staged=await asyncio.to_thread(self.store.read,index)
                    del staged
                else:
                    await asyncio.to_thread(self.store.write,index,frames)
                del frames
                self.completed=index+1
            self._check()
            self.state='exporting'
            self.result=await self.export(self.store)
            self._check()
            self.state='complete'
            return self.result
        except HDRChunkCancelled:
            self.state='cancelled'
            raise
        except Exception as error:
            self.state='failed';self.error=str(error)
            raise
        finally:
            self.current_prompt=None
            self._running=False
            self.cancelling=False
            try:
                await asyncio.to_thread(self.store.cleanup)
            except (OSError,ValueError):
                # A failed cleanup must not hide an otherwise valid export or
                # remove anything outside the job's own staging directory.
                logging.warning('Could not remove HDR staging files for job %s',self.store.identity,exc_info=True)
