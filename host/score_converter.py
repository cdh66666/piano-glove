"""Local PDF -> review project -> right-hand PGL. No serial or motion access."""
import argparse
import json
import math
import re
from pathlib import Path
from score_codec import encode, validate


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def pitch_midi(value):
    match = re.fullmatch(r'([A-Ga-g])(##|bb|#|b|)(-?\d+)', str(value))
    if not match:
        raise ValueError('音高须为 C4、F#4 等音名')
    letter, accidental, octave = match.groups()
    number = (int(octave) + 1) * 12 + {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[letter.upper()]
    number += {'':0,'#':1,'b':-1,'##':2,'bb':-2}[accidental]
    if not 0 <= number <= 127:
        raise ValueError('音高超出 MIDI 范围')
    return number


def source_range(selection):
    """Inclusive printed order; system/measure numbering restarts on new pages."""
    fields = [field for field in ('page', 'system', 'measure')
              if selection.get('start_' + field) is not None or
              selection.get('end_' + field) is not None]
    lower, upper = [], []
    for field in fields:
        lo, hi = selection.get('start_' + field), selection.get('end_' + field)
        if any(value is not None and (type(value) is not int or value < 1)
               for value in (lo, hi)):
            raise ValueError('页、谱表组、小节必须为正整数')
        lower.append(lo if lo is not None else 1)
        upper.append(hi if hi is not None else math.inf)
    if tuple(lower) > tuple(upper):
        raise ValueError('原谱区间的结束位置早于开始位置')
    return fields, tuple(lower), tuple(upper)


def recognize_pdf(path, bpm=120):
    from score_converter_engine import recognize
    if not finite(bpm) or not 10 <= bpm <= 240:
        raise ValueError('BPM须为10至240')
    project = recognize(path)
    project['name'] = Path(path).stem
    project['selection'] = dict(hand='right', bpm=bpm, start_beat=0, end_beat=None,
                                range_reviewed=False, repeat_mode='written')
    for note in project['notes']:
        note['duration_beats'] = note.get('duration')
        note['confirmed'] = False
        # Local sections remain usable even when earlier repeats close the
        # whole-score timeline. This is an explicit review candidate, not a
        # substitute for an unknown whole-score beat.
        note['section_beat_candidate'] = note.get('written_beat')
    right = [n for n in project['notes'] if n['hand'] == 'right']
    project['report'] = dict(
        pages=len(project['pages']), candidates=len(project['notes']), right_candidates=len(right),
        right_complete_fields=sum(n.get('finger') is not None and n.get('pitch') is not None and
                                  n.get('beat') is not None and n.get('duration') is not None for n in right),
        right_section_complete_fields=sum(n.get('finger') is not None and n.get('pitch') is not None and
                                          n.get('written_beat') is not None and n.get('duration') is not None for n in right),
        unresolved_hand=sum(n['hand'] is None for n in project['notes']),
        unsupported_pages=sum(p['staff_count'] == 0 for p in project['pages']),
        rests=len(project.get('rests',[])),
        tie_candidates=sum(n.get('tie_to_candidate') is not None for n in project['notes']),
        repeat_sections=len(project.get('repeat_sections',[])),
        requires_review=True, ready=False)
    return project


def _merge_reviewed_ties(records, selection):
    if not any(record['source'].get('tie_to') is not None or
               (selection.get('apply_tie_candidates') is True and record['source'].get('tie_to_candidate') is not None)
               for record in records):
        return [dict(record,sources=[record['source']]) for record in records]
    by_id={record['source'].get('id'):record for record in records}
    links={}
    for record in records:
        source=record['source']
        target_id=source.get('tie_to')
        if selection.get('apply_tie_candidates') is True and target_id is None:
            target_id=source.get('tie_to_candidate')
        if target_id is None:
            continue
        if source.get('tie_reviewed') is not True and selection.get('ties_reviewed') is not True:
            raise ValueError('请对照原谱确认延音线，再合并连音')
        target=by_id.get(target_id)
        if target is None or target is record:
            raise ValueError('连音目标不存在或不在所选区间')
        if (target['pitch']!=record['pitch'] or
            abs(record['beat']+record['duration']-target['beat'])>1e-6):
            raise ValueError('延音线两端必须音高相同、时间连续')
        if (record['source'].get('finger') is not None and target['source'].get('finger') is not None
            and target['source']['finger']!=record['source']['finger']):
            raise ValueError('延音线指法改变需要人工调整')
        if target_id in links.values():
            raise ValueError('多个连音指向同一个音符')
        links[source.get('id')]=target_id
    incoming=set(links.values())
    merged=[]
    for record in records:
        if record['source'].get('id') in incoming:
            continue
        result=dict(record, sources=[record['source']])
        current=record
        visited=set()
        while current['source'].get('id') in links:
            ident=current['source'].get('id')
            if ident in visited:
                raise ValueError('延音线不能形成循环')
            visited.add(ident)
            current=by_id[links[ident]]
            if current['source'].get('finger') not in (None,result['source'].get('finger')):
                raise ValueError('延音线指法改变需要人工调整')
            result['duration']+=current['duration']
            result['sources'].append(current['source'])
        merged.append(result)
    return merged


def _performance_segments(project, selection, start, end):
    """Only reviewed, disjoint repeat sections are expanded; no guessed endings."""
    mode=selection.get('repeat_mode','written')
    if mode not in ('written','unfold'):
        raise ValueError('反复模式须为 written 或 unfold')
    if mode=='written':
        return [(start,end,0.0)],end-start
    if project.get('repeat_review_issues') and selection.get('performance_order_reviewed') is not True:
        raise ValueError('未解决的反复或导航标记需要人工整理演奏顺序')
    sections=[]
    for repeat in project.get('repeat_sections',[]):
        lo,hi,count=repeat.get('start_beat'),repeat.get('end_beat'),repeat.get('count',2)
        if not finite(lo) or not finite(hi) or lo<0 or hi<=lo or type(count) is not int or not 2<=count<=10:
            raise ValueError('反复区间或次数无效')
        first,second=repeat.get('first_ending_start_beat'),repeat.get('second_ending_end_beat')
        alternate=first is not None or second is not None
        if alternate and (count!=2 or not finite(first) or not finite(second) or not lo<first<hi<second):
            raise ValueError('第一、第二结尾区间无效；其他跳房子需要人工整理')
        section_end=second if alternate else hi
        if section_end<=start or lo>=end:
            continue
        if lo<start or section_end>end:
            raise ValueError('所选区间不能截断反复段')
        if repeat.get('confirmed') is not True and selection.get('repeats_reviewed') is not True:
            raise ValueError('请对照原谱确认反复段与次数，再展开')
        sections.append((lo,hi,count,first,second))
    sections.sort(key=lambda item:item[0])
    segments=[];cursor=start;played=0.0
    for lo,hi,count,first,second in sections:
        if lo<cursor:
            raise ValueError('重叠、嵌套反复或跳房子需要人工整理演奏顺序')
        if lo>cursor:
            segments.append((cursor,lo,played));played+=lo-cursor
        if first is not None:
            for left,right in ((lo,hi),(lo,first),(hi,second)):
                segments.append((left,right,played));played+=right-left
            cursor=second
        else:
            for _ in range(count):
                segments.append((lo,hi,played));played+=hi-lo
            cursor=hi
    if cursor<end:
        segments.append((cursor,end,played));played+=end-cursor
    return segments,played


def export_reviewed(project):
    selection = project.get('selection', {})
    if selection.get('range_reviewed') is not True:
        raise ValueError('请对照原谱确认所选区间没有漏音，再导出')
    bpm, start, end = selection.get('bpm', 120), selection.get('start_beat', 0), selection.get('end_beat')
    if not finite(bpm) or not 10 <= bpm <= 240 or not finite(start) or start < 0:
        raise ValueError('速度或区间无效')
    if end is not None and (not finite(end) or end <= start):
        raise ValueError('结束拍无效')
    source_fields, source_start, source_end = source_range(selection)
    records = []
    errors = []
    for note in project.get('notes', []):
        if note.get('excluded') is True:
            continue
        if note.get('hand') == 'left':
            continue
        if source_fields:
            coordinates = tuple(note.get(field) for field in source_fields)
            if any(type(value) is not int or value < 1 for value in coordinates):
                errors.append(f"音符{note.get('id', '?')}：核对原谱页、谱表组与小节位置"); continue
            if not source_start <= coordinates <= source_end:
                continue
        beat = note.get('beat')
        if finite(beat) and (beat < start or (end is not None and beat >= end)):
            continue
        label = f"第{note.get('page', '?')}页 音符{note.get('id', '?')}"
        if note.get('hand') != 'right':
            errors.append(label + '：核对左右手'); continue
        if note.get('confirmed') is not True:
            errors.append(label + '：尚未确认'); continue
        duration = note.get('duration_beats')
        if not finite(beat) or beat < 0 or not finite(duration) or duration <= 0:
            errors.append(label + '：核对起拍与时值'); continue
        try:
            pitch = pitch_midi(note.get('pitch'))
        except ValueError:
            errors.append(label + '：核对音高'); continue
        records.append(dict(beat=beat,duration=duration,pitch=pitch,source=note))
    if errors:
        raise ValueError('\n'.join(errors[:30]) + (f'\n另有{len(errors)-30}项' if len(errors)>30 else ''))
    if not records:
        raise ValueError('没有已核对的右手音符')
    if any(n['source'].get('tie_to') is not None for n in records) or selection.get('apply_tie_candidates') is True:
        identifiers=[n['source'].get('id') for n in records]
        if any(type(ident) not in (str,int) for ident in identifiers) or len(set(identifiers))!=len(identifiers):
            raise ValueError('合并延音线需要唯一音符编号')
    records=_merge_reviewed_ties(records,selection)
    for record in records:
        finger=record['source'].get('finger')
        if type(finger) is not int or not 1<=finger<=5:
            raise ValueError(f"音符{record['source'].get('id','?')}：核对1至5指法")
    written_end=max(n['beat']+n['duration'] for n in records)
    if end is not None:
        written_end=max(written_end,end)
    elif not source_fields and finite(project.get('written_duration_beats')):
        written_end=max(written_end,project['written_duration_beats'])
    segments,performed_duration=_performance_segments(project,selection,start,written_end)
    exported=[]
    occurrence=0
    for lo,hi,played in segments:
        for record in records:
            if not lo<=record['beat']<hi:
                continue
            if selection.get('repeat_mode')=='unfold' and record['beat']+record['duration']>hi+1e-6:
                raise ValueError('跨越反复边界的持续音需要人工整理')
            occurrence+=1
            source=record['source']
            note=dict(t_ms=round((played+record['beat']-lo)*60000/bpm),
                      duration_ms=round(record['duration']*60000/bpm),pitch=record['pitch'],
                      finger=source['finger'],velocity=96,amplitude_pct=100)
            sources=record.get('sources',[source])
            metadata={key:source[key] for key in ('id','page','system','measure','origin','bbox') if key in source}
            metadata.update(t_ms=note['t_ms'],duration_ms=note['duration_ms'],finger=note['finger'],pitch=note['pitch'],
                            source_note_ids=[s.get('id') for s in sources],occurrence=occurrence)
            metadata['source_spans']=[dict({key:s[key] for key in ('id','page','system','measure','origin','bbox') if key in s},
                t_ms=note['t_ms']+round((s['beat']-source['beat'])*60000/bpm),
                duration_ms=round(s['duration_beats']*60000/bpm)) for s in sources]
            exported.append((note,metadata))
    exported.sort(key=lambda pair:(pair[0]['t_ms'],pair[0]['finger']))
    notes=[pair[0] for pair in exported]
    title = str(project.get('name', project.get('source_name', '练习')))
    while len(title.encode('utf-8')) > 96:
        title = title[:-1]
    score = dict(version=1, hand='right', title=title, notes=notes,
                 duration_ms=max(max(n['t_ms']+n['duration_ms'] for n in notes),
                                 round(performed_duration*60000/bpm)),
                 source_notes=[pair[1] for pair in exported])
    return validate(score)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--bpm', type=float, default=120)
    args = parser.parse_args()
    if args.input.suffix.lower() == '.pdf':
        args.output.write_text(json.dumps(recognize_pdf(args.input, args.bpm), ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        project = json.loads(args.input.read_text(encoding='utf-8-sig'))
        args.output.write_bytes(encode(export_reviewed(project)))


if __name__ == '__main__':
    main()
