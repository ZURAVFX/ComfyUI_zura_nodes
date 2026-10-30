"""Save HDR video with the source's exact rational frame rate."""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from .model_downloads import _publish_verified


def exact_rate(fps):
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or not 1<=fps<=120:
        raise ValueError('Choose a valid source frame rate.')
    return Fraction(float(fps)).limit_denominator(1_000_000)


def retime_without_reencoding(source, output, fps, *, executable=None):
    """Rebuild CFR timestamps without changing encoded video/audio packets."""
    import av
    rate=exact_rate(fps)
    executable=executable or shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is required to preserve the exact frame rate.')
    source=Path(source);output=Path(output)
    if output.exists():raise ValueError('The temporary HDR output already exists.')
    with av.open(str(source)) as original:
        if not original.streams.video:raise ValueError('The saved HDR video has no video stream.')
        stream=original.streams.video[0]
        frame_count=stream.frames
        colour=(stream.codec_context.color_primaries,stream.codec_context.color_trc,stream.codec_context.colorspace)
        audio_count=len(original.streams.audio)
    result=subprocess.run([str(executable),'-hide_banner','-loglevel','error','-r',f'{rate.numerator}/{rate.denominator}',
        '-i',str(source),'-map','0','-c','copy','-movflags','+faststart',str(output)],capture_output=True)
    if result.returncode:raise ValueError('Could not preserve the source frame rate in the HDR video.')
    with av.open(str(output)) as checked:
        stream=checked.streams.video[0]
        actual=(stream.codec_context.color_primaries,stream.codec_context.color_trc,stream.codec_context.colorspace)
        if stream.average_rate!=rate or (frame_count and stream.frames!=frame_count) or actual!=colour or len(checked.streams.audio)!=audio_count:
            raise ValueError('The exact-rate HDR output did not retain its expected frames, colour tags or audio.')
    return rate


class ZuraHDRSaveExactRate:
    """Comfy-compatible HDR saver; retain source-rate precision beyond 0.001 fps."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'video':('VIDEO',),'filename_prefix':('STRING',{'default':'genj/hdr/output'}),
                            'fps':('FLOAT',{'default':24.,'min':1.,'max':120.})}}
    RETURN_TYPES=('VIDEO',)
    OUTPUT_NODE=True
    FUNCTION='save'
    CATEGORY='Zura/Artist Studio'
    def save(self,video,filename_prefix,fps):
        import folder_paths
        from comfy_api.latest import InputImpl, Types
        exact_rate(fps)
        if not shutil.which('ffmpeg'):raise ValueError('FFmpeg is required to preserve the exact frame rate.')
        width,height=video.get_dimensions()
        folder,name,counter,subfolder,_=folder_paths.get_save_image_path(filename_prefix,folder_paths.get_output_directory(),width,height)
        destination=Path(folder)/f'{name}_{counter:05d}_.mp4'
        with tempfile.TemporaryDirectory(prefix='.zura-hdr-rate-',dir=folder) as temp:
            initial=Path(temp)/'initial.mp4';corrected=Path(temp)/'corrected.mp4'
            video.save_to(str(initial),format=Types.VideoContainer.MP4,codec=Types.VideoCodec.H264)
            retime_without_reencoding(initial,corrected,fps)
            _publish_verified(corrected,destination)
        result={'filename':destination.name,'subfolder':subfolder,'type':'output'}
        return {'ui':{'images':[result],'animated':[True]},'result':(InputImpl.VideoFromFile(str(destination)),)}


NODE_CLASS_MAPPINGS={'ZuraHDRSaveExactRate':ZuraHDRSaveExactRate}
NODE_DISPLAY_NAME_MAPPINGS={'ZuraHDRSaveExactRate':'Zura · Save HDR at Source Frame Rate'}
