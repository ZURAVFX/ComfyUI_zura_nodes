"""Local word-level audio editing around the existing isolated LongCat node."""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

import numpy as np
import soundfile as sf
import torch
from aiohttp import web
import folder_paths

from .longcat import ZuraLongCatVoice, runtime_config
from .media_source import local_path, require_same_origin

DEMUX = ['-protocol_whitelist', 'file,pipe', '-format_whitelist',
         'wav,mp3,flac,ogg,aac,mov,matroska,webm,avi,aiff,asf,mpeg,mpegvideo']


def command(name, args, data=None):
    exe = shutil.which(name)
    if not exe:
        raise RuntimeError(f'Install {name} and add it to PATH, then restart ComfyUI.')
    return subprocess.run([exe, '-v', 'error', *args], input=data, capture_output=True,
                          check=True, timeout=180, **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {})).stdout


def identity(path):
    s = path.stat()
    return hashlib.sha256(f'{path}:{s.st_size}:{s.st_mtime_ns}'.encode()).hexdigest()


def decode(path):
    meta = json.loads(command('ffprobe', [*DEMUX, '-select_streams', 'a:0', '-show_streams', '-of', 'json', str(path)]))['streams']
    if not meta:
        raise ValueError('This file has no audio stream.')
    rate, channels = int(meta[0]['sample_rate']), int(meta[0]['channels'])
    if not 8000 <= rate <= 192000 or not 1 <= channels <= 8:
        raise ValueError('Use audio with 1–8 channels and a sample rate between 8 and 192 kHz.')
    duration = float(meta[0].get('duration', 0) or 0)
    if duration > 1800:
        raise ValueError('Choose an excerpt under 30 minutes for the interactive editor.')
    raw = command('ffmpeg', [*DEMUX, '-i', str(path), '-map', '0:a:0', '-t', '1801', '-f', 'f32le', '-acodec', 'pcm_f32le', 'pipe:1'])
    audio = np.frombuffer(raw, np.float32).reshape(-1, channels).copy()
    if not len(audio) or len(audio) > rate * 1800 or not np.isfinite(audio).all():
        raise ValueError('Choose a nonempty, finite audio excerpt under 30 minutes.')
    return audio, rate


def peaks(audio, bins=1600):
    mono = np.max(np.abs(audio), axis=1)
    return [float(np.max(p)) if len(p) else 0 for p in np.array_split(mono, min(bins, len(mono)))]


def bounds(start, end, length, rate, label):
    # ComfyUI's millisecond controls may round the final sample upwards.
    # Accept only that half-millisecond discrepancy and snap it to the file end.
    tolerance = max(.0005, .5 / rate) + 1e-12
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end <= length / rate + tolerance:
        raise ValueError(f'Keep {label} IN and OUT inside the audio, with OUT after IN.')
    a,b=round(start * rate),min(length, round(end * rate))
    if b<=a:raise ValueError(f'Select at least one audio sample for {label}.')
    return a,b


def convert(audio, old_rate, new_rate, channels):
    if audio.ndim != 2 or not np.isfinite(audio).all() or len(audio) == 0:
        raise ValueError('The generated audio is empty or contains invalid samples.')
    if audio.shape[1] != channels:
        audio = np.repeat(audio.mean(axis=1, keepdims=True), channels, axis=1)
    if old_rate != new_rate:
        raw = command('ffmpeg', ['-f', 'f32le', '-ar', str(old_rate), '-ac', str(channels), '-i', 'pipe:0',
                                 '-ar', str(new_rate), '-f', 'f32le', 'pipe:1'], audio.astype(np.float32).tobytes())
        audio = np.frombuffer(raw, np.float32).reshape(-1, channels).copy()
    return audio


def splice(original, generated, rate, start, end, gen_start, gen_end, fade_ms, timing):
    a, b = bounds(start, end, len(original), rate, 'source selection')
    c, d = bounds(gen_start, gen_end, len(generated), rate, 'replacement selection')
    take = generated[c:d].copy()
    ratio = len(take) / (b - a)
    if timing == 'Keep timing (up to 15% fit)':
        if not .85 <= ratio <= 1.15:
            raise ValueError(f'The selected take is {ratio:.2f}× the source duration. Adjust its handles, change LongCat pace, or explicitly choose Natural duration. No large time stretch was applied.')
        if len(take) != b - a:
            raw = command('ffmpeg', ['-f', 'f32le', '-ar', str(rate), '-ac', str(take.shape[1]), '-i', 'pipe:0',
                '-af', f'atempo={ratio:.10f},apad', '-t', f'{(b-a)/rate:.12f}', '-f', 'f32le', 'pipe:1'], take.astype(np.float32).tobytes())
            take = np.frombuffer(raw, np.float32).reshape(-1, take.shape[1]).copy()[:b-a]
            if len(take) < b-a:
                take = np.pad(take, ((0,b-a-len(take)),(0,0)))
    elif timing != 'Natural duration (no stretch)':
        raise ValueError('Choose a timing mode.')
    # Match voice level locally. Bound gain and avoid introducing hard clipping.
    old_rms = float(np.sqrt(np.mean(original[a:b].astype(np.float64)**2)))
    new_rms = float(np.sqrt(np.mean(take.astype(np.float64)**2)))
    gain = np.clip(old_rms / max(new_rms, 1e-9), .25, 4.0) if old_rms > 1e-5 else 1.0
    gain = min(float(gain), .999 / max(float(np.abs(take).max()), 1e-9))
    take *= gain
    n = min(round(rate * fade_ms / 1000), len(take)//2, (b-a)//2)
    if n:
        ramp = np.sin(np.linspace(0, np.pi/2, n))[:,None]**2
        take[:n] = original[a:a+n] * (1-ramp) + take[:n]*ramp
        take[-n:] = take[-n:]*(1-ramp) + original[b-n:b]*ramp
    result = np.concatenate((original[:a], take, original[b:]))
    assert np.array_equal(result[:a], original[:a])
    assert np.array_equal(result[a+len(take):], original[b:])
    return result, {'source_samples':[a,b], 'replacement_samples':[c,d], 'output_replacement_samples':len(take),
                    'timing':timing, 'duration_ratio':ratio, 'level_gain':gain, 'fade_ms':fade_ms,
                    'outside_selection_unchanged':True, 'time_stretched':timing.startswith('Keep') and len(generated[c:d]) != b-a}


def parakeet_config():
    config = Path(os.environ.get('ZURA_PARAKEET_CONFIG', str(Path(__file__).with_name('parakeet.local.json'))))
    if config.is_file():
        data = json.loads(config.read_text(encoding='utf-8-sig'))
        return str(Path(data['python']).expanduser()), str(Path(data['models']).expanduser())
    local = Path.home() / 'AppData' / 'Local' if os.name == 'nt' else Path.home()
    root = Path(os.environ.get('LOCALAPPDATA') or local) / 'ParakeetRuntime'
    python = root / 'Scripts' / 'python.exe'
    if python.is_file() and (root/'models'/'parakeet-tdt-0.6b-v3-int8').is_dir():
        return str(python), str(root/'models')
    raise RuntimeError('Parakeet is optional. Configure parakeet.local.json (python and models), or select Manual IN/OUT and edit the waveform directly. No models are downloaded automatically.')


def transcribe(path):
    python, models = parakeet_config()
    cache = Path(folder_paths.get_temp_directory()) / 'zura_audio_words'
    cache.mkdir(parents=True, exist_ok=True)
    digest=hashlib.sha256(json.dumps([python,models,'word-timestamps-v1']).encode())
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    target = cache / (digest.hexdigest()+'.json')
    if target.is_file():
        return json.loads(target.read_text(encoding='utf-8'))
    env = {k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH','PYTHONEXECUTABLE','__PYVENV_LAUNCHER__','VIRTUAL_ENV','CONDA_PREFIX','CONDA_DEFAULT_ENV')}
    env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    try:
        process = subprocess.run([python, str(Path(__file__).with_name('audio_parakeet.py')), '--input', str(path),
            '--models', models, '--output', str(target)], capture_output=True, text=True, env=env, timeout=300,
            cwd=str(Path(__file__).resolve().parent),
            **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
    except OSError as error:
        raise RuntimeError(f'Cannot start the installed Parakeet Python ({python}): {error}') from error
    if process.returncode or not target.is_file():
        raise RuntimeError('Parakeet could not read this take: '+process.stderr[-1200:])
    return json.loads(target.read_text(encoding='utf-8'))


def normal(text):
    value = re.sub(r'[^\w]', '', text.lower())
    return {'0':'zero','1':'one','2':'two','3':'three','4':'four','5':'five','6':'six','7':'seven','8':'eight','9':'nine'}.get(value,value)


def changed_range(original, script, words):
    before, after = [normal(w) for w in original.split()], [normal(w) for w in script.split()]
    edits = [op for op in difflib.SequenceMatcher(a=before,b=after,autojunk=False).get_opcodes() if op[0]!='equal']
    if len(edits)!=1 or edits[0][3]==edits[0][4]:
        raise ValueError('Auto selection needs one continuous replacement phrase. Choose Manual IN/OUT for several edits or deletions.')
    _,_,_,a,b=edits[0]
    tokens=[normal(w['text']) for w in words]
    matches=[i for i in range(len(tokens)-(b-a)+1) if tokens[i:i+b-a]==after[a:b]]
    if len(matches)!=1:
        raise ValueError('The changed words were not recognised unambiguously. Listen to the take and choose Manual IN/OUT.')
    i=matches[0]
    return float(words[i]['start']),float(words[i+b-a-1]['end'])


class ZuraAudioDialogueSource:
    CATEGORY='Zura/audio editing'
    FUNCTION='prepare'
    RETURN_TYPES=('AUDIO','STRING','ZURA_AUDIO_EDIT')
    RETURN_NAMES=('speaker_reference','reference_transcript','edit')

    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'source':('STRING',{'default':''}),
            'source_transcript':('STRING',{'multiline':True,'default':''}),
            'word_start':('FLOAT',{'default':0.,'min':0.,'step':.001}),
            'word_end':('FLOAT',{'default':.5,'min':0.,'step':.001}),
            'reference_start':('FLOAT',{'default':0.,'min':0.,'step':.001}),
            'reference_end':('FLOAT',{'default':0.,'min':0.,'step':.001}),
            'extra_reference':('STRING',{'default':''}),
            'extra_transcript':('STRING',{'multiline':True,'default':''}),
            'reference_mode':(['Source and extra reference','Extra reference only'],),
        },'optional':{'source_reference_transcript':('STRING',{'multiline':True,'default':''})}}

    @classmethod
    def IS_CHANGED(cls, source='', extra_reference='', **kwargs):
        return '|'.join(identity(local_path(p)) for p in (source,extra_reference) if p.strip())

    def prepare(self,source,source_transcript,word_start,word_end,reference_start,reference_end,extra_reference,extra_transcript,reference_mode,source_reference_transcript=''):
        path=local_path(source); audio,rate=decode(path)
        bounds(word_start,word_end,len(audio),rate,'source selection')
        refs=[];texts=[]
        if reference_mode=='Source and extra reference':
            end=reference_end or len(audio)/rate
            a,b=bounds(reference_start,end,len(audio),rate,'speaker reference')
            trimmed=a!=0 or b!=len(audio)
            transcript=source_reference_transcript.strip() if trimmed else source_transcript.strip()
            if not transcript:
                if trimmed:raise ValueError('Enter the exact words in the trimmed source reference. Keep the full source transcript for word selection.')
                raise ValueError('Enter the exact words in the source reference, or use Transcribe with Parakeet.')
            refs.append(convert(audio[a:b],rate,24000,1));texts.append(transcript)
        if extra_reference.strip():
            if not extra_transcript.strip():
                raise ValueError('Enter the exact words in the additional reference.')
            extra,extra_rate=decode(local_path(extra_reference))
            refs.append(convert(extra,extra_rate,24000,1));texts.append(extra_transcript.strip())
        if not refs:
            raise ValueError('Choose a speaker reference.')
        reference=np.concatenate([part for i,ref in enumerate(refs) for part in ((np.zeros((3600,1),np.float32),ref) if i else (ref,))])
        if len(reference)/24000 > 25:
            raise ValueError('Keep the combined speaker reference under 25 seconds. Trim the reference range or supply a shorter extra clip.')
        edit={'source':str(path),'identity':identity(path),'rate':rate,'channels':audio.shape[1],
              'samples':len(audio),'word_start':word_start,'word_end':word_end,'source_transcript':source_transcript,
              'reference_seconds':len(reference)/24000}
        return ({'waveform':torch.from_numpy(reference.T.copy())[None],'sample_rate':24000},' '.join(texts),edit)


class ZuraLongCatDialogueVoice(ZuraLongCatVoice):
    DESCRIPTION='The existing LongCat voice node with retained take caching. Changing edit handles reuses the take. Change seed for a new performance.'

    @classmethod
    def INPUT_TYPES(cls):
        parent=super().INPUT_TYPES()
        required={'reference_audio':parent['optional']['reference_audio'],
                  'reference_transcript':('STRING',{'forceInput':True})}
        required.update({k:v for k,v in parent['required'].items() if k!='reference_transcript'})
        return {'required':required}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        config=runtime_config()
        return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

    def generate(self,mode,script,reference_transcript,pace,seed,project,reference_audio=None):
        config=runtime_config()
        key=hashlib.sha256(json.dumps([mode,script,reference_transcript,pace,seed,project,config],sort_keys=True).encode())
        if reference_audio is not None:
            key.update(str(reference_audio['sample_rate']).encode())
            key.update(reference_audio['waveform'].detach().float().cpu().numpy().tobytes())
        cache=Path(folder_paths.get_output_directory())/'zura_voice'/'dialogue_cache'
        cache.mkdir(parents=True,exist_ok=True);index=cache/(key.hexdigest()+'.json')
        if index.is_file():
            try:
                report=json.loads(index.read_text(encoding='utf-8'))
                path=local_path(report['wav'])
                audio,rate=sf.read(path,dtype='float32',always_2d=True)
                if not len(audio) or not np.isfinite(audio).all():raise ValueError('Invalid cached take')
                return ({'waveform':torch.from_numpy(audio.T.copy())[None],'sample_rate':rate},json.dumps(report))
            except (ValueError,OSError,KeyError):
                pass
        result=super().generate(mode,script,reference_transcript,pace,seed,project,reference_audio)
        pending=index.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        pending.write_text(result[1],encoding='utf-8');pending.replace(index)
        return result


class ZuraAudioDialogueTake:
    CATEGORY='Zura/audio editing'
    FUNCTION='attach'
    RETURN_TYPES=('AUDIO','ZURA_AUDIO_EDIT')
    RETURN_NAMES=('generated_audio','edit')
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'audio':('AUDIO',),'run_report':('STRING',{'forceInput':True}),'edit':('ZURA_AUDIO_EDIT',)}}
    def attach(self,audio,run_report,edit):
        report=json.loads(run_report)
        return audio,{**edit,'take':report}


class ZuraAudioDialogueSelect:
    CATEGORY='Zura/audio editing'
    FUNCTION='select'
    RETURN_TYPES=('AUDIO','ZURA_AUDIO_EDIT')
    RETURN_NAMES=('replacement_take','selected_edit')
    DESCRIPTION='Choose words in the generated take. Press Run again to apply a changed selection; the unchanged LongCat take is reused.'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'generated_audio':('AUDIO',),'edit':('ZURA_AUDIO_EDIT',),
            'selection_mode':(['Auto changed words','Manual IN/OUT'],),
            'generated_start':('FLOAT',{'default':0.,'min':0.,'step':.001}),
            'generated_end':('FLOAT',{'default':.5,'min':0.,'step':.001}),
            'original_start':('FLOAT',{'default':-1.,'min':-1.,'step':.001}),
            'original_end':('FLOAT',{'default':-1.,'min':-1.,'step':.001}),
        }}

    def select(self,generated_audio,edit,selection_mode,generated_start,generated_end,original_start=-1.,original_end=-1.):
        source=local_path(edit['source'])
        if identity(source)!=edit['identity']:raise ValueError('The source changed. Load its waveform again.')
        original,source_rate=decode(source)
        source_selection=[edit['word_start'] if original_start<0 else original_start,
                          edit['word_end'] if original_end<0 else original_end]
        source_a,source_b=bounds(*source_selection,len(original),source_rate,'Original')
        source_selection=[source_a/source_rate,source_b/source_rate]
        wav=generated_audio['waveform']
        if wav.ndim!=3 or wav.shape[0]!=1 or not wav.shape[-1]:raise ValueError('Use one nonempty generated take.')
        audio=wav[0].detach().float().cpu().numpy().T
        if not np.isfinite(audio).all():raise ValueError('The generated take contains invalid samples.')
        rate=int(generated_audio['sample_rate'])
        if rate<=0:raise ValueError('The generated take needs a valid sample rate.')
        digest=hashlib.sha256(json.dumps([rate,list(audio.shape)]).encode()+audio.tobytes()).hexdigest()
        directory=Path(folder_paths.get_output_directory())/'zura_voice'/'dialogue_takes'/digest
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/'replacement_take.wav'
        if not path.is_file():sf.write(path,audio,rate,subtype='FLOAT')
        words=[];source_words=[];notice='';selection=[generated_start,generated_end]
        try:source_words=transcribe(source)
        except (ValueError,RuntimeError):pass
        try:
            words=transcribe(path)
            if selection_mode=='Auto changed words':selection=list(changed_range(edit['source_transcript'],edit['take']['script'],words))
        except (ValueError,RuntimeError,KeyError) as error:
            if selection_mode=='Auto changed words':notice=str(error)
        if not notice:
            gen_a,gen_b=bounds(*selection,len(audio),rate,'Replacement')
            selection=[gen_a/rate,gen_b/rate]
        selected={**edit,'word_start':source_selection[0],'word_end':source_selection[1],
                  'generated_selection':selection,'selection_error':notice}
        preview={'take':str(path),'take_duration':len(audio)/rate,'take_peaks':peaks(audio),
                 'words':words,'selection':selection,'status':'Select replacement words' if notice else 'Selection ready',
                 'notice':notice,'source':str(source),'source_duration':len(original)/source_rate,
                 'source_peaks':peaks(original),'source_words':source_words,'source_selection':source_selection}
        return {'ui':{'zura_audio_dialogue':[preview]},'result':(generated_audio,selected)}


class ZuraAudioDialogueFinish:
    CATEGORY='Zura/audio editing'
    FUNCTION='finish'
    RETURN_TYPES=('AUDIO','STRING')
    RETURN_NAMES=('finished_audio','receipt')
    OUTPUT_NODE=True
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'generated_audio':('AUDIO',),'edit':('ZURA_AUDIO_EDIT',),
            'selection_mode':(['Auto changed words','Manual IN/OUT'],),
            'generated_start':('FLOAT',{'default':0.,'min':0.,'step':.001}),
            'generated_end':('FLOAT',{'default':.5,'min':0.,'step':.001}),
            'timing':(['Natural duration (no stretch)','Keep timing (up to 15% fit)'],),
            'fade_ms':('FLOAT',{'default':12.,'min':0.,'max':100.,'step':1.}),
            'project':('STRING',{'default':'Dialogue_Edit'}),
        }}

    def finish(self,generated_audio,edit,selection_mode,generated_start,generated_end,timing,fade_ms,project):
        path=local_path(edit['source'])
        if identity(path)!=edit['identity']:raise ValueError('The source changed. Select the words again.')
        original,rate=decode(path)
        wav=generated_audio['waveform']
        if wav.ndim!=3 or wav.shape[0]!=1:raise ValueError('Use one generated take.')
        generated=convert(wav[0].detach().float().cpu().numpy().T,int(generated_audio['sample_rate']),rate,original.shape[1])
        from .longcat import project_directory
        directory=project_directory(project)
        takefile=directory/'replacement_take.wav';sf.write(takefile,generated,rate,subtype='FLOAT')
        words=[];notice='';selection=[generated_start,generated_end]
        if selection_mode=='Auto changed words':
            try:
                words=transcribe(takefile)
                report=edit['take']
                selection=list(changed_range(edit['source_transcript'],report['script'],words))
            except (ValueError,RuntimeError,KeyError) as error:
                notice=str(error)
        if notice:
            result=original.copy();receipt={'status':'Select replacement words','notice':notice,'source_unchanged':True}
        else:
            result,receipt=splice(original,generated,rate,edit['word_start'],edit['word_end'],*selection,fade_ms,timing)
            receipt.update(status='Blended',source=edit['source'],reference_seconds=edit['reference_seconds'])
        final=directory/'dialogue_edit.wav';sf.write(final,result,rate,subtype='FLOAT')
        readback,sr=sf.read(final,dtype='float32',always_2d=True)
        if sr!=rate or not np.array_equal(readback,result):raise RuntimeError('The WAV verification failed.')
        receipt.update(sample_rate=rate,channels=result.shape[1],samples=len(result),generated_selection=selection)
        (directory/'edit_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        preview={'file':str(final),'take':str(takefile),'duration':len(result)/rate,'take_duration':len(generated)/rate,
                 'peaks':peaks(result),'take_peaks':peaks(generated),'words':words,'selection':selection,'status':receipt['status'],'notice':notice}
        if not notice:
            preview['output_selection']=[edit['word_start'],edit['word_start']+receipt['output_replacement_samples']/rate]
        return {'ui':{'zura_audio_dialogue':[preview]},'result':({'waveform':torch.from_numpy(result.T.copy())[None],'sample_rate':rate},json.dumps(receipt))}


class ZuraAudioDialogueOutput(ZuraAudioDialogueFinish):
    DESCRIPTION='Run to blend the selected words into the original audio, then listen and download here. Selection or blend changes reuse the unchanged LongCat take.'

    @classmethod
    def INPUT_TYPES(cls):
        inputs=super().INPUT_TYPES()['required']
        return {'required':{k:v for k,v in inputs.items() if k not in ('selection_mode','generated_start','generated_end')}}

    def finish(self,generated_audio,edit,timing,fade_ms,project):
        if edit.get('selection_error'):
            raise ValueError('Select replacement words on the waveform, then press Run. '+edit['selection_error'])
        if 'generated_selection' not in edit:raise ValueError('Connect Select Replacement Words before Final Audio.')
        start,end=edit['generated_selection']
        return super().finish(generated_audio,edit,'Manual IN/OUT',start,end,timing,fade_ms,project)


def register_routes(server):
    @server.routes.post('/zura/audio-dialogue/info')
    async def info(request):
        require_same_origin(request)
        try:
            data=await request.json();path=local_path(data['source'])
            audio,rate=await asyncio.to_thread(decode,path)
            return web.json_response({'duration':len(audio)/rate,'sample_rate':rate,'channels':audio.shape[1],
                                      'identity':identity(path),'peaks':peaks(audio)})
        except Exception as error:return web.json_response({'error':str(error)},status=400)
    @server.routes.get('/zura/audio-dialogue/media')
    async def media(request):
        require_same_origin(request)
        try:return web.FileResponse(local_path(request.query['source']))
        except Exception as error:raise web.HTTPBadRequest(text=str(error))
    @server.routes.post('/zura/audio-dialogue/transcribe')
    async def words(request):
        require_same_origin(request)
        try:
            data=await request.json();path=local_path(data['source'])
            return web.json_response({'words':await asyncio.to_thread(transcribe,path)})
        except Exception as error:return web.json_response({'error':str(error)},status=400)


NODE_CLASS_MAPPINGS={c.__name__:c for c in (ZuraAudioDialogueSource,ZuraLongCatDialogueVoice,ZuraAudioDialogueTake,ZuraAudioDialogueSelect,ZuraAudioDialogueFinish,ZuraAudioDialogueOutput)}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraAudioDialogueSource':'Zura · Select Audio Words',
    'ZuraLongCatDialogueVoice':'Zura · LongCat Retained Take','ZuraAudioDialogueTake':'Zura · Attach Audio Take',
    'ZuraAudioDialogueSelect':'Zura · Select Replacement Words',
    'ZuraAudioDialogueOutput':'Zura · Final Audio',
    'ZuraAudioDialogueFinish':'Zura · Blend Audio Words (combined editor)'}
