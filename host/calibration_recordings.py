"""Preserve full observed calibration paths, including encoder wrap crossings."""
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'calibration_recordings'

def validate_recording(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('轨迹格式无效')
    slot, encoder = data.get('slot'), data.get('range')
    if type(slot) is not int or not 0 <= slot <= 5:
        raise ValueError('轨迹槽位无效')
    if (data.get('profile'), encoder) not in (('SCS',1023),('STS',4095)):
        raise ValueError('轨迹型号或量程无效')
    if not re.fullmatch(r'[0-9]+', str(data.get('id',''))) or not 1 <= int(data['id']) <= 253:
        raise ValueError('轨迹设备编号无效')
    if type(data.get('complete')) is not bool:
        raise ValueError('轨迹完成状态无效')
    frames = data.get('frames')
    if not isinstance(frames,list) or not 1 <= len(frames) <= 200000:
        raise ValueError('轨迹帧数无效')
    previous = None
    period = encoder + 1
    for frame in frames:
        if not isinstance(frame,dict):
            raise ValueError('轨迹帧无效')
        t, raw, expanded = frame.get('t_ms'), frame.get('raw'), frame.get('unwrapped')
        if type(t) not in (int,float) or not math.isfinite(t) or t < 0:
            raise ValueError('轨迹时间无效')
        if type(raw) is not int or not 0 <= raw <= encoder or type(expanded) is not int:
            raise ValueError('轨迹位置无效')
        if previous is not None:
            delta = (raw-previous['raw']+period/2) % period-period/2
            if t < previous['t_ms'] or expanded-previous['unwrapped'] != delta:
                raise ValueError('轨迹时间或跨零展开不连续')
        previous = frame
    return data

def save_recording(data, root=ROOT):
    validate_recording(data)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    target = root / (identity+'.json')
    temp = root / (identity+'.tmp')
    saved = dict(data, savedAt=datetime.now(timezone.utc).isoformat())
    temp.write_text(json.dumps(saved,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    os.replace(temp,target)
    return {'ok':True,'id':identity,'url':'/calibration_trace.html?id='+identity,'dataUrl':'/api/calibration/recording?id='+identity,
            'file':str(target),'frames':len(data['frames']),'complete':data['complete']}

def read_recording(identity, root=ROOT):
    if not re.fullmatch(r'[0-9a-f]{32}',identity):
        raise ValueError('轨迹编号无效')
    return json.loads((Path(root)/(identity+'.json')).read_text(encoding='utf-8'))
