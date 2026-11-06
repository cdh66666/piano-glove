"""Portable sounding timeline; the PGL1 stream remains glove motion only."""
import json
import re
import hashlib
from score_codec import MAX_DURATION, MAX_EVENTS

MAX_PERFORMANCE_BYTES = 8 * 1024 * 1024


def performance_identity(value):
    """Language-neutral integer/string arrays, also checked by the web player."""
    payload = [1, value['source_identity'], value['duration_ms'],
               [[e['t_ms'], e['duration_ms'], e['pitch'], e.get('velocity', 96),
                 e.get('finger') or 0, e.get('source_note_ids', [])]
                for e in value['audio_events']]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':'),
                                    allow_nan=False).encode('utf8')).hexdigest()


def clean_performance(value, duration_ms=None, clone=True):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('mode') not in ('practice', 'strict'):
        raise ValueError('练习编排格式不正确')
    if not isinstance(value.get('arrangement_id'), str) or not re.fullmatch(r'[0-9a-f]{64}', value['arrangement_id']):
        raise ValueError('练习编排标识不正确')
    if not isinstance(value.get('source_identity'), str) or not re.fullmatch(r'[0-9a-f]{64}', value['source_identity']):
        raise ValueError('练习编排的源标识不正确')
    end = value.get('duration_ms')
    if type(end) is not int or not 1 <= end <= MAX_DURATION or (duration_ms is not None and end != duration_ms):
        raise ValueError('练习编排总时长与动作谱不一致')
    events = value.get('audio_events')
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError('练习琴声事件数不正确')
    previous = -1
    referenced = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('练习琴声事件不正确')
        start, duration = event.get('t_ms'), event.get('duration_ms')
        if type(start) is not int or type(duration) is not int or start < previous or start < 0 or duration <= 0 or start + duration > end:
            raise ValueError('练习琴声的开始或持续时间不正确')
        if type(event.get('pitch')) is not int or not 0 <= event['pitch'] <= 127:
            raise ValueError('练习琴声音高不正确')
        if type(event.get('velocity', 96)) is not int or not 1 <= event.get('velocity', 96) <= 127:
            raise ValueError('练习琴声力度不正确')
        finger = event.get('finger')
        if finger is not None and (type(finger) is not int or not 1 <= finger <= 5):
            raise ValueError('练习琴声指法不正确')
        sources = event.get('source_note_ids', [])
        if not isinstance(sources, list) or any(type(s) not in (str, int) or not str(s) or len(str(s)) > 256 for s in sources):
            raise ValueError('练习琴声来源不正确')
        referenced.update(str(s) for s in sources)
        previous = start
    mapping = value.get('source_map')
    if mapping is not None and (not isinstance(mapping, dict) or any(not isinstance(m, dict) for m in mapping.values())
                                or not referenced.issubset(str(s) for s in mapping)):
        raise ValueError('练习琴声缺少原谱来源映射')
    if performance_identity(value) != value['arrangement_id']:
        raise ValueError('练习琴声与编排标识不一致')
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('练习编排包含不支持的数据') from error
    if len(encoded) > MAX_PERFORMANCE_BYTES:
        raise ValueError('练习编排超过8MB，请分段导出')
    return json.loads(encoded) if clone else value
