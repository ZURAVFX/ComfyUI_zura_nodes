"""Small streaming delivery adapter around ComfyUI's installed HDR/video nodes."""
from pathlib import Path
import io
import subprocess
from fractions import Fraction
import torch
import numpy as np
from .paintout import encode_ct, native_colour, resize, sdr_view

def correct_video_clock(path,fps):
    rate=Fraction(str(fps)).limit_denominator(100000)
    temp=path.with_name(path.stem+'_clock.mp4')
    ticks=rate.denominator;timescale=rate.numerator
    # Native encoded chunks use millisecond clocks. Rebuild the continuous
    # source clock after concatenation, without re-encoding image samples.
    # Packet-count expressions need no prescale option (absent in older FFmpeg).
    expression=f'setts=pts=N*{ticks}/{timescale}/TB:dts=N*{ticks}/{timescale}/TB:duration={ticks}/{timescale}/TB'
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-c:v','copy','-bsf:v',expression,'-video_track_timescale',str(timescale),'-y',str(temp)],check=True,capture_output=True)
    temp.replace(path)

def copy_source_audio(path,plate):
    """Trim original audio to the selected image range; preserve video samples."""
    source=plate.get('source',{})
    if source.get('kind')!='video':return False
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_entries','stream=index','-of','csv=p=0',source['path']],check=True,capture_output=True,text=True)
    if not probe.stdout.strip():return False
    temporary=path.with_name(path.stem+'_audio.mp4')
    start=plate['start']/plate['fps'];duration=plate['count']/plate['fps']
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-ss',str(start),'-i',source['path'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-af','asetpts=PTS-STARTPTS','-t',str(duration),'-movflags','+faststart','-y',str(temporary)],check=True,capture_output=True)
    temporary.replace(path)
    return True

class Delivery:
    def __init__(self,target,plate,format,preview):
        self.target=target;self.plate=plate;self.hdr='HLG' in format;self.sdr='SDR' in format;self.preview=preview
        self.hdr_chunks=[];self.sdr_chunks=[];self.preview_chunks=[];self.pending=[]

    def append(self,linear):
        if not(self.hdr or self.sdr or self.preview):return
        self.pending.append(linear)
        # Full-size frames never accumulate over the entire shot in RAM.
        if len(self.pending)>=4:self.flush()

    def flush(self):
        if not self.pending:return
        from comfy_extras.nodes_video import CreateVideo
        from comfy_api.latest import InputImpl, Types
        x=torch.stack(self.pending);self.pending=[]
        ct=encode_ct(x)
        if self.sdr:
            from .paintout import is_hdr
            sdr=sdr_view(x,is_hdr(self.plate['space']))
            h,w=sdr.shape[1:3]
            if h%2 or w%2:self.sdr_chunks.append(self.encode_odd_chunk(sdr,False))
            else:
                video=CreateVideo.execute(sdr,self.plate['fps'],bit_depth=10,color_space='sRGB',codec='none')[0]
                self.sdr_chunks.append(self.encode_chunk(video))
        if self.hdr:
            hlg=native_colour(ct,'HDR ACEScct','HDR')
            h,w=hlg.shape[1:3]
            if h%2 or w%2:self.hdr_chunks.append(self.encode_odd_chunk(hlg,True))
            else:
                video=CreateVideo.execute(hlg,self.plate['fps'],bit_depth=10,color_space='HDR',codec='none')[0]
                self.hdr_chunks.append(self.encode_chunk(video))
        if self.preview:
            h,w=ct.shape[1:3];scale=min(1,960/max(h,w))
            h=max(2,round(h*scale/2)*2);w=max(2,round(w*scale/2)*2)
            # SDR processing stays display-referred; HDR viewing uses a fixed shoulder.
            from .paintout import is_hdr
            shoulder=is_hdr(self.plate['space'])
            sdr=sdr_view(resize(x,h,w),shoulder)
            video=CreateVideo.execute(sdr,self.plate['fps'],bit_depth=8,color_space='sRGB',codec='none')[0]
            self.preview_chunks.append(self.encode_chunk(video))

    def encode_odd_chunk(self, images, hdr):
        """4:4:4 supports odd plate dimensions without adding delivery pixels."""
        from comfy_api.latest import InputImpl
        h,w=images.shape[1:3]
        pixels=(images.detach().cpu().clamp(0,1).numpy()*65535).round().astype('<u2')
        rate=str(self.plate.get('fps_rational',self.plate['fps']))
        colour=['-color_primaries','bt2020','-color_trc','arib-std-b67','-colorspace','bt2020nc'] if hdr else ['-color_primaries','bt709','-color_trc','iec61966-2-1','-colorspace','bt709']
        command=['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb48le','-s',f'{w}x{h}','-r',rate,'-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv444p10le','-preset','ultrafast','-crf','18','-bf','0',*colour,'-f','matroska','pipe:1']
        result=subprocess.run(command,input=pixels.tobytes(),capture_output=True,check=True)
        return InputImpl.VideoFromFile(io.BytesIO(result.stdout))

    @staticmethod
    def encode_chunk(video):
        from comfy_api.latest import InputImpl, Types
        buffer=io.BytesIO()
        # No B-frame delay at chunk joins. Native concatenation can remux these.
        video.save_to(buffer,format=Types.VideoContainer.MKV,codec=Types.VideoCodec.H264,preset='ultrafast',crf=18)
        return InputImpl.VideoFromFile(buffer)

    def finish(self):
        self.flush()
        if not(self.hdr_chunks or self.sdr_chunks or self.preview_chunks):return {}
        from comfy_api.latest import InputImpl, Types
        import folder_paths
        results=[]
        for name,chunks in [('paintout_HLG_10bit.mp4',self.hdr_chunks),('paintout_SDR_10bit.mp4',self.sdr_chunks),('motion_preview_SDR.mp4',self.preview_chunks)]:
            if not chunks:continue
            path=self.target/name
            video=InputImpl.VideoFromList(chunks,codec=Types.VideoCodec.H264)
            # Uses the same VIDEO implementation as native Create Video / Save Video.
            video.save_to(str(path),format=Types.VideoContainer.MP4,codec=Types.VideoCodec.AUTO)
            correct_video_clock(path,self.plate.get('fps_rational',self.plate['fps']))
            copy_source_audio(path,self.plate)
            rel=path.relative_to(Path(folder_paths.get_output_directory()))
            results.append({'filename':rel.name,'subfolder':str(rel.parent).replace('\\','/'),'type':'output'})
        # Comfy's standard video preview UI supports playback, seeking and looping.
        return {'images':results,'animated':(True,)} if results else {}
