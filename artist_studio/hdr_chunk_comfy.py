"""Internal native Comfy queue adapter for bounded HDR chunk generation.

This is not registered as a Studio endpoint. The coordinator must perform all
source, model and export preflight checks before submitting the first prompt.
"""
from __future__ import annotations

import asyncio
import copy
import time
import uuid
from pathlib import Path

from .hdr_chunks import plan_chunks
from .hdr_chunk_store import HDRChunkCancelled, HDRChunkStore


def staging_root():
    import folder_paths
    return Path(folder_paths.get_temp_directory())/'zura_hdr_staging'


class ZuraHDRWriteChunk:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'job_id':('STRING',{'default':''}),
            'start_frame':('INT',{'default':0,'min':0}),'total_frames':('INT',{'default':1,'min':1,'max':10000}),
            'width':('INT',{'default':512,'min':32,'max':2048}),
            'height':('INT',{'default':512,'min':32,'max':2048}),
            'max_frames':('INT',{'default':121,'min':9,'max':121}),
            'overlap':('INT',{'default':8,'min':1,'max':60}),
            'chunk_index':('INT',{'default':0,'min':0})}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='write'
    CATEGORY='Zura/Artist Studio'
    def write(self,images,job_id,start_frame,total_frames,width,height,max_frames,overlap,chunk_index):
        plan=plan_chunks(start_frame,total_frames,width,height,overlap=overlap,max_frames=max_frames)
        HDRChunkStore(staging_root(),job_id,plan,width,height).write(chunk_index,images)
        return {'ui':{'text':[f'Staged HDR chunk {chunk_index+1} of {len(plan)}.']},'result':()}


class ZuraHDRReadChunkAnchor:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'job_id':('STRING',{'default':''}),
            'start_frame':('INT',{'default':0,'min':0}),'total_frames':('INT',{'default':1,'min':1,'max':10000}),
            'width':('INT',{'default':512,'min':32,'max':2048}),
            'height':('INT',{'default':512,'min':32,'max':2048}),
            'max_frames':('INT',{'default':121,'min':9,'max':121}),
            'overlap':('INT',{'default':8,'min':1,'max':60}),
            'chunk_index':('INT',{'default':1,'min':1})}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='read'
    CATEGORY='Zura/Artist Studio'
    def read(self,job_id,start_frame,total_frames,width,height,max_frames,overlap,chunk_index):
        plan=plan_chunks(start_frame,total_frames,width,height,overlap=overlap,max_frames=max_frames)
        if not 1<=chunk_index<len(plan):raise ValueError('Invalid continuation chunk index.')
        previous=HDRChunkStore(staging_root(),job_id,plan,width,height).read(chunk_index-1)
        offset=plan[chunk_index].start-plan[chunk_index-1].start
        if not 0<=offset<len(previous):raise ValueError('Previous HDR chunk does not cover the continuation frame.')
        return (previous[offset:offset+1].clone(),)


NODE_CLASS_MAPPINGS={'ZuraHDRWriteChunk':ZuraHDRWriteChunk,'ZuraHDRReadChunkAnchor':ZuraHDRReadChunkAnchor}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRWriteChunk':'Zura · Stage HDR Chunk',
                            'ZuraHDRReadChunkAnchor':'Zura · Read HDR Continuation Anchor'}


def chunk_graph(graph, store, index, image_node, anchor_strength=None, anchor_mode='guide'):
    """Keep the model branch and replace whole-clip delivery with staging."""
    if image_node not in graph or not 0<=index<len(store.plan):
        raise ValueError('HDR chunk graph is missing its output frames.')
    graph={key:copy.deepcopy(value) for key,value in graph.items() if key not in {
        'zura_hdr_hlg','zura_hdr_video','zura_hdr_save_video','zura_hdr_exr',
        'zura_hdr_archive','zura_hdr_preview_tonemap','zura_hdr_preview_video',
        'zura_hdr_save_preview'}}
    total=store.plan[-1].start+store.plan[-1].count-store.plan[0].start
    graph['zura_hdr_stage_chunk']={'class_type':'ZuraHDRWriteChunk','inputs':{
        'images':[image_node,0],'job_id':store.identity,'start_frame':store.plan[0].start,
        'total_frames':total,'width':store.width,'height':store.height,
        'max_frames':store.plan[0].count if len(store.plan)>1 else 121,
        'overlap':store.plan[1].overlap if len(store.plan)>1 else 8,'chunk_index':index}}
    if index and anchor_strength is not None:
        if isinstance(anchor_strength,bool) or not isinstance(anchor_strength,(int,float)) or not 0<anchor_strength<=1:
            raise ValueError('Choose an HDR anchor strength above zero and at most one.')
        if anchor_mode not in ('guide','i2v'):raise ValueError('Unknown HDR anchor mode.')
        if not {'guide1','sample1','guide2','sample2','vae','empty','upsample'} <= graph.keys():
            raise ValueError('This HDR graph does not support the experimental continuation anchor.')
        inputs=graph['zura_hdr_stage_chunk']['inputs']
        graph['zura_hdr_previous_anchor']={'class_type':'ZuraHDRReadChunkAnchor','inputs':{
            key:inputs[key] for key in ('job_id','start_frame','total_frames','width','height','max_frames','overlap','chunk_index')}}
        graph['zura_hdr_anchor_pad']={'class_type':'ZuraHDRNativePrepare','inputs':{'images':['zura_hdr_previous_anchor',0]}}
        graph['zura_hdr_anchor_first']={'class_type':'ImageFromBatch','inputs':{'image':['zura_hdr_anchor_pad',0],'batch_index':0,'length':1}}
        for stage in (1,2):
            source=f'guide{stage}'; anchor=f'zura_hdr_anchor_guide{stage}'; sampler=f'sample{stage}'
            if anchor_mode=='guide':
                graph[anchor]={'class_type':'LTXVAddGuide','inputs':{'positive':[source,0],'negative':[source,1],
                    'latent':[source,2],'vae':['vae',0],'image':['zura_hdr_anchor_first',0],
                    'frame_idx':0,'strength':float(anchor_strength)}}
                graph[sampler]['inputs'].update(positive=[anchor,0],negative=[anchor,1],latents=[anchor,2])
            else:
                latent='empty' if stage==1 else 'upsample'
                graph[anchor]={'class_type':'LTXVImgToVideoInplace','inputs':{'vae':['vae',0],
                    'image':['zura_hdr_anchor_first',0],'latent':[latent,0],
                    'strength':float(anchor_strength),'bypass':False}}
                graph[source]['inputs']['latent']=[anchor,0]
    return graph


class ComfyHDRRenderer:
    """Submit one chunk, wait for its own history, then release its prompt."""
    def __init__(self,server,store,make_graph,image_node,anchor_strength=None,anchor_mode='guide'):
        self.server=server;self.store=store;self.make_graph=make_graph;self.image_node=image_node
        self.anchor_strength=anchor_strength
        self.anchor_mode=anchor_mode

    async def submit(self,index,part):
        import execution
        identity=uuid.uuid4().hex
        graph=chunk_graph(await asyncio.to_thread(self.make_graph,part),self.store,index,self.image_node,self.anchor_strength,self.anchor_mode)
        server=self.server
        graph=server.trigger_on_prompt({'prompt':graph,'prompt_id':identity,'client_id':'zura-hdr-chunks'})['prompt']
        server.node_replace_manager.apply_replacements(graph)
        valid=await execution.validate_prompt(identity,graph,None)
        if not valid[0]:raise ValueError('ComfyUI cannot run this HDR chunk: '+str(valid[1])[:1200])
        number=server.number;server.number+=1
        server.prompt_queue.put((number,identity,graph,{'client_id':'zura-hdr-chunks',
            'create_time':int(time.time()*1000),'comfy_usage_source':'zura-studio'},valid[2],{}))
        return identity,self._wait(identity)

    async def _wait(self,identity):
        queue=self.server.prompt_queue
        missing_since=None
        while True:
            if self.store.cancelled.is_set():
                await self._wait_until_stopped(identity)
                raise HDRChunkCancelled('HDR conversion cancelled.')
            history=queue.get_history(identity).get(identity)
            if history:
                if history.get('status',{}).get('status_str')!='success':
                    raise RuntimeError('The HDR chunk failed. Check ComfyUI job details.')
                if 'zura_hdr_stage_chunk' not in history.get('outputs',{}):
                    raise RuntimeError('The HDR chunk did not stage its result.')
                return None
            running,pending=queue.get_current_queue_volatile()
            if any(item[1]==identity for item in running+pending):missing_since=None
            else:
                # Queue/history snapshots can race. Never silently resubmit.
                if missing_since is None:missing_since=time.monotonic()
                elif time.monotonic()-missing_since>90:
                    raise RuntimeError('The HDR chunk disappeared from the Comfy queue; it was not resubmitted.')
            await asyncio.sleep(1)

    async def _wait_until_stopped(self,identity):
        """Do not report cancellation while this prompt is still executing."""
        queue=self.server.prompt_queue
        while True:
            running,pending=queue.get_current_queue_volatile()
            if not any(item[1]==identity for item in (*running,*pending)):
                return
            await asyncio.sleep(.25)

    async def cancel(self,identity):
        queue=self.server.prompt_queue
        queue.interrupt_if_running(identity)
        queue.delete_queue_item(lambda item:item[1]==identity)
        await self._wait_until_stopped(identity)
