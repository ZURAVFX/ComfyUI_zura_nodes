"""ProRes 4444 working-RGB delivery. No display, HLG, gamma or gamut transform."""
from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

import numpy as np


def inspect_prores4444(path):
    import av
    with av.open(str(path)) as container:
        if len(container.streams.video)!=1:raise ValueError('Expected one ProRes 4444 video stream.')
        codec=container.streams.video[0].codec_context
        if codec.name!='prores' or codec.codec_tag not in ('ap4h','ap4x') or '444' not in codec.format.name:
            raise ValueError('The movie is not ProRes 4444.')
        if codec.color_trc==18:raise ValueError('Working RGB delivery must not be tagged as HLG.')
        return {'codec':'prores4444','pixelFormat':codec.format.name}


def write_prores4444(frames, destination, *, width, height, count, fps,
                    source_space='acescg', audio=None, audio_source=None,
                    audio_start=0., audio_duration=None, cancelled=None,
                    progress=None, executable=None, channels=3):
    from .model_downloads import _publish_verified
    if source_space not in ('acescg','acescct','linear_rec709','srgb_display'):
        raise ValueError('Choose the working RGB space for ProRes delivery.')
    if channels not in (3,4):raise ValueError('ProRes delivery needs RGB or RGBA frames.')
    rate=Fraction(str(fps)).limit_denominator(1_000_000)
    if not 1<=rate<=120 or min(width,height,count)<1:raise ValueError('Invalid ProRes dimensions or frame range.')
    executable=executable or shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is required for ProRes 4444 delivery.')
    destination=Path(destination)
    if destination.suffix.lower()!='.mov' or destination.exists():raise ValueError('Choose a new MOV destination.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    duration=float(Fraction(count,1)/rate)
    with tempfile.TemporaryDirectory(prefix='.zura-prores-',dir=destination.parent) as temporary:
        temporary=Path(temporary);output=temporary/'master.mov'
        command=[str(executable),'-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgba64le' if channels==4 else 'rgb48le',
                 '-video_size',f'{width}x{height}','-framerate',f'{rate.numerator}/{rate.denominator}','-i','pipe:0']
        if audio is not None:
            waveform=audio['waveform'];samples=waveform.detach().cpu().numpy() if hasattr(waveform,'detach') else np.asarray(waveform)
            if samples.ndim==3:samples=samples[0]
            if samples.ndim!=2 or not np.isfinite(samples).all():raise ValueError('Invalid source audio.')
            pcm=(np.clip(samples.T,-1,1)*2147483647).round().astype('<i4')
            wav=temporary/'source.wav'
            with wave.open(str(wav),'wb') as target:
                target.setnchannels(samples.shape[0]);target.setsampwidth(4);target.setframerate(int(audio['sample_rate']));target.writeframes(pcm.tobytes())
            audio_source=wav;audio_start=0.
        if audio_source is not None:
            held=duration if audio_duration is None else float(audio_duration)
            command+=['-ss',str(float(audio_start)),'-i',str(audio_source),'-map','0:v:0','-map','1:a:0',
                      '-af',f'atrim=duration={held:.9f},apad=whole_dur={duration:.9f},atrim=duration={duration:.9f}',
                      '-c:a','pcm_s24le']
        else:command+=['-map','0:v:0','-an']
        # The YCbCr matrix is a reversible codec representation, not a creative
        # gamut conversion. Do not label ACES working samples as Rec.2020 HLG.
        command+=['-frames:v',str(count),'-t',str(duration),'-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709',
                  '-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le' if channels==4 else 'yuv444p10le','-alpha_bits','16','-vendor','apl0','-tag:v','ap4h',
                  '-color_range','tv','-colorspace','bt709','-color_primaries','unspecified','-color_trc','unspecified',
                  '-video_track_timescale',str(rate.numerator),'-metadata','comment=Zura working RGB: '+source_space,
                  '-movflags','+faststart+write_colr','-f','mov',str(output)]
        clipped=0;written=0
        with (temporary/'encode.log').open('wb') as log:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
            try:
                for frame in frames:
                    if cancelled and cancelled():raise ValueError('ProRes export cancelled.')
                    pixels=frame.detach().float().cpu().numpy() if hasattr(frame,'detach') else np.asarray(frame)
                    if pixels.shape!=(height,width,channels) or not np.isfinite(pixels).all():raise ValueError('Invalid working RGB frame.')
                    clipped+=int(np.count_nonzero((pixels<0)|(pixels>1)))
                    process.stdin.write(np.ascontiguousarray(np.rint(np.clip(pixels,0,1)*65535).astype('<u2')).tobytes())
                    written+=1
                    if written>count:raise ValueError('Too many frames for the ProRes range.')
                    if progress:progress(written,count)
                if written!=count:raise ValueError('Incomplete ProRes frame range.')
                process.stdin.close();process.stdin=None
                if process.wait(timeout=120):raise ValueError('FFmpeg could not encode ProRes 4444.')
            finally:
                if process.poll() is None:process.kill();process.wait()
                if process.stdin is not None:
                    try:process.stdin.close()
                    except OSError:pass
        if cancelled and cancelled():raise ValueError('ProRes export cancelled.')
        _publish_verified(output,destination)
    # Float values outside the codec's representable interval stay in EXR.
    destination.with_suffix('.mov.json').write_text(json.dumps({'schemaVersion':1,'codec':'prores4444',
        'colour':{'encoding':source_space,'sceneLinear':source_space in ('acescg','linear_rec709')},
        'samplePolicy':'working_rgb_no_transfer_or_gamut_transform','clippedSamples':clipped,
        'frameRate':{'numerator':rate.numerator,'denominator':rate.denominator}},sort_keys=True),encoding='utf-8')
    return destination


class ZuraHDRSaveProRes4444:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'filename_prefix':('STRING',{'default':'genj/hdr/output'}),
                'fps':('FLOAT',{'default':24.,'min':1.,'max':120.}),'source_space':(['acescg','acescct','linear_rec709','srgb_display'],)},
                'optional':{'audio':('AUDIO',)}}
    RETURN_TYPES=('VIDEO',)
    OUTPUT_NODE=True
    FUNCTION='save'
    CATEGORY='Zura/Artist Studio'
    def save(self,images,filename_prefix,fps,source_space='acescg',audio=None):
        import folder_paths
        from comfy_api.latest import InputImpl
        count,height,width,channels=images.shape
        if channels not in (3,4):raise ValueError('ProRes delivery needs RGB or RGBA frames.')
        folder,name,counter,subfolder,_=folder_paths.get_save_image_path(filename_prefix,folder_paths.get_output_directory(),width,height)
        destination=Path(folder)/f'{name}_{counter:05d}_.mov'
        write_prores4444(images,destination,width=width,height=height,count=count,fps=fps,source_space=source_space,audio=audio,channels=channels)
        ref={'filename':destination.name,'subfolder':subfolder,'type':'output','colour':{'encoding':source_space,'sceneLinear':source_space in ('acescg','linear_rec709')}}
        return {'ui':{'images':[ref],'animated':[True]},'result':(InputImpl.VideoFromFile(str(destination)),)}


class ZuraSaveProRes4444(ZuraHDRSaveProRes4444):
    """Save raw native VIDEO components without an H.264 intermediate."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'video':('VIDEO',),'filename_prefix':('STRING',{'default':'ZURA STUDIO/video/result'})}}
    def save(self,video,filename_prefix,**kwargs):
        components=video.get_components();images=components.images
        if getattr(components,'alpha',None) is not None and images.shape[-1]==3:
            import torch
            alpha=components.alpha
            if alpha.ndim==3:alpha=alpha.unsqueeze(-1)
            images=torch.cat([images,alpha.to(images)],dim=-1)
        result=super().save(images,filename_prefix,float(components.frame_rate),source_space='srgb_display',audio=components.audio)
        import folder_paths
        ref=result['ui']['images'][0];master=Path(folder_paths.get_output_directory())/ref['subfolder']/ref['filename']
        preview=make_sdr_preview(master)
        ref['preview']={'filename':preview.name,'subfolder':ref['subfolder'],'type':'output'}
        return result


def make_sdr_preview(master):
    """A browser copy only; the ProRes file remains the downloadable master."""
    master=Path(master);preview=master.with_name(master.stem+'_preview.mp4')
    if not preview.exists():
        command=[shutil.which('ffmpeg'),'-v','error','-i',str(master),'-map','0:v:0','-map','0:a:0?',
                 '-vf',"scale='min(960,iw)':'min(960,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                 '-c:v','libx264','-crf','20','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(preview)]
        result=subprocess.run(command,capture_output=True,timeout=300)
        if result.returncode:preview.unlink(missing_ok=True);raise ValueError('Could not create the browser video preview. The ProRes master is retained.')
    return preview
