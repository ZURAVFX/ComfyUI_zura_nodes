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


def validated_client_id(client_id):
    if client_id is not None and (not isinstance(client_id,str) or not client_id or len(client_id)>128):
        raise ValueError('Invalid Studio connection. Reload Studio and try again.')
    return client_id or 'zura-hdr-chunks'


def validate_anchor_settings(anchor_strength,anchor_mode):
    if anchor_strength is None:return
    if isinstance(anchor_strength,bool) or not isinstance(anchor_strength,(int,float)) or not 0<anchor_strength<=1:
        raise ValueError('Choose an HDR anchor strength above zero and at most one.')
    if anchor_mode not in ('guide','i2v'):raise ValueError('Unknown HDR anchor mode.')


class ZuraHDRWriteChunk:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'job_id':('STRING',{'default':''}),
            'start_frame':('INT',{'default':0,'min':0}),'total_frames':('INT',{'default':1,'min':1,'max':10000}),
            'width':('INT',{'default':512,'min':32,'max':4096}),
            'height':('INT',{'default':512,'min':32,'max':4096}),
            'max_frames':('INT',{'default':121,'min':9,'max':121}),
            'overlap':('INT',{'default':8,'min':1,'max':60}),
            'chunk_index':('INT',{'default':0,'min':0})},'optional':{'single_frame':('BOOLEAN',{'default':False}),'colour_space':(['acescct','acescg'],{'default':'acescct'}),'planning_mode':(['native','sdr'],{'default':'native'})}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='write'
    CATEGORY='Zura/Artist Studio'
    def write(self,images,job_id,start_frame,total_frames,width,height,max_frames,overlap,chunk_index,single_frame=False,colour_space='acescct',planning_mode='native'):
        if type(single_frame) is not bool:raise ValueError('Invalid still HDR staging mode.')
        if single_frame:
            from .hdr_prepare import sdr_still_limit
            from .hdr_chunks import HDRChunk
            if start_frame!=0 or total_frames!=1 or chunk_index!=0 or not sdr_still_limit(width,height):raise ValueError('Still HDR staging requires one exact source frame within the spatial budget.')
            plan=[HDRChunk(0,1,0)]
        else:plan=plan_chunks(start_frame,total_frames,width,height,overlap=overlap,max_frames=max_frames,mode=planning_mode)
        HDRChunkStore(staging_root(),job_id,plan,width,height,colour_space=colour_space,planning_mode=planning_mode).write(chunk_index,images)
        return {'ui':{'text':[f'Staged HDR chunk {chunk_index+1} of {len(plan)}.']},'result':()}


class ZuraHDRReadChunkAnchor:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'job_id':('STRING',{'default':''}),
            'start_frame':('INT',{'default':0,'min':0}),'total_frames':('INT',{'default':1,'min':1,'max':10000}),
            'width':('INT',{'default':512,'min':32,'max':4096}),
            'height':('INT',{'default':512,'min':32,'max':4096}),
            'max_frames':('INT',{'default':121,'min':9,'max':121}),
            'overlap':('INT',{'default':8,'min':1,'max':60}),
            'chunk_index':('INT',{'default':1,'min':1})},'optional':{'colour_space':(['acescct','acescg'],{'default':'acescct'}),'planning_mode':(['native','sdr'],{'default':'native'})}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='read'
    CATEGORY='Zura/Artist Studio'
    def read(self,job_id,start_frame,total_frames,width,height,max_frames,overlap,chunk_index,colour_space='acescct',planning_mode='native'):
        plan=plan_chunks(start_frame,total_frames,width,height,overlap=overlap,max_frames=max_frames,mode=planning_mode)
        if not 1<=chunk_index<len(plan):raise ValueError('Invalid continuation chunk index.')
        previous=HDRChunkStore(staging_root(),job_id,plan,width,height,colour_space=colour_space,planning_mode=planning_mode).read(chunk_index-1)
        offset=plan[chunk_index].start-plan[chunk_index-1].start
        if not 0<=offset<len(previous):raise ValueError('Previous HDR chunk does not cover the continuation frame.')
        anchor=previous[offset:offset+1].clone()
        if colour_space=='acescg':
            from ..paintout.paintout import native_colour
            anchor=native_colour(anchor,'linear ACEScg','HDR ACEScct')
        return (anchor,)


class ZuraHDRPadSDRAnchor:
    """Pad a generated ACEScct anchor exactly like the SDR source guide."""
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'images':('IMAGE',)}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='prepare'
    CATEGORY='Zura/Artist Studio'
    def prepare(self,images):
        import torch
        import torch.nn.functional as F
        if not isinstance(images,torch.Tensor) or images.ndim!=4 or images.shape[-1]!=3 or len(images)!=1 or not torch.isfinite(images).all():
            raise ValueError('Expected one finite ACEScct anchor frame.')
        height,width=images.shape[1:3]
        if min(width,height)<32 or max(width,height)>4096:raise ValueError('Invalid HDR anchor dimensions.')
        right=(-width)%32;bottom=(-height)%32
        if right or bottom:images=F.pad(images.permute(0,3,1,2),(0,right,0,bottom),mode='reflect').permute(0,2,3,1)
        return (images,)


NODE_CLASS_MAPPINGS={'ZuraHDRWriteChunk':ZuraHDRWriteChunk,'ZuraHDRReadChunkAnchor':ZuraHDRReadChunkAnchor,'ZuraHDRPadSDRAnchor':ZuraHDRPadSDRAnchor}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRWriteChunk':'Zura · Stage HDR Chunk',
                            'ZuraHDRReadChunkAnchor':'Zura · Read HDR Continuation Anchor',
                            'ZuraHDRPadSDRAnchor':'Zura · Pad SDR-to-HDR Anchor'}


def chunk_graph(graph, store, index, image_node, anchor_strength=None, anchor_mode='guide'):
    """Keep the model branch and replace whole-clip delivery with staging."""
    source_detail=image_node=='hdr_unpad_raster' and graph.get('hdr_detail',{}).get('class_type')=='ZuraHDRSourceDetail'
    if source_detail:image_node='hdr_detail'
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
    planning_mode=getattr(store,'planning_mode','sdr' if source_detail else 'native')
    if planning_mode=='sdr':graph['zura_hdr_stage_chunk']['inputs']['planning_mode']='sdr'
    if graph.get('zura_hdr_prepare',{}).get('inputs',{}).get('single_frame') is True:
        graph['zura_hdr_stage_chunk']['inputs']['single_frame']=True
    if source_detail:graph['zura_hdr_stage_chunk']['inputs']['colour_space']='acescg'
    if index and anchor_strength is not None:
        validate_anchor_settings(anchor_strength,anchor_mode)
        is_sdr={'hdr_guide','hdr_vae','hdr_empty_video'} <= graph.keys()
        if not is_sdr and not {'guide1','sample1','guide2','sample2','vae','empty','upsample'} <= graph.keys():
            raise ValueError('This HDR graph does not support the experimental continuation anchor.')
        if is_sdr and anchor_mode!='i2v':raise ValueError('SDR-to-HDR continuation supports only an I2V anchor.')
        inputs=graph['zura_hdr_stage_chunk']['inputs']
        graph['zura_hdr_previous_anchor']={'class_type':'ZuraHDRReadChunkAnchor','inputs':{
            key:inputs[key] for key in ('job_id','start_frame','total_frames','width','height','max_frames','overlap','chunk_index')}}
        if source_detail:graph['zura_hdr_previous_anchor']['inputs']['colour_space']='acescg'
        if planning_mode=='sdr':graph['zura_hdr_previous_anchor']['inputs']['planning_mode']='sdr'
        if is_sdr:
            graph['zura_hdr_anchor_pad']={'class_type':'ZuraHDRPadSDRAnchor','inputs':{'images':['zura_hdr_previous_anchor',0]}}
            graph['zura_hdr_sdr_anchor']={'class_type':'LTXVImgToVideoInplace','inputs':{'vae':['hdr_vae',0],
                'image':['zura_hdr_anchor_pad',0],'latent':['hdr_empty_video',0],
                'strength':float(anchor_strength),'bypass':False}}
            graph['hdr_guide']['inputs']['latent']=['zura_hdr_sdr_anchor',0]
            return graph
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
    def __init__(self,server,store,make_graph,image_node,anchor_strength=None,anchor_mode='guide',client_id=None):
        validate_anchor_settings(anchor_strength,anchor_mode)
        self.server=server;self.store=store;self.make_graph=make_graph;self.image_node=image_node
        self.anchor_strength=anchor_strength
        self.anchor_mode=anchor_mode
        self.client_id=validated_client_id(client_id)

    async def submit(self,index,part):
        import execution
        identity=uuid.uuid4().hex
        graph=chunk_graph(await asyncio.to_thread(self.make_graph,part),self.store,index,self.image_node,self.anchor_strength,self.anchor_mode)
        server=self.server
        graph=server.trigger_on_prompt({'prompt':graph,'prompt_id':identity,'client_id':self.client_id})['prompt']
        server.node_replace_manager.apply_replacements(graph)
        valid=await execution.validate_prompt(identity,graph,None)
        if not valid[0]:raise ValueError('ComfyUI cannot run this HDR chunk: '+str(valid[1])[:1200])
        number=server.number;server.number+=1
        server.prompt_queue.put((number,identity,graph,{'client_id':self.client_id,
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
