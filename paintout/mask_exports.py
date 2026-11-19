"""Stream the actual repair blend matte into compositing deliverables."""
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

import numpy as np
from PIL import Image
from .media_tools import find_media_tool


def export_ref(path,root):
    relative=Path(path).resolve().relative_to(Path(root).resolve())
    return {'filename':relative.name,'subfolder':relative.parent.as_posix(),'type':'output'}


class MaskExports:
    def __init__(self,target,plate,root):
        self.target=Path(target);self.root=Path(root);self.plate=plate;self.count=0
        export_ref(self.target/'repair_mask.mov',self.root)
        self.width=plate['source']['width'];self.height=plate['source']['height']
        self.rate=Fraction(str(plate.get('fps_rational',plate['fps']))).limit_denominator(1_000_000)
        self.work=tempfile.TemporaryDirectory(prefix='.mask-',dir=self.target)
        self.folder=Path(self.work.name)
        self.full_frame_png=None

    def append(self,matte):
        matte=np.asarray(matte,dtype=np.float32)
        if matte.shape!=(self.height,self.width) or not np.isfinite(matte).all() or np.any(matte<0) or np.any(matte>1):raise ValueError('Invalid full-resolution repair matte.')
        path=self.folder/f'mask_{self.plate["start"]+self.count:06d}.png'
        Image.fromarray(np.rint(matte*65535).astype(np.uint16)).save(path,compress_level=1)
        self.count+=1

    def append_full_frame(self):
        if self.full_frame_png is None:
            self.full_frame_png=self.folder/f'mask_{self.plate["start"]+self.count:06d}.png'
            self.append(np.ones((self.height,self.width),dtype=np.float32))
        else:
            path=self.folder/f'mask_{self.plate["start"]+self.count:06d}.png'
            shutil.copyfile(self.full_frame_png,path)
            self.count+=1

    def finish(self):
        try:
            if self.count!=self.plate['count']:raise ValueError('The repair matte frame range is incomplete.')
            metadata={'role':'final_repair_compositing_matte','white':'generated repair','black':'original plate',
                      'width':self.width,'height':self.height,'sourceStartFrame':self.plate['start'],'frameCount':self.count,
                      'frameRate':{'numerator':self.rate.numerator,'denominator':self.rate.denominator},
                      'bitDepth':16,'grow':self.plate['grow'],'feather':self.plate.get('subtitle_feather',16) if self.plate.get('subtitle_full_crop') else self.plate['feather'],'protectionApplied':not self.plate.get('subtitle_full_crop',False)}
            archive=self.target/'repair_mask_png16.zip'
            with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED) as output:
                for frame in sorted(self.folder.glob('mask_*.png')):output.write(frame,frame.name)
                output.writestr('mask_info.json',json.dumps(metadata,indent=2))
            result=[{'role':'mask_sequence','file':export_ref(archive,self.root)}]
            try:ffmpeg=find_media_tool('ffmpeg')
            except (ValueError,FileNotFoundError,AttributeError):return result
            movie=self.target/'repair_mask.mov'
            command=[ffmpeg,'-v','error','-framerate',str(self.rate),'-start_number',str(self.plate['start']),'-i',str(self.folder/'mask_%06d.png'),
                     '-frames:v',str(self.count),'-an','-c:v','prores_ks','-profile:v','4','-pix_fmt','yuv444p10le','-tag:v','ap4h',
                     '-video_track_timescale',str(self.rate.numerator),'-movflags','+faststart+write_colr',str(movie)]
            subprocess.run(command,check=True,capture_output=True,timeout=600)
            result.insert(0,{'role':'mask','file':export_ref(movie,self.root)})
            return result
        finally:self.work.cleanup()

    def abort(self):self.work.cleanup()


def sequence_exports(target,root):
    """Publish the rendered EXRs themselves, never a reconstructed image."""
    target=Path(target);frames=sorted(target.glob('frame_*.exr'))
    if not frames:return []
    if len(frames)==1:return [{'role':'exr','file':export_ref(frames[0],root)}]
    archive=target/'render_exr.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED) as output:
        for frame in frames:output.write(frame,frame.name)
    return [{'role':'exr','file':export_ref(archive,root)}]


def retained_mask_exports(directory):
    """Keep the repair's real matte when its RGB goes through HDR conversion."""
    import folder_paths
    root=Path(folder_paths.get_output_directory()).resolve();directory=Path(directory).resolve()
    if not directory.is_relative_to(root):return []
    metadata=directory/'paintout.json'
    if not metadata.is_file():return []
    entries=json.loads(metadata.read_text(encoding='utf-8')).get('exports',[])
    result=[]
    for entry in entries:
        file=entry.get('file',{})
        if entry.get('role') not in ('mask','mask_sequence') or file.get('type')!='output':continue
        name=file.get('filename','');subfolder=file.get('subfolder','')
        if Path(name).name!=name or '\\' in name:raise ValueError('Invalid retained repair matte.')
        path=(root/subfolder/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('The retained repair matte is unavailable.')
        result.append({'role':entry['role'],'file':export_ref(path,root)})
    return result


def save_still_png(target,root,rgb):
    import OpenImageIO as oiio
    rgb=np.ascontiguousarray(np.rint(np.clip(rgb,0,1)*65535),dtype=np.uint16)
    path=Path(target)/'render.png';writer=oiio.ImageOutput.create(str(path))
    if not writer:raise ValueError('Could not create the still PNG.')
    try:
        spec=oiio.ImageSpec(rgb.shape[1],rgb.shape[0],3,oiio.UINT16)
        if not writer.open(str(path),spec) or not writer.write_image(rgb):raise ValueError('Could not save the still PNG.')
    finally:writer.close()
    return {'role':'image','file':export_ref(path,root)}
