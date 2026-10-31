"""Internal Comfy adapter for the two-stage long HDR outpaint prototype."""
import asyncio
import os
from pathlib import Path
import shutil
import time
import uuid

from .hdr_outpaint_artifacts import checked_stage
from .hdr_outpaint_long_conversion import create_long_hdr_conversion
from .hdr_outpaint_long_job import LongHDROutpaintJob
from .hdr_outpaint_long_plan import plan_hdr_windows, long_plan_values
from .hdr_outpaint_long_runner import run_long_hdr_sdr_pass, run_long_hdr_review
from .hdr_outpaint_queue import ReviewedHDRQueue


def _failure_message(entry, fallback):
    messages=entry.get('status',{}).get('messages',[])
    errors=[item[1].get('exception_message','') for item in messages
            if isinstance(item,(list,tuple)) and len(item)>1 and item[0]=='execution_error' and isinstance(item[1],dict)]
    return (errors[-1] if errors and errors[-1] else fallback)[:1200]


class LongHDRReviewJob:
    def __init__(self, run_review, cleanup):
        self.run_review,self.cleanup=run_review,cleanup
        self.state='ready';self.error=None;self.result=None;self.progress=None;self.active={'id':None}
    def snapshot(self):
        return {'state':self.state,'error':self.error,'result':self.result,'progress':self.progress,
                'active_prompt_id':self.active['id']}
    async def run(self):
        if self.state!='ready':raise ValueError('This HDR review has already started.')
        self.state='running'
        try:
            self.result=await self.run_review(lambda state,index,total:setattr(self,'progress',{
                'state':state,'window':min(index+1,total),'windows':total}))
            self.state='complete';return self.result
        except asyncio.CancelledError:
            self.state='cancelled';self.error='Stopped this HDR review.';raise
        except Exception as exc:
            self.state='failed';self.error=str(exc)[:1200];raise
        finally:
            self.active['id']=None
            await self.cleanup(self.state=='complete')


def create_long_hdr_review_job(server, source, selection, *, review_key, output_root,
                               check_asset, client_id='zura-hdr-outpaint', ffmpeg=None):
    """Create a private full-range review; no public Studio route yet."""
    from .enhancement import inspect_video
    from .outpaint_chunks import disk_requirements
    values=long_plan_values(selection)
    expected,parts,_=plan_hdr_windows(source,duration=selection['requested_duration'],
                                        **values)
    if review_key!=expected['review_key'] or selection.get('review_key')!=expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    if len(parts)<2:raise ValueError('Use the single-section HDR review for this range.')
    check_asset(source)
    executable=ffmpeg or shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is required for HDR review.')
    root=Path(output_root).resolve();directory=root/'genj'/'hdr_outpaint';directory.mkdir(parents=True,exist_ok=True)
    directory=directory.resolve()
    if not directory.is_relative_to(root):raise ValueError('The HDR review folder is outside Comfy output.')
    output_bytes,_=disk_requirements(expected['width'],expected['height'],parts)
    if shutil.disk_usage(directory).free<output_bytes:raise ValueError('Not enough free disk space for HDR review.')
    identity=uuid.uuid4().hex;output=directory/(identity+'_review.mp4')
    if output.exists():raise ValueError('The HDR review output already exists.')
    children=[];pending={};active={'id':None}
    adapter=ReviewedHDRQueue(server,root,client_id=client_id,identity=identity,selection=expected,
        has_audio=False,update=lambda stage:None,on_prompt=lambda value:active.update(id=value))
    async def submit(subplan,graph):
        prefix=graph['save']['inputs']['filename_prefix'].rsplit('/',1)[-1]
        prompt_id=await adapter.submit('review',graph);pending[prompt_id]=(prefix,subplan)
        return prompt_id
    async def wait(prompt_id):
        queue=server.prompt_queue;started=time.monotonic()
        while True:
            entry=queue.get_history(prompt_id).get(prompt_id)
            if entry:
                if entry.get('status',{}).get('status_str')!='success':raise ValueError(_failure_message(entry,'An HDR review section failed.'))
                refs=entry.get('outputs',{}).get('save',{}).get('images',[])
                if not isinstance(refs,list) or len(refs)!=1:raise ValueError('A review section did not return its video.')
                prefix,sub=pending[prompt_id]
                path=await asyncio.to_thread(checked_stage,root,refs[0],prefix,
                    width=sub['width'],height=sub['height'],frames=sub['frames'])
                children.append(path);active['id']=None;return path
            running,queued=queue.get_current_queue_volatile()
            if not any(item[1]==prompt_id for item in (*running,*queued)) and time.monotonic()-started>20:
                raise ValueError('An HDR review section disappeared. It was not resubmitted.')
            await asyncio.sleep(.5)
    async def run_review(update):
        path=await run_long_hdr_review(source=source,selection=expected,review_key=review_key,
            submit=submit,wait=wait,cancel=adapter.cancel,update=update,ffmpeg=executable,output=output,check_asset=check_asset)
        await asyncio.to_thread(inspect_video,path,expected_frames=expected['frames'],
            expected_width=expected['width'],expected_height=expected['height'],expected_fps=24,expected_audio_tracks=0)
        return {'type':'output','subfolder':'genj/hdr_outpaint','filename':output.name}
    async def cleanup(success):
        active['id']=None
        for path in children:await asyncio.to_thread(path.unlink,missing_ok=True)
        if not success:await asyncio.to_thread(output.unlink,missing_ok=True)
    job=LongHDRReviewJob(run_review,cleanup);job.active=active
    return job,{'id':identity,'frames':expected['frames'],'sections':len(parts),
                'fps':24,'width':expected['width'],'height':expected['height']}


def create_long_hdr_outpaint_job(server, source, selection, *, review_key, output_root,
                                 input_root, check_asset, prompt='', seed=42,
                                 client_id='zura-hdr-outpaint', ffmpeg=None):
    """Create one isolated job; no Studio route is registered here."""
    from .outpaint_chunks import disk_requirements
    values=long_plan_values(selection)
    expected,parts,_=plan_hdr_windows(source,duration=selection['requested_duration'],
                                       **values)
    if review_key!=expected['review_key'] or selection.get('review_key')!=expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    if len(parts)<2:raise ValueError('Use the single-section HDR workflow for this range.')
    if not isinstance(prompt,str) or len(prompt)>4000 or type(seed) is not int or not 0<=seed<=2**53-1:
        raise ValueError('Choose a valid prompt and seed.')
    check_asset(source)
    executable=ffmpeg or shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is required for HDR frame extension.')
    output_root=Path(output_root).resolve();input_root=Path(input_root).resolve()
    output_dir=output_root/'genj'/'hdr_outpaint';output_dir.mkdir(parents=True,exist_ok=True)
    input_dir=input_root/'genj_studio';input_dir.mkdir(parents=True,exist_ok=True)
    output_dir=output_dir.resolve();input_dir=input_dir.resolve()
    if not output_dir.is_relative_to(output_root) or not input_dir.is_relative_to(input_root):
        raise ValueError('The HDR working folders are outside the Comfy directories.')
    output_bytes,input_bytes=disk_requirements(expected['width'],expected['height'],parts,anchor=True)
    # Include conservative HDR staging and final deliverables in the same
    # preflight rather than discovering insufficient space after sampling.
    from .hdr_chunk_comfy import staging_root
    stage_dir=staging_root();stage_dir.mkdir(parents=True,exist_ok=True)
    staging_bytes=sum(part.count for part in parts)*expected['width']*expected['height']*12+512*1024**2
    output_bytes+=expected['frames']*expected['width']*expected['height']*10
    groups={}
    for directory,needed in ((output_dir,output_bytes),(input_dir,input_bytes),(stage_dir,staging_bytes)):
        device=os.stat(directory).st_dev
        if device in groups:groups[device][1]+=needed
        else:groups[device]=[directory,needed]
    enough=all(shutil.disk_usage(directory).free>=needed for directory,needed in groups.values())
    if not enough:raise ValueError('Not enough free disk space for HDR frame extension.')
    identity=uuid.uuid4().hex;intermediate=output_dir/(identity+'_assembled.mp4')
    if intermediate.exists():raise ValueError('The HDR intermediate already exists.')
    anchors=[];children=[];pending={};anchor_dir=input_dir/('hdr-outpaint-'+identity);anchor_created=False
    active={'id':None}
    adapter=ReviewedHDRQueue(server,output_root,client_id=client_id,identity=identity,
        selection=expected,has_audio=False,update=lambda stage:None,on_prompt=lambda value:active.update(id=value))

    async def submit(subplan,graph):
        prefix=graph['stage_save']['inputs']['filename_prefix'].rsplit('/',1)[-1]
        prompt_id=await adapter.submit('outpaint',graph)
        pending[prompt_id]=(prefix,subplan)
        return prompt_id

    async def wait(prompt_id):
        queue=server.prompt_queue;started=time.monotonic()
        while True:
            entry=queue.get_history(prompt_id).get(prompt_id)
            if entry:
                if entry.get('status',{}).get('status_str')!='success':
                    raise ValueError(_failure_message(entry,'An HDR frame-extension section failed. Check ComfyUI for details.'))
                refs=entry.get('outputs',{}).get('stage_save',{}).get('images',[])
                if not isinstance(refs,list) or len(refs)!=1:raise ValueError('A section did not return its video.')
                prefix,sub=pending[prompt_id]
                path=await asyncio.to_thread(checked_stage,output_root,refs[0],prefix,
                    width=sub['width'],height=sub['height'],frames=sub['frames'])
                children.append(path);active['id']=None
                return path
            running,queued=queue.get_current_queue_volatile()
            if not any(item[1]==prompt_id for item in (*running,*queued)) and time.monotonic()-started>20:
                raise ValueError('An HDR section disappeared from ComfyUI. It was not resubmitted.')
            await asyncio.sleep(.5)

    async def make_anchor(path,index):
        nonlocal anchor_created
        from .outpaint_anchor import extract_frame
        if not anchor_created:
            anchor_dir.mkdir(exist_ok=False);anchor_created=True
        target=anchor_dir/f'{len(anchors):04d}.png';anchors.append(target)
        await asyncio.to_thread(extract_frame,path,target,index)
        return target.relative_to(input_root).as_posix()

    async def run_sdr(update):
        try:
            return await run_long_hdr_sdr_pass(source=source,selection=expected,review_key=review_key,
                prompt=prompt,seed=seed,submit=submit,wait=wait,cancel=adapter.cancel,update=update,
                make_anchor=make_anchor,ffmpeg=executable,output=intermediate,check_asset=check_asset)
        finally:
            active['id']=None
            for path in children:await asyncio.to_thread(path.unlink,missing_ok=True)
            for path in anchors:await asyncio.to_thread(path.unlink,missing_ok=True)
            if anchor_created and anchor_dir.exists():
                try:anchor_dir.rmdir()
                except OSError:pass

    def conversion(path):
        return create_long_hdr_conversion(server,source,expected,path,review_key=review_key,
            output_root=output_root,check_asset=check_asset,client_id=client_id,ffmpeg=executable)

    async def cleanup(path):
        if Path(path)==intermediate:await asyncio.to_thread(intermediate.unlink,missing_ok=True)

    job=LongHDROutpaintJob(run_sdr,conversion,cleanup,intermediate)
    job.sdr_active=active
    return job,{'id':identity,'frames':expected['frames']+(1-expected['frames'])%8,
                'sections':len(parts),'fps':24,'width':expected['width'],'height':expected['height']}
