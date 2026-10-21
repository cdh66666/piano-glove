"""Versioned .pgl wire format shared by USB and hotspot (no hardware access)."""
import json
import math
import struct
import zlib
from pathlib import Path

HEADER = struct.Struct('<4sHHIIIHH')
EVENT = struct.Struct('<IIBBBBHH')
HEADER_SIZE = 128
MAX_EVENTS = 60000
MAX_DURATION = 24 * 60 * 60 * 1000

def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid ' + label)
    return value

def validate(score):
    if not isinstance(score, dict) or score.get('version') != 1 or score.get('hand') != 'right':
        raise ValueError('Only v1 right-hand scores are supported')
    title = score.get('title')
    if not isinstance(title, str) or not title.strip() or '\x00' in title or len(title.encode('utf-8')) > 96:
        raise ValueError('Title must be 1..96 UTF-8 bytes')
    notes = score.get('notes')
    if not isinstance(notes, list) or not 1 <= len(notes) <= MAX_EVENTS:
        raise ValueError('Invalid note count')
    end = integer(score.get('duration_ms'), 1, MAX_DURATION, 'duration')
    previous = -1
    occupied = {}
    for note in notes:
        if not isinstance(note, dict): raise ValueError('Invalid note')
        start = integer(note.get('t_ms'), 0, end, 'start')
        duration = integer(note.get('duration_ms'), 1, end, 'note duration')
        finger = integer(note.get('finger'), 1, 5, 'finger')
        integer(note.get('pitch'), 0, 127, 'MIDI pitch')
        integer(note.get('velocity', 96), 1, 127, 'velocity')
        integer(note.get('amplitude_pct', 100), 1, 100, 'amplitude')
        if start < previous or start + duration > end:
            raise ValueError('Notes must be chronological and fit the score')
        if occupied.get(finger, -1) > start:
            raise ValueError('Overlapping notes on one finger require score correction')
        previous = start
        occupied[finger] = start + duration
    return score

def encode(score):
    validate(score)
    title = score['title'].encode('utf-8')
    payload = b''.join(EVENT.pack(n['t_ms'], n['duration_ms'], n['pitch'], n['finger'],
                                 n.get('velocity',96), n.get('amplitude_pct',100), 0, 0)
                       for n in score['notes'])
    head = HEADER.pack(b'PGL1',1,HEADER_SIZE,len(score['notes']),score['duration_ms'],0,len(title),0)
    blob = bytearray(head + title + bytes(HEADER_SIZE-len(head)-len(title)) + payload)
    # Integrity covers metadata and notes with the checksum field zeroed.
    struct.pack_into('<I',blob,16,zlib.crc32(blob) & 0xffffffff)
    return bytes(blob)

def decode(blob):
    if not isinstance(blob, (bytes,bytearray)) or len(blob)<HEADER_SIZE:
        raise ValueError('Truncated file')
    magic,version,header,count,duration,crc,title_size,reserved = HEADER.unpack_from(blob)
    if (magic,version,header,reserved)!=(b'PGL1',1,HEADER_SIZE,0) or not 1<=count<=MAX_EVENTS or not 1<=title_size<=96:
        raise ValueError('Unsupported header')
    if len(blob)!=HEADER_SIZE+count*EVENT.size:
        raise ValueError('Invalid file length')
    check=bytearray(blob)
    struct.pack_into('<I',check,16,0)
    if zlib.crc32(check)&0xffffffff != crc: raise ValueError('CRC mismatch')
    if any(blob[HEADER.size+title_size:HEADER_SIZE]): raise ValueError('Unknown header fields')
    title=blob[HEADER.size:HEADER.size+title_size].decode('utf-8')
    notes=[]
    for i in range(count):
        t,d,p,f,v,a,flags,padding=EVENT.unpack_from(blob,HEADER_SIZE+i*EVENT.size)
        if flags or padding: raise ValueError('Unknown event flags')
        notes.append(dict(t_ms=t,duration_ms=d,pitch=p,finger=f,velocity=v,amplitude_pct=a))
    return validate(dict(version=1,hand='right',title=title,duration_ms=duration,notes=notes))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Convert reviewed right-hand score JSON to .pgl or back; does not perform OCR.')
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.input.suffix.lower()=='.pgl':
        args.output.write_text(json.dumps(decode(args.input.read_bytes()),ensure_ascii=False,indent=2),encoding='utf-8')
    else:
        args.output.write_bytes(encode(json.loads(args.input.read_text(encoding='utf-8-sig'))))
