"""Optional isolated Parakeet word timestamps, using installed ONNX assets only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    model=args.models/'parakeet-tdt-0.6b-v3-int8';vad=args.models/'silero-vad'
    if not model.is_dir() or not vad.is_dir():raise RuntimeError('Install the Parakeet v3 INT8 and Silero ONNX assets before transcription.')
    import onnx_asr
    recognizer=onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v3',str(model),quantization='int8')
    timed=recognizer.with_vad(onnx_asr.load_vad('silero',str(vad)),max_speech_duration_s=20).with_timestamps()
    words=[]
    with tempfile.TemporaryDirectory(prefix='zura-words-') as temp:
        wav=Path(temp)/'audio.wav'
        subprocess.run([shutil.which('ffmpeg'),'-v','error','-y','-protocol_whitelist','file,pipe',
            '-format_whitelist','wav,mp3,flac,ogg,aac,mov,matroska,webm,avi,aiff,asf,mpeg,mpegvideo',
            '-i',str(args.input),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],check=True,
            **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
        for item in timed.recognize(str(wav)):
            groups=[]
            for token,offset in zip(item.tokens,item.timestamps):
                if not token:continue
                if token[0].isspace() or not groups:groups.append([token.strip(),float(item.start)+float(offset)])
                else:groups[-1][0]+=token
            for i,(text,start) in enumerate(groups):
                end=groups[i+1][1] if i+1<len(groups) else float(item.end)
                if text and end>start:words.append({'text':text,'start':start,'end':end})
    if not words:raise RuntimeError('No words recognised. Use manual waveform selection.')
    pending=args.output.with_suffix('.'+str(os.getpid())+'.tmp')
    pending.write_text(json.dumps(words,ensure_ascii=False),encoding='utf-8');pending.replace(args.output)


if __name__=='__main__':main()
