"""Explicit colour declaration for tiny ProRes MOV fixtures across FFmpeg versions.

QuickTime nclc records have no range flag. The test encoder is configured for
BT.709 limited-range YUV; declare that known fixture contract using nclx without
re-encoding its compressed video or touching alpha/RGB samples.
"""
from pathlib import Path
import hashlib
import struct

import av

_CONTAINERS={b'moov',b'trak',b'mdia',b'minf',b'stbl'}
_PRORES={b'ap4h',b'ap4x',b'apch',b'apcn',b'apcs',b'apco'}
_NCLX=b'nclx'+struct.pack('>HHH',1,1,1)+b'\x00'


def _boxes(data):
    offset=0
    while offset<len(data):
        if len(data)-offset<8:raise AssertionError('Incomplete fixture MOV box')
        size,kind=struct.unpack_from('>I4s',data,offset);header=8
        if size==1:
            if len(data)-offset<16:raise AssertionError('Incomplete extended fixture MOV box')
            size=struct.unpack_from('>Q',data,offset+8)[0];header=16
        elif size==0:size=len(data)-offset
        if size<header or offset+size>len(data):raise AssertionError('Invalid fixture MOV box size')
        yield offset,kind,data[offset+header:offset+size],data[offset:offset+size]
        offset+=size


def _box(kind,payload):
    size=len(payload)+8
    if size>=2**32:raise AssertionError('Fixture MOV is unexpectedly large')
    return struct.pack('>I4s',size,kind)+payload


def _packets(path):
    with av.open(str(path)) as movie:
        return [(packet.stream.type,hashlib.sha256(bytes(packet)).hexdigest())
                for packet in movie.demux() if packet.size]


def declare_bt709_limited_mov(path):
    """Upgrade fixture colr metadata only; encoded packets must stay identical."""
    path=Path(path);before=path.read_bytes();roots=list(_boxes(before))
    movie=[box for box in roots if box[1]==b'moov'];data=[box for box in roots if box[1]==b'mdat']
    if len(movie)!=1 or not data or any(box[0]>movie[0][0] for box in data):
        raise AssertionError('Fixture must use moov after mdat so chunk offsets stay unchanged')
    coded=_packets(path);entries=0
    def rewrite(payload):
        nonlocal entries
        output=[]
        for _,kind,body,raw in _boxes(payload):
            if kind in _CONTAINERS:output.append(_box(kind,rewrite(body)))
            elif kind==b'stsd':output.append(_box(kind,body[:8]+rewrite(body[8:])))
            elif kind in _PRORES:
                if len(body)<78:raise AssertionError('Incomplete ProRes fixture sample entry')
                children=list(_boxes(body[78:]));colour=[]
                for _,child_type,child,child_raw in children:
                    if child_type==b'colr':
                        if child[:4] not in (b'nclc',b'nclx') or struct.unpack('>HHH',child[4:10])!=(1,1,1):
                            raise AssertionError('Fixture encoder did not declare BT.709 colour')
                        colour.append(_box(b'colr',_NCLX))
                    else:colour.append(child_raw)
                if not any(child[1]==b'colr' for child in children):colour.append(_box(b'colr',_NCLX))
                entries+=1;output.append(_box(kind,body[:78]+b''.join(colour)))
            else:output.append(raw)
        return b''.join(output)
    after=rewrite(before)
    if entries!=1:raise AssertionError('Expected one ProRes fixture sample description')
    if [box[3] for box in _boxes(after) if box[1]==b'mdat']!=[box[3] for box in data]:
        raise AssertionError('Compressed fixture media changed during metadata declaration')
    path.write_bytes(after)
    if _packets(path)!=coded:raise AssertionError('Fixture compressed packet identity changed')
    with av.open(str(path)) as movie:
        frame=next(movie.decode(video=0))
        if int(frame.colorspace)!=1 or int(frame.color_range)!=1:
            raise AssertionError('Decoder did not receive explicit BT.709 limited range')
