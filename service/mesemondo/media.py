import hashlib
import json
import os
import shutil
import subprocess
import tempfile



def probe(path):
    data = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
    streams = data['streams']
    if len(streams)!=1 or streams[0]['codec_name']!='mp3' or streams[0]['channels']!=1 or int(streams[0]['sample_rate'])!=32000 or int(streams[0]['bit_rate'])!=64000:
        raise ValueError('Required: MP3, mono, 32000 Hz, CBR 64000 bps')
    subprocess.run(['nice','-n','15','ffmpeg','-threads','1','-filter_threads','1','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    validate_frames(path)
    return {'size_bytes':path.stat().st_size,'sha256':file_digest(path),'duration_ms':round(float(data['format']['duration'])*1000)}


def file_digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def validate_frames(path):
    """Validate frame headers without loading the entire recording into RAM."""
    length = path.stat().st_size
    count = 0
    with path.open('rb') as stream:
        tag = stream.read(10)
        if tag.startswith(b'ID3'):
            if len(tag) != 10 or any(v & 128 for v in tag[6:10]):
                raise ValueError('Invalid ID3 header')
            stream.seek(10 + sum(tag[6+j] << (7*(3-j)) for j in range(4)))
        else:
            stream.seek(0)
        while stream.tell() < length:
            position = stream.tell()
            header = stream.read(4)
            if length-position == 128 and header.startswith(b'TAG'):
                break
            if len(header) != 4:
                raise ValueError('Truncated MP3 frame')
            h = int.from_bytes(header, 'big')
            if h>>21!=0x7ff or (h>>19)&3!=3 or (h>>17)&3!=1 or (h>>12)&15!=5 or (h>>10)&3!=2 or (h>>6)&3!=3:
                raise ValueError('Unsupported or non-CBR MP3 frame')
            size = 144*64000//32000 + ((h>>9)&1)
            if position + size > length:
                raise ValueError('Truncated MP3 frame')
            stream.seek(position + size)
            count += 1
    if not count:
        raise ValueError('No MP3 frames')


def normalize(source, output, seconds=None):
    if output.exists():
        raise ValueError('Output already exists; use a new content version')
    cut = ['-t',str(seconds)] if seconds else []
    base=['nice','-n','15','ffmpeg','-hide_banner','-nostdin','-threads','1','-filter_threads','1','-i',str(source),*cut,'-map','0:a:0','-ac','1']
    result=subprocess.run(base+['-af','loudnorm=I=-23:TP=-2:LRA=7:print_format=json','-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    measured=json.loads(result.stderr[result.stderr.rfind('{'):])
    if any(measured[k] in ('-inf','inf') for k in ('input_i','input_tp','input_lra','input_thresh')):
        raise ValueError('Silent or invalid input audio')
    filt='loudnorm=I=-23:TP=-2:LRA=7:linear=true:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}'.format(**measured)
    subprocess.run(base+['-af',filt,'-ar','32000','-codec:a','libmp3lame','-threads','1','-b:a','64k','-map_metadata','-1','-write_xing','0','-id3v2_version','0','-f','mp3','-n',str(output)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return probe(output)


def store_blob(source, storage):
    storage.mkdir(parents=True,exist_ok=True,mode=0o700)
    checksum=file_digest(source)
    target=storage/checksum
    if target.exists():
        if file_digest(target)!=checksum:
            raise ValueError('Corrupt immutable object')
        return checksum
    fd,tmp=tempfile.mkstemp(dir=storage,prefix='.import-')
    try:
        with os.fdopen(fd,'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp,out)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp,0o444)
        try:
            os.link(tmp,target)
        except FileExistsError:
            if file_digest(target)!=checksum:
                raise ValueError('Corrupt immutable object')
        dfd=os.open(storage,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        os.unlink(tmp)
    return checksum
