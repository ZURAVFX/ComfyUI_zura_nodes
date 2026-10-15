"""Local word selection, tracked face crops and bounded dialogue compositing."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import uuid

import cv2
import numpy as np
import torch
from aiohttp import web

import folder_paths
from comfy_api.latest import InputImpl
from .media_source import local_path, require_same_origin, LOCAL_DEMUX


def ffmpeg(*args, data=None):
    executable = shutil.which('ffmpeg')
    if executable is None:
        raise RuntimeError('Install FFmpeg on PATH, then restart ComfyUI.')
    return subprocess.run([executable, '-v', 'error', '-y', *map(str, args)], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def stamp(path):
    stat = path.stat()
    return hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()


def inspect(path):
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width, height = int(cap.get(3)), int(cap.get(4))
    finally:
        cap.release()
    if fps <= 0 or count < 1 or width < 1 or height < 1:
        raise ValueError('The selected file has no readable video frames.')
    return dict(fps=fps, frames=count, width=width, height=height, duration=count/fps, identity=stamp(path))


def read_audio(path, rate=48000):
    raw = ffmpeg(*LOCAL_DEMUX, '-i', path, '-vn', '-ac', 2, '-ar', rate, '-f', 'f32le', 'pipe:1')
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def peaks(audio, bins=1400):
    mono = np.max(np.abs(audio), axis=1)
    edges = np.linspace(0, len(mono), min(bins, len(mono))+1).astype(int)
    return [float(mono[a:b].max(initial=0)) for a, b in zip(edges[:-1], edges[1:])]


def ltx_geometry(render_size, crop_width, crop_height, frames):
    """Bound this local two-stage profile; never round away source frames."""
    if not all(math.isfinite(v) and v > 0 for v in (render_size, crop_width, crop_height, frames)):
        raise ValueError('Resolution, crop size and frame count must be positive finite values.')
    width = math.ceil(render_size/64)*64
    height = max(64, math.ceil(width*crop_height/crop_width/64)*64)
    count = math.ceil((frames-1)/8)*8+1
    # These are workstation-profile limits, not claims about LTX model limits.
    if max(width, height) > 512:
        raise ValueError('This quality profile supports up to 1024 pixels after refinement. Use a smaller render size or a squarer face crop.')
    if count > 121:
        raise ValueError('This local profile supports up to 121 padded frames per context. Shorten the context around the selected words.')
    return width, height, count


def validate_generated(edit, shape, generated_start, generated_end):
    expected = edit.get('generation')
    if expected and tuple(shape[:3]) != (expected['frames'], expected['height'], expected['width']):
        raise ValueError(f"Generated video has {tuple(shape[:3])}; expected frames/height/width "
                         f"{(expected['frames'], expected['height'], expected['width'])}. Rerun both LTX stages.")
    if len(shape) != 4 or shape[-1] != 3:
        raise ValueError('Generated video must contain RGB frames.')
    if not (math.isfinite(generated_start) and math.isfinite(generated_end)
            and 0 <= generated_start < generated_end <= shape[0]/edit['meta']['fps']):
        raise ValueError('The generated word range must be inside the generated video.')


def verify_export(path, meta):
    actual = inspect(path)
    if any(actual[k] != meta[k] for k in ('frames', 'width', 'height')) or abs(actual['fps']-meta['fps']) > 1e-5:
        raise RuntimeError('Export geometry or frame rate differs from the source. The result was not accepted.')
    return {k:actual[k] for k in ('frames','width','height','fps','duration')}


def validate_source_cadence(path, meta):
    executable=shutil.which('ffprobe')
    if executable is None:raise RuntimeError('Install FFprobe with FFmpeg, then restart ComfyUI.')
    data=json.loads(subprocess.run([executable,'-v','error','-select_streams','v:0','-show_packets',
        '-show_entries','packet=pts_time','-of','json',str(path)],capture_output=True,check=True).stdout)
    pts=sorted(float(p['pts_time']) for p in data['packets'] if 'pts_time' in p)
    if len(pts)!=meta['frames'] or not np.allclose(np.diff(pts),1/meta['fps'],rtol=0,atol=.0002):
        raise ValueError('This editor requires a constant-frame-rate source. Convert the variable-rate clip before selecting words.')
    if pts and abs(pts[0])>.0002:
        raise ValueError('The source video must start at timestamp zero. Re-export it before selecting words.')


def selection_data(value, meta):
    value = json.loads(value)
    if 'box' not in value or 'mouth' not in value:
        raise ValueError('Open Select words and face, draw a face crop and place the mouth region.')
    if value.get('identity') and value['identity'] != meta['identity']:
        raise ValueError('The source changed. Reopen Select words and face and select it again.')
    box = np.asarray(value['box'], dtype=float)
    mouth = np.asarray(value['mouth'], dtype=float)
    if box.shape != (4,) or mouth.shape != (4,) or not np.isfinite(np.r_[box, mouth]).all():
        raise ValueError('Draw a face crop and set its mouth region in the picker.')
    x, y, w, h = box
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > meta['width']+1 or y+h > meta['height']+1:
        raise ValueError('Keep the face crop inside the video.')
    if mouth[2] <= 0 or mouth[3] <= 0 or not (x <= mouth[0] <= x+w and y <= mouth[1] <= y+h):
        raise ValueError('Place the mouth region inside the selected face crop.')
    return box, mouth, float(value.get('frame', 0))


def track_points(frames, reference, box, mouth, enabled):
    # Track the upper face, leaving the articulating mouth out of the features.
    anchor = min(len(frames)-1, max(0, reference))
    centres = np.tile(mouth[:2], (len(frames), 1)).astype(float)
    if not enabled:
        return centres
    x, y, w, h = map(int, box)
    mask = np.zeros(frames[0].shape[:2], np.uint8)
    mx, my, rx, ry = mouth
    cv2.ellipse(mask, (round(mx), round(my-1.4*ry)), (max(12, round(rx*1.2)), max(12, round(ry*1.4))), 0, 0, 360, 255, -1)
    mask[:y] = 0; mask[y+h:] = 0; mask[:, :x] = 0; mask[:, x+w:] = 0
    greys = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    for direction in (1, -1):
        pts = cv2.goodFeaturesToTrack(greys[anchor], 100, .01, 4, mask=mask)
        if pts is None or len(pts) < 4:
            raise ValueError('No stable face features in this crop. Enlarge it or disable tracking.')
        previous = anchor
        for i in range(anchor+direction, len(frames) if direction == 1 else -1, direction):
            nxt, status, _ = cv2.calcOpticalFlowPyrLK(greys[previous], greys[i], pts, None, winSize=(31,31), maxLevel=3)
            a, b = pts[status.ravel() == 1], nxt[status.ravel() == 1]
            if len(a) < 4:
                raise ValueError('Face tracking lost the subject. Shorten the context or choose a clearer reference frame.')
            transform, inliers = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=2.5)
            if transform is None:
                raise ValueError('Face tracking failed. Adjust the crop or disable tracking.')
            centres[i] = transform[:, :2] @ centres[previous] + transform[:, 2]
            pts = b[inliers.ravel().astype(bool)].reshape(-1,1,2)
            previous = i
    return centres


def resolve_timing(edit, generated_start, generated_end, timing_mode='source'):
    """Use one second of generated performance per second of source, always."""
    duration = edit['word_end']-edit['word_start']
    if timing_mode == 'source':
        generated_start = edit['word_start']-edit['first']/edit['meta']['fps']
    elif timing_mode == 'manual':
        if not all(math.isfinite(v) for v in (generated_start, generated_end)):
            raise ValueError('Choose finite replacement IN and OUT times.')
        if abs((generated_end-generated_start)-duration) > 1/edit['meta']['fps']+1e-6:
            raise ValueError('Replacement and original selections must have the same duration. '
                             'Adjust their IN/OUT points or use Match original timing. Video is never retimed.')
    else:
        raise ValueError('Choose source or manual replacement timing.')
    return generated_start, generated_start+duration


def blend_audio(original, generated, start, end, generated_start, generated_end, fade_ms=12, rate=48000, allow_retime=True):
    if not (0 <= start < end <= len(original)/rate + 1/rate):
        raise ValueError('The word range must be inside the source audio.')
    if not (0 <= generated_start < generated_end <= len(generated)/rate + 1/rate):
        raise ValueError('The generated word range must be inside the generated audio.')
    a, b = round(start*rate), round(end*rate)
    piece = generated[round(generated_start*rate):round(generated_end*rate)]
    if allow_retime:
        tempo = (generated_end-generated_start)/(end-start)
        filters = []
        while tempo > 2: filters.append('atempo=2'); tempo /= 2
        while tempo < .5: filters.append('atempo=0.5'); tempo *= 2
        filters += [f'atempo={tempo:.12f}', 'apad']
        raw = ffmpeg('-f','f32le','-ar',rate,'-ac',2,'-i','pipe:0','-af',','.join(filters),'-t',(end-start),'-f','f32le','pipe:1',data=piece.astype(np.float32).tobytes())
        piece = np.frombuffer(raw,np.float32).reshape(-1,2).copy()[:b-a]
    else:
        if abs((generated_end-generated_start)-(end-start)) > 1/rate+1e-8:
            raise ValueError('Video speech replacement requires matching durations; retiming is disabled.')
        piece = piece[:b-a].copy()
    piece = np.pad(piece,((0,max(0,b-a-len(piece))),(0,0)))
    rms = lambda v: float(np.sqrt(np.mean(v.astype(np.float64)**2)))
    gain = rms(original[a:b])/max(rms(piece),1e-8)
    piece *= gain
    fade = min(round(fade_ms/1000*rate),len(piece)//2)
    alpha = np.ones((len(piece),1),np.float32)
    if fade:
        alpha[:fade,0] = np.sin(np.linspace(0,np.pi/2,fade))**2
        alpha[-fade:,0] = np.cos(np.linspace(0,np.pi/2,fade))**2
    output = original.copy(); output[a:b] = original[a:b]*(1-alpha)+piece*alpha
    return output, gain


class ZuraDialogueSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'source': ('STRING', {'default':'', 'tooltip':'Upload a local video with the picker.'}),
            'word_start': ('FLOAT', {'default':1.145, 'min':0, 'step':.001}),
            'word_end': ('FLOAT', {'default':1.565, 'min':0, 'step':.001}),
            'context_start': ('FLOAT', {'default':0, 'min':0, 'step':.001}),
            'context_end': ('FLOAT', {'default':2.266667, 'min':0, 'step':.001}),
            'selection': ('STRING', {'default':'{}', 'multiline':False}),
            'render_size': ('INT', {'default':512, 'min':128, 'max':512, 'step':64, 'tooltip':'Base face width. The second LTX stage doubles this; the source video keeps its original size.'}),
            'track_face': ('BOOLEAN', {'default':True}),
        }, 'optional': {'stabilize_crop': ('BOOLEAN', {'default':False, 'tooltip':'Optional moving reference crop. Fixed reference crops are the tested default; mouth tracking still follows the speaker.'})}}
    RETURN_TYPES = ('IMAGE','AUDIO','INT','FLOAT','INT','INT','ZURA_DIALOGUE_EDIT')
    RETURN_NAMES = ('face_frames','reference_audio','padded_frames','fps','width','height','edit')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Dialogue'

    @classmethod
    def IS_CHANGED(cls, source, **kwargs):
        return stamp(local_path(source))

    def prepare(self, source, word_start, word_end, context_start, context_end, selection, render_size, track_face, stabilize_crop=False):
        path = local_path(source); meta = inspect(path)
        validate_source_cadence(path,meta)
        if meta['width'] % 2 or meta['height'] % 2:
            raise ValueError('The H264 export profile needs even source dimensions. Resize the source before selecting words.')
        if not (0 <= context_start <= word_start < word_end <= context_end <= meta['duration']+.001):
            raise ValueError('The word must be inside the context range, and the context inside the clip.')
        box, mouth, reference = selection_data(selection,meta)
        fps = meta['fps']; first = math.floor(context_start*fps); last = min(meta['frames'], math.ceil(context_end*fps))
        width,height,count = ltx_geometry(render_size,box[2],box[3],last-first)
        cap = cv2.VideoCapture(str(path)); cap.set(cv2.CAP_PROP_POS_FRAMES,first); frames=[]
        try:
            for _ in range(first,last):
                ok, frame = cap.read()
                if not ok: raise ValueError('Video decoding stopped before the selected context ended.')
                frames.append(frame)
        finally: cap.release()
        centres = track_points(frames,round(reference*fps)-first,box,mouth,track_face)
        x,y,w,h = box
        crops=[]; origins=[]
        for frame,centre in zip(frames,centres):
            delta = centre-mouth[:2] if track_face and stabilize_crop else np.zeros(2)
            left = float(np.clip(x+delta[0],0,meta['width']-w)); top=float(np.clip(y+delta[1],0,meta['height']-h))
            native_w,native_h=round(w),round(h)
            transform = np.array([[native_w/w,0,-left*native_w/w],[0,native_h/h,-top*native_h/h]],np.float32)
            crop = cv2.warpAffine(frame,transform,(native_w,native_h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
            crops.append(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB));origins.append([left,top])
        crops.extend([crops[-1]]*(count-len(crops)))
        audio = read_audio(path); a=round(first/fps*48000); b=round((first+count)/fps*48000)
        reference_audio = audio[a:b];reference_audio=np.pad(reference_audio,((0,max(0,b-a-len(reference_audio))),(0,0)))
        edit = dict(source=source,identity=meta['identity'],meta=meta,box=box.tolist(),mouth=mouth.tolist(),
                    centres=centres.tolist(),origins=origins,first=first,last=last,word_start=word_start,word_end=word_end,
                    generation=dict(width=width*2,height=height*2,frames=count,base_width=width,base_height=height),
                    crop_mode='tracked' if stabilize_crop else 'fixed')
        return (torch.from_numpy(np.stack(crops).astype(np.float32)/255),
                {'waveform':torch.from_numpy(reference_audio.T.copy()).unsqueeze(0),'sample_rate':48000},count,fps,width,height,edit)


class ZuraDialogueFinish:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'generated_frames':('IMAGE',), 'generated_audio':('AUDIO',), 'edit':('ZURA_DIALOGUE_EDIT',),
            'generated_word_start':('FLOAT',{'default':1.165,'min':0,'step':.001}),
            'generated_word_end':('FLOAT',{'default':1.600,'min':0,'step':.001}),
            'audio_fade_ms':('FLOAT',{'default':12,'min':0,'max':100,'step':1}),
            'mouth_feather':('FLOAT',{'default':.24,'min':.01,'max':1,'step':.01}),
            'filename_prefix':('STRING',{'default':'dialogue/euros'}),
        },'optional':{
            'temporal_resampling':(['blend','nearest'],{'default':'nearest','tooltip':'Nearest keeps a single mouth pose per output frame. Blend interpolates adjacent generated frames.'}),
            'timing_mode':(['source','manual'],{'default':'source','tooltip':'Source follows the original timestamps. Manual allows an offset with equal duration. Neither mode retimes video or audio.'}),
        }}
    RETURN_TYPES = ('VIDEO',)
    FUNCTION = 'finish'
    CATEGORY = 'Zura/Dialogue'
    OUTPUT_NODE = True

    def finish(self, edit, generated_frames, generated_audio, generated_word_start, generated_word_end,
               audio_fade_ms, mouth_feather, filename_prefix, temporal_resampling='nearest', timing_mode='source'):
        path=local_path(edit['source']);meta=inspect(path)
        if meta['identity'] != edit['identity']: raise ValueError('Source changed after preparation. Run the source stage again.')
        fps=meta['fps'];start,end=edit['word_start'],edit['word_end'];rate=48000
        requested_range=[generated_word_start,generated_word_end]
        generated_word_start,generated_word_end=resolve_timing(edit,generated_word_start,generated_word_end,timing_mode)
        validate_generated(edit,generated_frames.shape,generated_word_start,generated_word_end)
        if temporal_resampling not in ('nearest','blend'):
            raise ValueError('Choose nearest or blend temporal resampling.')
        output_root=Path(folder_paths.get_output_directory()).resolve()
        # Resolve the prefix before writing anything, including symlink targets.
        prefix=(output_root/filename_prefix).resolve()
        if not prefix.is_relative_to(output_root):raise ValueError('Keep the filename prefix inside ComfyUI output.')
        if any(':' in part for part in prefix.parts[1:]):raise ValueError('Use a filename prefix without colons.')
        prefix.parent.mkdir(parents=True,exist_ok=True)
        base=prefix.parent/(prefix.name+'_'+uuid.uuid4().hex[:10]); final=Path(str(base)+'.mp4')
        generated=generated_frames.detach().cpu().numpy()
        if not all(np.isfinite(frame).all() for frame in generated):
            raise ValueError('Generated frames contain invalid pixels. Rerun the generation with another seed.')
        generated=np.clip(generated,0,1)
        audio_tensor=generated_audio['waveform'][0].detach().cpu().float()
        if audio_tensor.shape[0]==1:audio_tensor=audio_tensor.repeat(2,1)
        raw=audio_tensor[:2].T.numpy().copy()
        if generated_audio['sample_rate']!=rate:
            raw=np.frombuffer(ffmpeg('-f','f32le','-ar',generated_audio['sample_rate'],'-ac',2,'-i','pipe:0','-ar',rate,'-f','f32le','pipe:1',data=raw.tobytes()),np.float32).reshape(-1,2).copy()
        original_audio=read_audio(path)
        target_samples=round(meta['frames']/fps*rate)
        original_audio=np.pad(original_audio[:target_samples],((0,max(0,target_samples-len(original_audio))),(0,0)))
        soundtrack,gain=blend_audio(original_audio,raw,start,end,generated_word_start,generated_word_end,audio_fade_ms,rate,allow_retime=False)
        pcm=Path(str(base)+'.wav')
        ffmpeg('-f','f32le','-ar',rate,'-ac',2,'-i','pipe:0','-c:a','pcm_f32le',pcm,data=soundtrack.tobytes())
        generated_pcm=base.parent/(base.name+'_generated.wav')
        ffmpeg('-f','f32le','-ar',rate,'-ac',2,'-i','pipe:0','-c:a','pcm_f32le',generated_pcm,data=raw.tobytes())
        generated_video=base.parent/(base.name+'_generated.mp4')
        gh,gw=generated.shape[1:3]
        ffmpeg('-f','rawvideo','-pix_fmt','rgb24','-s',f'{gw}x{gh}','-r',fps,'-i','pipe:0',
               '-i',generated_pcm,'-c:v','libx264','-preset','fast','-crf',16,'-pix_fmt','yuv420p',
               '-c:a','aac','-b:a','256k','-movflags','+faststart',generated_video,
               data=np.round(generated*255).astype(np.uint8).tobytes())
        x,y,w,h=edit['box'];w,h=round(w),round(h)
        yy,xx=np.mgrid[:h,:w].astype(np.float32);track=np.array(edit['centres']);origins=np.array(edit['origins'])
        cap=cv2.VideoCapture(str(path));changed=[]
        command=[shutil.which('ffmpeg'),'-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f"{meta['width']}x{meta['height']}",'-r',str(fps),'-i','pipe:0','-i',str(pcm),'-map','0:v','-map','1:a','-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-t',str(meta['duration']),'-movflags','+faststart',str(final)]
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            for i in range(meta['frames']):
                ok,frame=cap.read()
                if not ok: raise ValueError('Source decoding stopped before the last frame.')
                t=(i+.5)/fps
                if start<=t<end:
                    tg=generated_word_start+(t-start)
                    j=max(0,min(len(generated)-1,tg*fps-.5));j0=int(j);mix=j-j0
                    g=(generated[min(round(j),len(generated)-1)] if temporal_resampling=='nearest'
                       else (1-mix)*generated[j0]+mix*generated[min(j0+1,len(generated)-1)])
                    # Integrate the supersampled face once; avoid cubic ringing on reduction.
                    interpolation=cv2.INTER_AREA if generated.shape[2]>=w and generated.shape[1]>=h else cv2.INTER_CUBIC
                    g=cv2.cvtColor(cv2.resize(g,(w,h),interpolation=interpolation),cv2.COLOR_RGB2BGR)*255
                    local=i-edit['first'];jg=np.clip(round(j) if temporal_resampling=='nearest' else j,0,len(track)-1)
                    source_centre=track[local];gen_centre=np.array([np.interp(jg,np.arange(len(track)),track[:,k]-origins[:,k]) for k in (0,1)])
                    left,top=np.round(origins[local]).astype(int);desired=source_centre-[left,top];delta=desired-gen_centre
                    g=cv2.warpAffine(g,np.array([[1,0,delta[0]],[0,1,delta[1]]],np.float32),(w,h),borderMode=cv2.BORDER_REPLICATE)
                    rx,ry=edit['mouth'][2:];d=np.sqrt(((xx-desired[0])/rx)**2+((yy-desired[1])/ry)**2)
                    temporal=max(0,min(1,(t-start)*fps/.75,(end-t)*fps/.75))
                    mask=(np.clip((1-d)/mouth_feather,0,1)*temporal)[...,None]
                    region=frame[top:top+h,left:left+w];region[:]=np.round(g*mask+region*(1-mask)).clip(0,255).astype(np.uint8);changed.append(i)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close();error=proc.stderr.read();code=proc.wait()
            if code:raise RuntimeError(error.decode(errors='replace')[-2000:])
        finally:
            cap.release()
            if proc.poll() is None:proc.kill();proc.wait()
        verified=verify_export(final,meta)
        receipt=dict(source_word=[start,end],generated_word=[generated_word_start,generated_word_end],
                     requested_generated_word=requested_range,timing_mode=timing_mode,retimed=False,
                     changed_frames=changed,audio_gain_db=20*math.log10(max(gain,1e-8)),fps=fps,frames=meta['frames'],
                     generated_geometry=edit.get('generation'),crop_mode=edit.get('crop_mode'),
                     temporal_resampling=temporal_resampling,export_verified=verified,audio_samples=target_samples,
                     original_samples_preserved_outside_word=True,source_identity=meta['identity'],
                     note='Pixels outside selected frames and mouth mask are preserved before H264 encoding. PCM audio preserves samples outside the word; AAC is lossy.')
        Path(str(base)+'.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        relative=lambda p:str(p.relative_to(output_root)).replace('\\','/')+' [output]'
        ui={'file':relative(final),'generated_video':relative(generated_video),'generated_audio':relative(generated_pcm),'duration':len(raw)/rate,'peaks':peaks(raw),
            'source_range':[start,end],'generated_range':[generated_word_start,generated_word_end],'context_offset':edit['first']/fps,'timing_mode':timing_mode,'retimed':False}
        return {'ui':{'zura_dialogue':[ui]},'result':(InputImpl.VideoFromFile(str(final)),)}


def register_routes(server):
    @server.routes.post('/zura/dialogue/info')
    async def info(request):
        require_same_origin(request);data=await request.json()
        try:
            path=local_path(data['source'])
            def collect():
                meta=inspect(path);meta['peaks']=peaks(read_audio(path));return meta
            return web.json_response(await asyncio.to_thread(collect))
        except (ValueError,KeyError,subprocess.CalledProcessError) as exc:
            return web.json_response({'error':str(exc)},status=400)

    @server.routes.get('/zura/dialogue/media')
    async def media(request):
        require_same_origin(request)
        try:path=local_path(request.query['source'])
        except (ValueError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))
        return web.FileResponse(path)


NODE_CLASS_MAPPINGS={'ZuraDialogueSource':ZuraDialogueSource,'ZuraDialogueFinish':ZuraDialogueFinish}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraDialogueSource':'Zura · Select Words and Face','ZuraDialogueFinish':'Zura · Blend Selected Word'}
