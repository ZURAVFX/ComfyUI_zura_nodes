"""Private two-stage long HDR frame-extension job.

The caller owns the exclusive intermediate destination and supplies the
first-pass runner and cleanup. No Studio route is registered here.
"""
import asyncio

from .hdr_chunk_store import HDRChunkCancelled


class LongHDROutpaintJob:
    def __init__(self, run_sdr, create_conversion, cleanup, intermediate_path):
        self.run_sdr, self.create_conversion, self.cleanup = run_sdr, create_conversion, cleanup
        self.intermediate_path = intermediate_path
        self.state='ready';self.stage='preparing';self.result=None;self.error=None
        self.conversion=None;self.conversion_details=None;self.sdr_progress=None;self.cleanup_warning=None

    def update_sdr(self, state, index, total):
        self.sdr_progress={'state':state,'window':min(index+1,total),'windows':total}

    def snapshot(self):
        child=self.conversion.snapshot() if self.conversion else None
        active=child.get('active_prompt_id') if child else getattr(self,'sdr_active',{}).get('id')
        return {'state':self.state,'stage':self.stage,'error':self.error,'result':self.result,
                'sdr':self.sdr_progress,'hdr':child,'active_prompt_id':active,'cleanup_warning':self.cleanup_warning}

    async def run(self):
        if self.state!='ready':raise ValueError('This HDR frame-extension job has already started.')
        self.state='running'
        try:
            self.stage='extending'
            intermediate=await self.run_sdr(self.update_sdr)
            if intermediate != self.intermediate_path:
                raise ValueError('The HDR intermediate does not match this job.')
            self.stage='preparing_hdr'
            pending=asyncio.create_task(asyncio.to_thread(self.create_conversion, intermediate))
            try:
                self.conversion,self.conversion_details = await asyncio.shield(pending)
            except asyncio.CancelledError:
                # The preparation thread can create a private staging folder.
                # Wait for its result and clean it rather than abandoning it.
                try:
                    conversion,_ = await pending
                except Exception:
                    pass
                else:
                    await asyncio.to_thread(conversion.store.cleanup)
                raise
            self.stage='converting_hdr'
            conversion_task=asyncio.create_task(self.conversion.run())
            try:
                self.result=await asyncio.shield(conversion_task)
            except asyncio.CancelledError:
                await self.conversion.cancel()
                try:
                    await conversion_task
                except (HDRChunkCancelled,asyncio.CancelledError):
                    pass
                raise
            self.stage='complete';self.state='complete'
            return self.result
        except asyncio.CancelledError:
            self.state='cancelled';self.error='Stopped this HDR frame-extension job.'
            raise
        except HDRChunkCancelled:
            self.state='cancelled';self.error='Stopped this HDR frame-extension job.'
            raise
        except Exception as exc:
            self.state='failed';self.error=str(exc)[:1200]
            raise
        finally:
            try:
                await self.cleanup(self.intermediate_path)
            except OSError:
                self.cleanup_warning='The temporary HDR intermediate could not be removed.'
