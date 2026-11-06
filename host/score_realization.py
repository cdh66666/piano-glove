"""Compile written notation to an explicit, source-preserving practice performance.

The PDF/review notes are never edited.  Ambiguous performance choices are a
separate policy, not invented source readings.  Audio and finger intervals are
separate: a PGL1 file carries legal finger intervals; the performance manifest
carries every sounding attack, including the original gray/unfingered notes.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re

from score_codec import MAX_EVENTS, MAX_DURATION, validate
from score_converter import export_scope, _performance_segments
from score_timing import reflow_right_hand_timing
from score_compound import COMBINATION,LONG_MORDENT,combination_pair,long_mordent_pair

DEFAULT_POLICY = dict(mode='practice', estimate_unresolved_fingering=True,
    grace_ms=80.0, ornament_rate_hz=8.0, arpeggio_step_ms=30.0,
    fermata_factor=1.5, legato_overlap_ms=20.0)
KINDS = frozenset(('grace_long','grace_short','grace_cluster','grace_after',
    'grace_unspecified','mordent_upper','mordent_lower','turn','inverted_turn',
    'trill','arpeggio','broken_chord','glissando','tremolo_single',
    'tremolo_alternating','tuplet','dots','syncopation','tie','slur','fermata',
    'staccato','staccatissimo','tenuto','accent','ottava','pedal'))
GRACES = frozenset(k for k in KINDS if k.startswith('grace_'))
ORNAMENTS = frozenset(('mordent_upper','mordent_lower','turn','inverted_turn',
    'trill','glissando','tremolo_single'))
EDITABLE_KINDS=GRACES|frozenset(('mordent_upper','mordent_lower','turn','inverted_turn','trill','tremolo_single',COMBINATION,LONG_MORDENT))
LABELS = dict(grace_long='长倚音',grace_short='短倚音',grace_cluster='复倚音',
    grace_after='后倚音',grace_unspecified='倚音',mordent_upper='上波音',
    mordent_lower='下波音',turn='顺回音',inverted_turn='逆回音',trill='颤音',
    arpeggio='琶音',broken_chord='分解和弦',glissando='滑音',
    tremolo_single='同音震音',tremolo_alternating='交替震音',tuplet='连音组',
    dots='附点',syncopation='切分音',tie='延音线',slur='连音线',fermata='延长记号',
    staccato='跳音',staccatissimo='极短跳音',tenuto='保持音',accent='重音',trill_with_lower_mordent='颤音加下波收尾',long_lower_mordent='长下波音',
    ottava='八度移位',pedal='延音踏板',fingering='练习指法',finger_overlap='同指声部重按',source_timing='起拍估计')


def finite(x):
    return type(x) in (int,float) and math.isfinite(x)


def finger(x):
    return type(x) is int and 1 <= x <= 5


def pitch_midi(value):
    if type(value) is int and 0 <= value <= 127:
        return value
    match=re.fullmatch(r'([A-Ga-g])(##|bb|#|b|)(-?\d+)',str(value))
    if not match:
        raise ValueError('音高须为C4、F#4等音名')
    letter,alter,octave=match.groups()
    result=12*(int(octave)+1)+dict(C=0,D=2,E=4,F=5,G=7,A=9,B=11)[letter.upper()]+{'':0,'#':1,'b':-1,'##':2,'bb':-2}[alter]
    if not 0 <= result <= 127:
        raise ValueError('音高超出MIDI范围')
    return result


def normalize_policy(project, policy=None):
    supplied=project.get('performance_policy') if policy is None else policy
    supplied={} if supplied is None else supplied
    if not isinstance(supplied,dict) or supplied.get('mode','strict') not in ('practice','strict'):
        raise ValueError('演奏模式须为practice或strict')
    result=dict(DEFAULT_POLICY,**supplied)
    result['mode']=supplied.get('mode','strict')
    for key,lo,hi in [('grace_ms',10,500),('ornament_rate_hz',1,20),
                      ('arpeggio_step_ms',1,250),('fermata_factor',1,8),('legato_overlap_ms',0,100)]:
        if not finite(result[key]) or not lo <= result[key] <= hi:
            raise ValueError('练习参数无效：'+key)
    if type(result['estimate_unresolved_fingering']) is not bool:
        raise ValueError('练习指法估计选项不正确')
    return result


def normalize_override(note):
    value=note.get('performance_override') or {}
    if not isinstance(value,dict):
        raise ValueError('练习编排修改项不正确')
    result=dict(value)
    if result.get('kind') is None:result.pop('kind',None)
    if result.get('placement','on') not in ('before','on','after'):
        raise ValueError('倚音位置须为before/on/after')
    if result.get('mode','auto') not in ('auto','written'):
        raise ValueError('单音编排模式不正确')
    if 'kind' in result and result['kind'] not in EDITABLE_KINDS:
        raise ValueError('练习奏法类型不在可修改范围内')
    for key,lo,hi in [('rate_hz',1,20),('borrow_ratio',.02,.8),('hold_factor',1,8),('gate_ratio',.1,1.2)]:
        if key in result and (not finite(result[key]) or not lo<=result[key]<=hi):
            raise ValueError('练习编排参数超出范围：'+key)
    if result.get('aux_finger') is not None and not finger(result['aux_finger']):
        raise ValueError('辅助指法须为1至5')
    if result.get('lower_aux_finger') is not None and not finger(result['lower_aux_finger']):
        raise ValueError('下邻辅助指法须为1至5')
    if 'velocity' in result and (type(result['velocity']) is not int or not 1<=result['velocity']<=127):
        raise ValueError('声音力度须为1至127')
    if 'reviewed' in result and type(result['reviewed']) is not bool:
        raise ValueError('编排确认状态不正确')
    return result


def _marks(note):
    result=[]
    for item in note.get('performance_marks') or []:
        if isinstance(item,dict) and item.get('kind') in KINDS:
            mark=deepcopy(item);mark.setdefault('options',{})
            if not isinstance(mark['options'],dict):
                raise ValueError('特殊奏法参数不正确')
            result.append(mark)
    known={m['kind'] for m in result}
    grace=note.get('grace_kind')
    if not known.intersection(GRACES) and grace in ('slashed','unmeasured_prefix','unmeasured'):
        result.append(dict(kind='grace_short' if grace=='slashed' else 'grace_unspecified',
            group_id=note.get('grace_group'),options=dict(anchor_id=note.get('main_anchor_id'))))
    if 'arpeggio' not in known and 'arpeggio_requires_review' in (note.get('issues') or []):
        result.append(dict(kind='arpeggio',options={}))
    if note.get('tremolo_group') and 'tremolo_alternating' not in known:
        result.append(dict(kind='tremolo_alternating',group_id=note['tremolo_group'],
            options=dict(side=note.get('tremolo_side'),step_beats=note.get('tremolo_step_beats'),
                span_beats=note.get('tremolo_span_beats'))))
    if note.get('tie_to') is not None or note.get('tie_to_candidate') is not None:
        if 'tie' not in known:
            result.append(dict(kind='tie',options=dict(target_id=note.get('tie_to',note.get('tie_to_candidate')),already_applied=True)))
    rhythm=note.get('rhythm_evidence') or {}
    if rhythm.get('tuplet') and 'tuplet' not in known:
        result.append(dict(kind='tuplet',options=dict(rhythm['tuplet'],already_applied=True)))
    dots=rhythm.get('dots',rhythm.get('dot_count'))
    if type(dots) is int and dots>0 and 'dots' not in known:
        result.append(dict(kind='dots',options=dict(count=dots,already_applied=True)))
    if note.get('octave_shift') and 'ottava' not in known:
        result.append(dict(kind='ottava',options=dict(semitones=note['octave_shift'],already_applied=True)))
    return result


def _key_alter(letter,key):
    if isinstance(key,dict):
        value=key.get(letter,key.get(letter.lower(),0))
        return int(value) if finite(value) and value==int(value) and -2<=value<=2 else 0
    if type(key) is not int or not -7<=key<=7:
        key=0
    if key>0 and letter in 'FCGDAEB'[:key]:return 1
    if key<0 and letter in 'BEADGCF'[:-key]:return -1
    return 0


def _neighbor(record,direction,options,generic_accidental=True):
    source=record['source'];context=source.get('pitch_context') or {}
    match=re.fullmatch(r'([A-Ga-g])(##|bb|#|b|)(-?\d+)',str(source.get('pitch')))
    letter=(match[1].upper() if match else context.get('letter'))
    if letter not in 'CDEFGAB':
        letter=('C','C','D','D','E','F','F','G','G','A','A','B')[record['pitch']%12]
    letters='CDEFGAB';index=letters.index(letter)+direction
    next_letter=letters[index%7]
    natural=dict(C=0,D=2,E=4,F=5,G=7,A=9,B=11)
    alter=_key_alter(next_letter,context.get('key_signature',0))
    explicit=options.get('upper_auxiliary_accidental' if direction>0 else 'lower_auxiliary_accidental',
        options.get('auxiliary_accidental') if generic_accidental else None)
    if explicit is not None:
        values={'sharp':1,'flat':-1,'natural':0,'double_sharp':2,'double_flat':-2,'#':1,'b':-1,'n':0,'♯':1,'♭':-1,'♮':0,'𝄪':2,'𝄫':-2}
        if isinstance(explicit,str) and explicit in values:alter=values[explicit]
        elif type(explicit) is int and -2<=explicit<=2:alter=explicit
        else:raise ValueError('辅助变音记号不正确')
    if match:
        octave=int(match[3])+1+(record['pitch']-pitch_midi(source['pitch']))//12
    else:
        octave=(record['pitch']-natural[letter])//12
    target=octave*12+natural[next_letter]+alter
    if index<0:target-=12
    if index>=7:target+=12
    if not 0<=target<=127:raise ValueError('辅助音超出MIDI范围')
    return target


class _Warp:
    def __init__(self):self.ops=[]
    def __call__(self,t):
        for start,end,scale,extra in self.ops:
            if t<start-1e-10:continue
            if end>start and t<end:t=start+(t-start)*scale
            else:t+=extra
        return t
    def scale(self,start,end,ratio):
        a,b=self(start),self(end)
        if b<=a or not finite(ratio) or ratio<=0:raise ValueError('演奏时间比例不正确')
        self.ops.append((a,b,ratio,(b-a)*(ratio-1)))
    def hold(self,start,end,factor):
        a,b=self(start),self(end)
        if b<=a:raise ValueError('延长记号没有可延长的时间')
        self.ops.append((b,b,1,(b-a)*(factor-1)))


def _duration(note):
    value=note.get('duration_beats')
    if finite(value) and value>0:return float(value)
    if 'duration_beats' in (note.get('manual_fields') or []):return None
    value=note.get('duration')
    return float(value) if finite(value) and value>0 else None


def _plain_title(project):
    title=str(project.get('name') or project.get('source_name') or '练习').strip()
    return title or '练习'


def _valid_id(value):return type(value) in (str,int) and str(value)!=''


def _practice_timing_project(project):
    """Reflow a temporary clock when a newly read small note is unmeasured.

    The legacy written clock may already have counted that note's visual flag
    value.  Mark classification therefore has to enter the derived meter
    model, not merely the attack generator.  Explicit user durations/anchors
    remain data; source/review fields and source repeat positions are untouched.
    """
    additions=[]
    for source in project.get('notes',[]):
        if source.get('hand')!='right' or 'duration_beats' in (source.get('manual_fields') or []):continue
        if source.get('grace_kind') in ('slashed','unmeasured_prefix','unmeasured'):continue
        grace=next((m for m in _marks(source) if m['kind'] in GRACES),None)
        if grace is not None:additions.append((str(source.get('id')),grace))
    if not additions or (project.get('source_kind')=='manual' and project.get('recognition_performed') is False):return project
    clock=dict(project)
    clock['notes']=[dict(n) for n in project.get('notes',[])]
    clock['rests']=[dict(n) for n in project.get('rests',[])]
    clock['staves']=[dict(s,measures=[dict(m) for m in s.get('measures',[])]) for s in project.get('staves',[])]
    for key in ('repeat_sections','repeat_markers','ending_brackets'):
        if isinstance(project.get(key),list):clock[key]=deepcopy(project[key])
    clock['selection']=dict(project.get('selection') or {})
    clock.pop('right_hand_timing',None)
    notes={str(n.get('id')):n for n in clock['notes']}
    affected=set()
    for ident,mark in additions:
        event=notes[ident];event['grace_kind']='unmeasured'
        event['duration_beats']=None;event['duration']=None
        anchor=mark['options'].get('anchor_id',event.get('main_anchor_id'))
        if anchor is not None:
            event['main_anchor_id']=anchor
            target=notes.get(str(anchor))
            if target and finite(target.get('measure_beat')):event['main_anchor_measure_beat']=target['measure_beat']
        affected.add(tuple(event.get(k) for k in ('page','system','measure')))
    # Known positions from the former counted-grace voice cannot be reused as
    # fixed local anchors. The timing module still preserves explicit edits.
    for event in clock['notes']+clock['rests']:
        key=tuple(event.get(k) for k in ('page','system','measure'))
        if event.get('hand')=='right' and key in affected and 'beat' not in (event.get('manual_fields') or []):
            event['measure_beat']=None
    for staff in clock['staves']:
        if staff.get('hand')!='right':continue
        for measure in staff['measures']:
            if (staff.get('page'),staff.get('system'),measure.get('measure')) in affected:
                measure['timing_resolved']=False
    reflow_right_hand_timing(clock)
    # Source-range selection already uses printed coordinates. Numeric bounds
    # use the same original-to-derived boundary association as source events.
    points=defaultdict(list)
    original={str(n.get('id')):n for n in project.get('notes',[])+project.get('rests',[])}
    for derived in clock['notes']+clock['rests']:
        source=original.get(str(derived.get('id')))
        if source is None or derived.get('hand')!='right' or derived.get('grace_kind') in ('slashed','unmeasured_prefix','unmeasured'):continue
        if finite(source.get('beat')) and finite(derived.get('beat')):
            points[float(source['beat'])].append(float(derived['beat']))
            old_duration,new_duration=_duration(source),_duration(derived)
            if old_duration is not None and new_duration is not None:
                points[source['beat']+old_duration].append(derived['beat']+new_duration)
    pairs=sorted((a,values[0]) for a,values in points.items() if max(values)-min(values)<1e-6)
    def mapped(value):
        if not pairs:return value
        for a,b in pairs:
            if abs(value-a)<1e-6:return b
        for (a,b),(c,d) in zip(pairs,pairs[1:]):
            if a<value<c and d>=b:return b+(value-a)/(c-a)*(d-b)
        return value+(pairs[-1][1]-pairs[-1][0]) if value>pairs[-1][0] else value
    for field in ('start_beat','end_beat'):
        value=clock['selection'].get(field)
        if finite(value):clock['selection'][field]=mapped(value)
    return clock


def _group_override(records,keys):
    result={}
    for key in keys:
        values=[r['override'][key] for r in records if key in r['override']]
        if values:
            if any(v!=values[0] for v in values[1:]):
                raise ValueError('同一特殊奏法组存在不同的练习参数，请重新选择该组')
            result[key]=values[0]
    return result


def realize_project(project,policy=None):
    """Return a complete practice performance; never edit ``project``.

    Errors describe real source gaps.  A successful result accounts for every
    selected RH source head in audio; an unprinted finger remains audio-only.
    """
    policy=normalize_policy(project,policy)
    if policy['mode']!='practice':raise ValueError('此编译器只接收practice模式')
    source_project=project
    originals={str(n.get('id')):n for n in source_project.get('notes',[])}
    project=_practice_timing_project(project)
    scope=export_scope(project);bpm=scope['selection'].get('bpm',120);ms=60000/bpm
    selected=[n for n in scope['notes'] if not n.get('excluded') and n.get('hand')!='left']
    if len(selected)>MAX_EVENTS:raise ValueError('原谱音头超过60000，请缩小所选范围')
    records=[];by_id={};errors=[];estimates=[];features=[];states={};state_items=defaultdict(list);source_map={}
    def error(source,message):
        item=dict(id=source.get('id'),message=message)
        if item not in errors:errors.append(item)
    def feature(kind,ids,group=None,estimated=False,parameters=None,message=None,realized=True,rendering=None):
        ids=list(dict.fromkeys(i for i in ids if _valid_id(i)))
        group=str(group or (kind+':'+','.join(map(str,ids))))
        current=next((f for f in features if f['group_id']==group and f['kind']==kind),None)
        if current is None:
            current=dict(kind=kind,group_id=group,source_note_ids=ids,estimated=bool(estimated),parameters=parameters or {},realized=bool(realized))
            if rendering:current['rendering']=rendering
            features.append(current)
        else:
            current['source_note_ids']=list(dict.fromkeys(current['source_note_ids']+ids));current['estimated']|=bool(estimated)
        if estimated:
            notice=dict(kind=kind,group_id=group,source_note_ids=ids,message=message or LABELS.get(kind,kind)+'采用练习编排估计',parameters=parameters or {})
            prior=next((e for e in estimates if e['group_id']==group and e['kind']==kind),None)
            if prior is None:estimates.append(notice)
            else:prior['source_note_ids']=list(dict.fromkeys(prior['source_note_ids']+ids))
        for pos,ident in enumerate(ids):
            src=by_id.get(str(ident),{}).get('source',{})
            reviewed=(src.get('performance_override') or {}).get('reviewed') is True
            state=dict(group_id=group,kind=kind,label=LABELS.get(kind,kind),estimated=bool(estimated),
                warning_root=bool(estimated and pos==0 and not reviewed),reviewed=reviewed,
                realized=bool(realized),message=message or (LABELS.get(kind,kind)+'已编入练习事件'),parameters=deepcopy(parameters or {}))
            old_item=next((s for s in state_items[str(ident)] if s['group_id']==group and s['kind']==kind),None)
            if old_item is None:state_items[str(ident)].append(state)
            else:old_item.update(state)
            old=states.get(str(ident))
            if old is None or (estimated and (not old['estimated'] or state['warning_root'])):
                states[str(ident)]=state
        return current
    for index,clock_note in enumerate(selected):
        note=originals.get(str(clock_note.get('id')),clock_note)
        ident=note.get('id')
        if not _valid_id(ident) or str(ident) in by_id:
            error(note,'音符编号缺失或重复');continue
        if note.get('hand')!='right':error(note,'需要确认右手归属');continue
        if note.get('finger') is not None and not finger(note['finger']):
            error(note,'原谱指法必须为1至5或未设');continue
        try:pitch=pitch_midi(note.get('pitch'));override=normalize_override(note);marks=_marks(note)
        except ValueError as exc:error(note,str(exc));continue
        beat=clock_note.get('beat')
        if not finite(beat) or beat<0:
            error(note,'开始位置尚未确定');continue
        rec=dict(id=ident,source=note,clock=clock_note,index=index,beat=float(beat),duration=_duration(clock_note),pitch=pitch,
            finger=note.get('finger') if finger(note.get('finger')) else None,
            finger_origin='source' if finger(note.get('finger')) else 'unmarked' if note.get('source_fingering_state')=='unmarked' else 'unresolved',
            marks=marks,override=override,source_ids=[ident],velocity=note.get('velocity',96),gate=1.)
        if combination_pair(marks) is not None:rec['source_has_compound']=True
        if long_mordent_pair(marks) is not None:rec['source_has_long_mordent']=True
        if rec['beat']*ms>MAX_DURATION or (rec['duration'] is not None and rec['duration']*ms>MAX_DURATION):
            error(note,'原谱起拍或音长超过24小时');continue
        if type(rec['velocity']) is not int or not 1<=rec['velocity']<=127:rec['velocity']=96
        by_id[str(ident)]=rec;records.append(rec)
        source_map[str(ident)]=dict(pitch=note.get('pitch'),source_finger=note.get('finger'),source_fingering_state=note.get('source_fingering_state'),
            source_duration_beats=note.get('duration_beats'),source_beat=note.get('beat'),group_ids=[])
        if clock_note is not note:source_map[str(ident)]['derived_performance_beat']=clock_note.get('beat')
    if not records:return dict(version=1,mode='practice',policy=policy,errors=errors or [dict(id=None,message='没有可处理的右手音符')],note_states=states)
    # Enrich span membership; only derived local records receive the marks.
    span_rows=[]
    for span in project.get('performance_spans') or []:
        if not isinstance(span,dict) or span.get('kind') not in KINDS:continue
        options=dict(span.get('options') or {})
        for k in ('start_note_id','end_note_id'):
            if k in span:options[k]=span[k]
        mark=dict(kind=span['kind'],group_id=span.get('id'),position=span.get('position'),options=options,source=span.get('source'))
        ids=span.get('source_note_ids') or [span.get('start_note_id')]
        span_rows.append((span,mark))
        for ident in ids:
            if str(ident) in by_id:by_id[str(ident)]['marks'].append(mark)
    groups=defaultdict(set)
    for rec in records:
        for mark in rec['marks']:
            if mark.get('group_id') is not None:groups[str(mark['group_id'])].add(str(rec['id']))
    disabled_groups=set()
    for gid,ids in groups.items():
        modes={by_id[i]['override']['mode'] for i in ids if 'mode' in by_id[i]['override']}
        if modes=={'auto','written'}:raise ValueError('同一奏法组的练习/原谱模式不一致')
        if modes=={'written'}:
            disabled_groups.add(gid)
            mark=next(m for i in ids for m in by_id[i]['marks'] if str(m.get('group_id'))==gid)
            feature(mark['kind'],[r['id'] for r in records if str(r['id']) in ids],gid,
                message='此组按你的选择保留基础音符，没有自动展开该符号',realized=False,rendering='written-by-user')
    active_span_rows=[(span,mark) for span,mark in span_rows if str(mark.get('group_id')) not in disabled_groups]
    declared_grace_anchors={str(m['options'].get('anchor_id',r['source'].get('main_anchor_id'))) for r in records for m in r['marks'] if m['kind'] in GRACES}
    for rec in records:
        grace_written_disabled=any(m['kind'] in GRACES and (rec['override'].get('mode')=='written' or str(m.get('group_id')) in disabled_groups) for m in rec['marks'])
        rec['marks']=[m for m in rec['marks'] if str(m.get('group_id')) not in disabled_groups]
        if 'kind' in rec['override']:
            wanted=rec['override']['kind'];family=GRACES if wanted in GRACES else ORNAMENTS
            original=next((m for m in rec['marks'] if m['kind'] in family),None)
            group_parameter=str(rec['id']) in declared_grace_anchors and wanted in GRACES and (original is None or original['kind'] not in GRACES)
            if wanted==COMBINATION:
                if combination_pair(rec['marks']) is None:error(rec['source'],'当前音没有可核验的颤音与下波音组合关系')
            elif wanted==LONG_MORDENT:
                if long_mordent_pair(rec['marks']) is None:error(rec['source'],'当前音没有可核验的长下波音墨迹拼接关系')
            elif group_parameter:
                pass  # A principal can carry group parameters without becoming a grace.
            elif original is None or ((original['kind'] in GRACES)!=(wanted in GRACES)):
                error(rec['source'],'练习类型只能修改当前已检测的装饰音族')
            else:
                old_kind=original['kind'];original['options']['detected_kind']=old_kind
                original['kind']=wanted
                if wanted in ORNAMENTS:
                    # An explicit practice choice resolves competing ornament
                    # interpretations; the untouched source keeps every mark.
                    rec['marks']=[m for m in rec['marks'] if m is original or m['kind'] not in ORNAMENTS]
                if (old_kind=='grace_after')!=(wanted=='grace_after'):
                    original['options']['anchor_id']=None
        if rec['override'].get('mode')=='written':
            for mark in rec['marks']:
                feature(mark['kind'],[rec['id']],mark.get('group_id'),message='此处按你的选择保留基础音符，没有自动展开该符号',realized=False,rendering='written-by-user')
            rec['marks']=[]
        rec['grace']=next((m for m in rec['marks'] if m['kind'] in GRACES),None)
        if rec['duration'] is None and rec['grace'] is None:
            if grace_written_disabled:
                error(rec['source'],'此装饰小音没有唯一书面时长，请保留练习编排、明确设置时值或排除此音')
                continue
            rhythm=rec['source'].get('rhythm_evidence') or {}
            nominal=rhythm.get('nominal_duration',rhythm.get('nominal_beats'))
            if finite(nominal) and nominal>0 and 'duration_beats' not in (rec['source'].get('manual_fields') or []):
                rec['duration']=float(nominal)
                feature('duration_evidence',[rec['id']],estimated=True,message='练习音长按已读取的符干/连梁证据估计',parameters=dict(duration_beats=nominal))
            else:error(rec['source'],'原谱音值尚不能确定，请核对该音')
    timing_groups=defaultdict(list)
    for rec in records:
        if rec['clock'].get('timing_estimated'):
            timing_groups[str(rec['clock'].get('timing_source_id') or rec['id'])].append(rec)
            source_map[str(rec['id'])].update(source_timing_estimated=True,source_timing_source_id=rec['source'].get('timing_source_id'))
    for source,group in timing_groups.items():
        ordered=sorted(group,key=lambda r:(str(r['id'])!=source,r['index']))
        message=next((r['clock']['timing_warning'] for r in ordered if r['clock'].get('timing_warning')),'此处起拍沿用右手时间模型的估计，后续按节奏跟随')
        feature('source_timing',[r['id'] for r in ordered],'source-timing:'+source,True,dict(timing_source_id=source),message)
    previous=None
    for rec in sorted(records,key=lambda r:(r['beat'],r['index'])):
        if rec['finger_origin']=='unresolved':
            if policy['estimate_unresolved_fingering'] and rec['override'].get('mode')!='written':
                if previous is not None and previous['finger'] is not None:
                    delta=rec['pitch']-previous['pitch'];f=previous['finger']+(1 if delta>0 else -1 if delta<0 else 0)
                    rec['finger']=min(5,max(1,f)) if abs(delta)<=5 else 3
                else:rec['finger']=3
                rec['finger_origin']='estimated'
                feature('fingering',[rec['id']],estimated=True,message='练习指法为估计，原谱指法未被改写',parameters=dict(performance_finger=rec['finger'],finger_origin='estimated'))
            else:error(rec['source'],'原谱指法仍待核对')
        if rec['finger'] is not None:previous=rec
        source_map[str(rec['id'])].update(performance_finger=rec['finger'],finger_origin=rec['finger_origin'])
    if errors:
        # Unknown ordinary note values are real source gaps, not ornaments.
        # Stop with their source IDs before any group-budget operation; do not
        # turn the validation gap into an empty min()/generic global exception.
        for row in features:row['realized']=False
        for row in states.values():row['realized']=False
        for rows in state_items.values():
            for row in rows:row['realized']=False
        return dict(version=1,mode='practice',policy=policy,errors=errors,estimates=estimates,features=features,note_states=states,performance_complete=False)
    # Build a monotone time map for explicit, not-already-applied quantitative
    # marks and expressive holds.  Source beats and durations remain intact.
    warp=_Warp();unit_groups=defaultdict(list);seen=set()
    for rec in records:
        for mark in rec['marks']:
            kind=mark['kind'];opt=mark['options'];gid=str(mark.get('group_id') or kind+':'+str(rec['id']))
            if kind=='tuplet' and opt.get('already_applied',True) is False:unit_groups[gid].append((rec,mark))
            elif kind=='dots' and opt.get('already_applied',True) is False and rec['duration']:
                count=opt.get('count',1)
                if type(count) is not int or not 1<=count<=3:error(rec['source'],'附点数量不正确');continue
                factor=2-2**(-count);warp.scale(rec['beat'],rec['beat']+rec['duration'],factor)
            elif kind=='ottava' and opt.get('already_applied',True) is False:
                shift=opt.get('semitones',opt.get('shift'))
                if shift not in (-24,-12,12,24):error(rec['source'],'八度移位范围不正确');continue
                rec['pitch']+=shift
                if not 0<=rec['pitch']<=127:error(rec['source'],'移位后的音高超出范围')
    for gid,members in sorted(unit_groups.items(),key=lambda p:min(r['beat'] for r,m in p[1])):
        actual=members[0][1]['options'].get('actual');normal=members[0][1]['options'].get('normal')
        if type(actual) is not int or type(normal) is not int or not 2<=actual<=16 or not 1<=normal<=16:
            for rec,_ in members:error(rec['source'],'连音比例不正确')
            continue
        good=[r for r,m in members if r['duration']]
        if good:warp.scale(min(r['beat'] for r in good),max(r['beat']+r['duration'] for r in good),normal/actual)
    pauses=defaultdict(list)
    def pause(start,duration,owner,mark,source_event=None,clock=None):
        if not finite(start) or not finite(duration) or duration<=0:return
        if start+duration<=scope['start_beat'] or (scope.get('end_beat') is not None and start>=scope['end_beat']):return
        pauses[round(start+duration,9)].append(dict(start=start,duration=duration,owner=owner,mark=mark,source=source_event or owner['source'],clock=clock))
    for rec in records:
        for mark in rec['marks']:
            if mark['kind']!='fermata' or not rec['duration']:continue
            opt=mark['options']
            if opt.get('source_anchor_unresolved'):
                error(rec['source'],'延长记号的谱面声部归属尚未确定');continue
            if opt.get('anchor_rest_id') is not None or (opt.get('anchor_note_id') is not None and str(opt['anchor_note_id'])!=str(rec['id'])):continue
            pause(rec['beat'],rec['duration'],rec,mark)
    all_sources={str(e.get('id')):e for e in project.get('notes',[])+project.get('rests',[]) if _valid_id(e.get('id'))}
    pause_rows=list(active_span_rows)
    for event_source in project.get('rests',[])+[n for n in project.get('notes',[]) if n.get('hand')=='left']:
        for mark in _marks(event_source):
            if mark['kind']=='fermata':
                mark['options']['anchor_note_id' if event_source in project.get('notes',[]) else 'anchor_rest_id']=event_source['id']
                pause_rows.append((event_source,mark))
    for span,mark in pause_rows:
        if mark['kind']!='fermata' or str(mark.get('group_id')) in disabled_groups:continue
        opt=mark['options'];ident=opt.get('rest_id',opt.get('anchor_rest_id',opt.get('anchor_note_id')))
        event_source=all_sources.get(str(ident))
        if event_source is None:continue
        coordinates=tuple(event_source.get(k) for k in scope['source_fields'])
        if coordinates and all(type(v) is int and v>=1 for v in coordinates) and not scope['source_start']<=coordinates<=scope['source_end']:continue
        peers=[r for r in records if all(r['source'].get(k)==event_source.get(k) for k in ('page','system','measure'))]
        clock_events=[e for e in all_sources.values() if e.get('hand')=='right' and
            all(e.get(k)==event_source.get(k) for k in ('page','system','measure'))]
        bases=[e.get('measure_start_beat') if finite(e.get('measure_start_beat')) else e['beat']-e['measure_beat']
               for e in clock_events if finite(e.get('measure_start_beat')) or (finite(e.get('beat')) and finite(e.get('measure_beat')))]
        bases.extend(m['start_beat'] for m in project.get('right_hand_timing',{}).get('measures',[])
            if all(m.get(k)==event_source.get(k) for k in ('page','system','measure')) and finite(m.get('start_beat')))
        # A selected RH measure anchors a LH pause. Unresolved LH global values
        # never replace the RH timeline.
        owner=next((by_id[str(i)] for i in span.get('source_note_ids',[]) if str(i) in by_id),peers[0] if peers else None)
        if owner is None and bases and max(bases)-min(bases)<1e-6:
            owner=next((r for r in sorted(records,key=lambda r:r['beat']) if r['beat']>=bases[0]),records[-1])
        if owner is None and event_source.get('hand')!='left' and finite(event_source.get('beat')):
            owner=next((r for r in records if r['beat']>=event_source['beat']),records[-1])
        if owner is None and records:
            # 11-05：左手的延长记号找不到同一小节的右手音时，按通用读法算到同一行、横向最近的右手音上（两手一起停）
            def _x(e):
                b=e.get('bbox') or e.get('glyph_bbox')
                return (b[0]+b[2])/2 if isinstance(b,(list,tuple)) and len(b)>=4 and all(finite(v) for v in b[:4]) else None
            sx=_x(event_source)
            same=[r for r in records if r['source'].get('page')==event_source.get('page') and r['source'].get('system')==event_source.get('system') and _x(r['source']) is not None]
            if sx is not None and same:
                owner=min(same,key=lambda r:abs(_x(r['source'])-sx))
                if not finite(event_source.get('beat')) or event_source.get('hand')=='left':
                    event_source=owner['source']
        if owner is None:
            error(records[-1]['source'],'延长记号所在小节缺少可确认的右手时间锚，请核对该小节休止或起拍')
            continue
        if opt.get('source_anchor_unresolved'):
            error(owner['source'],'延长记号的谱面声部归属尚未确定');continue
        # 11-04：延长记号印在小音符（倚音）上方时，按通用读法算到它的主音上；小音符本身没有固定时值
        if event_source.get('grace_kind') in ('slashed','unmeasured_prefix','unmeasured') and str(event_source.get('main_anchor_id')) in all_sources:
            event_source=all_sources[str(event_source['main_anchor_id'])]
            owner=by_id.get(str(event_source.get('id')),owner)
        duration=_duration(event_source)
        if duration is None:
            error(owner['source'],'延长记号的基准音长尚未确定');continue
        start=event_source.get('beat');column_alignment=None
        if event_source.get('hand')=='left' or not finite(start):
            local_end=opt.get('local_end_beat',opt.get('group_end'))
            local=event_source.get('measure_beat')
            if bases and max(bases)-min(bases)<1e-6 and (finite(local_end) or finite(local)):
                start=bases[0]+(local_end-duration if finite(local_end) else local)
            else:
                # Printed grand-staff fermatas can repeat the same pause on
                # several LH heads/rests whose own clock is unresolved. A
                # matching explicit group on a known RH note/rest is already
                # a sufficient anchor; do not require the LH clock as well.
                gid=mark.get('group_id')
                candidates=[]
                if gid is not None:
                    for event in all_sources.values():
                        if event.get('hand')!='right' or not finite(event.get('beat')):continue
                        if not all(event.get(k)==event_source.get(k) for k in ('page','system','measure')):continue
                        value=_duration(event)
                        if value is None:continue
                        if any(m['kind']=='fermata' and m.get('group_id')==gid for m in _marks(event)):
                            candidates.append((event['beat'],value))
                ends={round(a+d,9) for a,d in candidates}
                if len(ends)==1:
                    # Shared fermatas establish an ending, not equal written
                    # values in different voices. Keep this source's own value.
                    start=next(iter(ends))-duration
                else:
                    # A uniquely printed simultaneous RH note/rest can anchor
                    # an otherwise unclocked LH pause. Infer performance only:
                    # known/explicitly cleared LH positions are never replaced.
                    aligned=[];origin=event_source.get('origin') or []
                    staff=next((s for s in project.get('staves',[]) if s.get('id')==event_source.get('staff')),{})
                    lines=staff.get('lines') or [];gap=abs(lines[1]-lines[0]) if len(lines)>=2 else None
                    unset=not finite(event_source.get('beat')) and not finite(local) and not set(event_source.get('manual_fields') or [])&{'beat','measure_beat'}
                    if unset and origin and finite(origin[0]) and finite(gap) and gap>0 and bases and max(bases)-min(bases)<1e-6:
                        for event in clock_events:
                            printed=event.get('origin') or [];value=_duration(event)
                            if (not printed or not finite(printed[0]) or abs(printed[0]-origin[0])>=.35*gap
                                or not finite(event.get('beat')) or not finite(event.get('measure_beat'))
                                or abs(event['beat']-bases[0]-event['measure_beat'])>1e-6
                                or value is None or abs(value-duration)>1e-6 or event.get('grace_kind')):continue
                            aligned.append(event)
                    starts={round(e['beat'],9) for e in aligned}
                    if len(starts)!=1:
                        error(owner['source'],'延长记号的右手小节时间锚尚未确定');continue
                    start=aligned[0]['beat']
                    column_alignment=dict(method='unique-printed-column-to-rh-event',anchor_source_ids=[str(e['id']) for e in aligned],
                        column_alignment=dict(source_id=str(event_source['id']),source_x=origin[0],staff_gap=gap,tolerance_gaps=.35))
        clock=dict(page=event_source.get('page'),system=event_source.get('system'),measure=event_source.get('measure'),
            start_beat=bases[0] if bases and max(bases)-min(bases)<1e-6 else None,
            source_ids=[str(e['id']) for e in clock_events],method='right-hand-measure-or-rest')
        if column_alignment:clock.update(column_alignment)
        pause(start,duration,owner,mark,event_source,clock)
    for end,rows in sorted(pauses.items()):
        # One shared pause at an ending, even with marks on several voices.
        chosen=min(rows,key=lambda r:(r['duration'],r['owner']['index']))
        owners=list({str(r['owner']['id']):r['owner'] for r in rows}.values())
        override=_group_override(owners,('hold_factor',));factor=override.get('hold_factor',chosen['mark']['options'].get('factor',policy['fermata_factor']))
        if not finite(factor) or not 1<=factor<=8:
            error(chosen['owner']['source'],'延长倍率不正确');continue
        warp.hold(chosen['start'],end,factor)
        group=str(chosen['mark'].get('group_id') or 'fermata-end:'+str(end))
        feature('fermata',[r['id'] for r in owners],group,True,dict(hold_factor=factor,pause_end_beat=end,
            pause_start_beat=chosen['start'],pause_duration_beats=chosen['duration'],
            anchor_source_ids=list(dict.fromkeys(str(r['source']['id']) for r in rows)),
            source_anchors=[{k:r['source'].get(k) for k in ('id','hand','page','system','measure','beat','measure_beat','duration_beats')} for r in rows],
            right_hand_clock=chosen['clock'],
            clock='right-hand-relative'),
            '延长记号按练习倍率处理，同一暂停点只延长一次，后续起音共同跟随')
    for rec in records:
        rec['start']=warp(rec['beat']);rec['end']=warp(rec['beat']+rec['duration']) if rec['duration'] else None
    scope_start=warp(scope['start_beat'])
    grace_groups=defaultdict(list);grace_anchor_groups={}
    for rec in records:
        mark=rec['grace']
        if not mark:continue
        if any(k in ('duration_beats','beat') for k in (rec['source'].get('manual_fields') or [])) and rec['duration']:
            rec['grace']=None;continue
        opt=mark['options'];anchor=by_id.get(str(opt.get('anchor_id',rec['source'].get('main_anchor_id'))))
        if anchor is None:
            after=mark['kind']=='grace_after'
            peers=[r for r in records if not r['grace'] and r['duration'] and
                all(r['source'].get(k)==rec['source'].get(k) for k in ('page','system','measure')) and
                ((r['index']<rec['index']) if after else (r['index']>rec['index']))]
            if peers:anchor=max(peers,key=lambda r:r['index']) if after else min(peers,key=lambda r:r['index'])
        if anchor is None or not anchor['duration']:
            error(rec['source'],'装饰音的主音锚尚不明确');continue
        rec['anchor']=anchor
        gid=str(mark.get('group_id') or rec['source'].get('grace_group') or 'grace:'+str(anchor['id']))
        position='after' if mark['kind']=='grace_after' or rec['override'].get('placement')=='after' else 'prefix'
        key=(str(anchor['id']),position)
        gid=grace_anchor_groups.setdefault(key,gid)
        rec['grace_performance_group']=gid
        grace_groups[gid].append(rec)
    grace_events=[]
    for gid,members in grace_groups.items():
        members.sort(key=lambda r:(r['grace']['options'].get('order',r['index']),r['index']))
        anchor=members[0]['anchor'];kind=members[0]['grace']['kind'];override=_group_override(members+[anchor],('placement','borrow_ratio','reviewed'))
        kinds={r['override']['kind'] for r in members+[anchor] if r['override'].get('kind') in GRACES}
        if len(kinds)>1:raise ValueError('同一倚音组存在不同练习类型')
        if kinds:kind=next(iter(kinds))
        if any(r['anchor'] is not anchor for r in members):
            for rec in members:error(rec['source'],'装饰音组含多个主音锚')
            continue
        total=anchor['end']-anchor['start'];placement=override.get('placement')
        if placement is None:placement='after' if kind=='grace_after' else 'before' if kind=='grace_short' else 'on'
        if kind=='grace_long':
            dotted=(anchor['source'].get('rhythm_evidence') or {}).get('dots',0)
            fraction=override.get('borrow_ratio',2/3 if dotted else .5);borrow=total*fraction
        elif 'borrow_ratio' in override:borrow=total*override['borrow_ratio']
        else:borrow=min(total*.25,policy['grace_ms']/ms)
        borrow=min(borrow,total*.8)
        columns=[]
        for rec in members:
            order=rec['grace']['options'].get('order',rec['index'])
            if not columns or columns[-1][0]!=order:columns.append((order,[]))
            columns[-1][1].append(rec)
        if borrow*ms<len(columns)+1:
            for rec in members:error(rec['source'],'装饰音组时间过短，不能保留每个攻击')
            continue
        if placement=='before' and anchor['start']-borrow<scope_start-1e-8:placement='on'
        if placement=='before':
            start=anchor['start']-borrow
            for prior in records:
                if prior is anchor or prior['grace'] or prior['end'] is None:continue
                anchor_voice=anchor['source'].get('voice');prior_voice=prior['source'].get('voice')
                if anchor_voice is not None and prior_voice!=anchor_voice:continue
                if anchor_voice is None and anchor['source'].get('staff') is not None and prior['source'].get('staff')!=anchor['source'].get('staff'):continue
                if prior['start']<start and start<prior['end']<=anchor['start']+1e-8:
                    prior['end']=start
        elif placement=='after':start=anchor['end']-borrow;anchor['end']=start
        else:start=anchor['start'];anchor['start']+=borrow
        for index,(_,column) in enumerate(columns):
            for rec in column:
                rec['start']=start+borrow*index/len(columns);rec['end']=start+borrow*(index+1)/len(columns)
                grace_events.append(rec)
        params=dict(placement=placement,borrow_ratio=borrow/total,performance_finger=members[0]['finger'],finger_origin=members[0]['finger_origin'])
        feature(kind,[r['id'] for r in members]+[anchor['id']],gid,True,params,'装饰音已借用主音或前音时间，不增加原小节拍数；分配为练习估计')
    arps=defaultdict(list)
    for rec in records:
        for mark in rec['marks']:
            if mark['kind']=='arpeggio':
                gid=str(mark.get('group_id') or 'arp:'+str((rec['source'].get('staff'),rec['source'].get('measure'),rec['beat'])))
                arps[gid].append((rec,mark))
    for gid,items in arps.items():
        unique={str(r['id']):(r,m) for r,m in items};items=list(unique.values())
        descending=items[0][1]['options'].get('direction') in ('down','descending')
        items.sort(key=lambda p:p[0]['pitch'],reverse=descending)
        if len(items)<2:
            feature('arpeggio',[r['id'] for r,m in items],gid,
                parameters=dict(effect='neutral_right_hand_subset',selected_heads=len(items)),
                message='右手选区内只有一个音头，无需拆开起音；此处不计为已验证的琶音展开',
                realized=False,rendering='neutral-right-hand-subset')
            continue
        start=max(r['start'] for r,m in items)
        if any(r['end'] is None for r,m in items):
            for rec,_ in items:error(rec['source'],'琶音组的演奏音长尚未确定')
            continue
        available=min(r['end']-start for r,m in items)
        if available<=0:
            for rec,_ in items:error(rec['source'],'琶音组没有共同的演奏时间窗口，请核对该组')
            continue
        override=_group_override([r for r,m in items],('borrow_ratio',))
        spread=available*override['borrow_ratio'] if 'borrow_ratio' in override else min(available*.25,policy['arpeggio_step_ms']/ms*(len(items)-1))
        for index,(rec,_) in enumerate(items):rec['start']=start+spread*index/(len(items)-1)
        feature('arpeggio',[r['id'] for r,m in items],gid,True,dict(direction='down' if descending else 'up',spread_ms=spread*ms,borrow_ratio=spread/available),'琶音各音已依次起音并保持，展开速度为练习估计')
    audio=[];motion_extra=[];handled=set();tremolos=defaultdict(list)
    def event(rec,start,end,pitch=None,f=None,kind='plain',group=None,ids=None,no_motion=False):
        if rec.get('grace') and end is not None:end=min(end,rec['end'])
        if end is None or end<=start+1e-10:return
        if len(audio)>=MAX_EVENTS:raise ValueError('练习展开超过60000次攻击，请缩小范围')
        audio.append(dict(start=start,end=end,pitch=rec['pitch'] if pitch is None else pitch,
            finger=rec['finger'] if f is None else f,velocity=rec['velocity'],source_note_ids=ids or list(rec['source_ids']),
            group_id=str(group or kind+':'+str(rec['id'])),kind=kind,no_motion=no_motion))
        if rec.get('grace') and kind!='grace':audio[-1]['parent_group_id']=rec['grace_performance_group']
    def auxiliary(rec,pitch,direction):
        if rec['finger'] is None:return None
        explicit=rec['override'].get('aux_finger')
        if explicit is not None:return explicit
        candidate=rec['finger']+direction
        return candidate if 1<=candidate<=5 else rec['finger']-direction
    for rec in records:
        if rec['grace']:continue
        for mark in rec['marks']:
            if mark['kind']=='tremolo_alternating':
                tremolos[str(mark.get('group_id') or rec['source'].get('tremolo_group') or 'tremolo:'+str(rec['id']))].append((rec,mark))
    for gid,items in tremolos.items():
        unique={str(r['id']):(r,m) for r,m in items};items=list(unique.values())
        opt=items[0][1]['options'];start=min(r['start'] for r,m in items)
        span=opt.get('span_beats',items[0][0]['source'].get('tremolo_span_beats'))
        if not finite(span) or span<=0:span=max((r['end'] or r['start'])-r['start'] for r,m in items)
        group_override=_group_override([r for r,m in items],('rate_hz',))
        step=bpm/(60*group_override['rate_hz']) if 'rate_hz' in group_override else opt.get('step_beats',items[0][0]['source'].get('tremolo_step_beats'))
        strokes=opt.get('strokes',opt.get('slash_count'))
        if not finite(step) or step<=0:step=2**(-strokes) if type(strokes) is int and 1<=strokes<=5 else bpm/(60*items[0][0]['override'].get('rate_hz',policy['ornament_rate_hz']))
        sides={m['options'].get('side',r['source'].get('tremolo_side')) for r,m in items}
        if not sides.issubset({0,1}) or not sides:
            for r,m in items:error(r['source'],'交替震音的两侧尚未确定')
            continue
        count=max(2 if sides=={0,1} else 1,math.ceil(span/step-1e-9))
        if count>MAX_EVENTS-len(audio):raise ValueError('交替震音展开超过60000次攻击')
        step=span/count
        for pulse in range(count):
            for rec,mark in items:
                if mark['options'].get('side',rec['source'].get('tremolo_side'))!=pulse%2:continue
                event(rec,start+pulse*step,start+min(span,(pulse+1)*step),kind='tremolo_alternating',group=gid)
        handled.update(str(r['id']) for r,m in items)
        feature('tremolo_alternating',[r['id'] for r,m in items],gid,True,dict(step_beats=step,span_beats=span,rate_hz=bpm/(60*step)),'交替震音已展开，按书面细分或练习速度交替，非唯一演奏速度')
    for rec in records:
        if str(rec['id']) in handled:continue
        if rec['end'] is None or rec['end']<=rec['start']:
            if not rec['grace']:error(rec['source'],'实际演奏时间尚未确定')
            continue
        kinds={m['kind'] for m in rec['marks']}
        if 'staccatissimo' in kinds:rec['gate']=.25
        elif 'staccato' in kinds:rec['gate']=.5
        elif 'tenuto' in kinds:rec['gate']=1.
        if 'accent' in kinds:rec['velocity']=min(127,round(rec['velocity']*1.2))
        if 'gate_ratio' in rec['override']:rec['gate']=rec['override']['gate_ratio']
        if 'velocity' in rec['override']:rec['velocity']=rec['override']['velocity']
        for kind in kinds-ORNAMENTS-GRACES-{'arpeggio','tremolo_alternating','fermata','pedal','tie'}:
            parameters={}
            if kind in ('staccato','staccatissimo','tenuto'):parameters['gate_ratio']=rec['gate']
            if kind=='accent':parameters['velocity']=rec['velocity']
            feature(kind,[rec['id']],next((m.get('group_id') for m in rec['marks'] if m['kind']==kind),None),parameters=parameters)
        ornament_rows=[m for m in rec['marks'] if m['kind'] in ORNAMENTS]
        long_mordent=long_mordent_pair(ornament_rows)
        if long_mordent is not None:
            extension,lower,notation_id=long_mordent
            duration=rec['end']-rec['start'];rate=rec['override'].get('rate_hz',policy['ornament_rate_hz'])
            if duration*ms<5:
                error(rec['source'],'长下波音预算不足以保留五次起音');continue
            try:lower_pitch=_neighbor(rec,-1,lower['options'],generic_accidental=True)
            except ValueError as exc:error(rec['source'],str(exc));continue
            lower_finger=auxiliary(rec,lower_pitch,-1);unit=min(bpm/(60*rate),duration/5)
            pitches=[rec['pitch'],lower_pitch,rec['pitch'],lower_pitch,rec['pitch']]
            for i,pitch in enumerate(pitches):
                end=rec['end'] if i==4 else rec['start']+(i+1)*unit
                event(rec,rec['start']+i*unit,min(rec['end'],rec['start']+i*unit+(end-rec['start']-i*unit)*rec['gate']),
                    pitch,lower_finger if i%2 else rec['finger'],'mordent_lower',lower['group_id'])
            common=dict(kind=LONG_MORDENT,notation_id=notation_id,notation_kind=LONG_MORDENT,
                component_group_ids=[extension['group_id'],lower['group_id']],rate_hz=rate,attack_count=5,
                aux_finger=rec['override'].get('aux_finger'),performance_finger=rec['finger'],finger_origin=rec['finger_origin'],
                candidates=['mordent_upper','mordent_lower',LONG_MORDENT])
            feature('mordent_upper',[rec['id']],extension['group_id'],parameters=dict(common,notation_role='wave_extension'),
                message='原始短波形是同一长下波音的延长墨迹，保留来源；不单独演奏上波音',realized=False,rendering='notation-ink-component')
            params=dict(common,notation_role='lower_mordent')
            if rec['grace']:params.update(parent_group_id=rec['grace_performance_group'],window_duration_ms=duration*ms)
            feature('mordent_lower',[rec['id']],lower['group_id'],True,params,
                '一枚长下波音按主音—下邻音—主音—下邻音—主音编排；五次起音和速度为可修改练习估计，后续起拍不变')
            continue
        compound=combination_pair(ornament_rows)
        if compound is not None and not rec['grace']:
            trill,lower,combo_id=compound
            duration=rec['end']-rec['start'];rate=rec['override'].get('rate_hz',policy['ornament_rate_hz'])
            ratio=rec['override'].get('borrow_ratio',1/3)
            if duration*ms<5:
                error(rec['source'],'组合装饰音预算不足以保留两种奏法的全部起音');continue
            split=rec['end']-duration*ratio;step=bpm/(60*rate)
            if (split-rec['start'])*ms<2 or (rec['end']-split)*ms<3:
                error(rec['source'],'组合装饰音的主体或收尾预算不足以保留全部起音');continue
            count=max(2,2*math.floor((split-rec['start'])/(2*step)+1e-9))
            if count+3+len(audio)>MAX_EVENTS:raise ValueError('练习展开超过60000次攻击')
            try:upper_pitch=_neighbor(rec,1,trill['options']);lower_pitch=_neighbor(rec,-1,lower['options'],generic_accidental=True)
            except ValueError as exc:error(rec['source'],str(exc));continue
            upper_finger=auxiliary(rec,upper_pitch,1)
            lower_finger=(rec['override'].get('lower_aux_finger') or (rec['finger']-1 if rec['finger']>1 else 2)) if rec['finger'] is not None else None
            if rec['finger'] is not None and (upper_finger==rec['finger'] or lower_finger==rec['finger']):
                error(rec['source'],'组合装饰音的辅助手指须与主音手指不同');continue
            unit=(split-rec['start'])/count
            for i in range(count):
                event(rec,rec['start']+i*unit,rec['start']+(i+rec['gate'])*unit,
                    rec['pitch'] if i%2==0 else upper_pitch,rec['finger'] if i%2==0 else upper_finger,
                    'trill',trill['group_id'])
            unit=(rec['end']-split)/3
            for i,pitch in enumerate((rec['pitch'],lower_pitch,rec['pitch'])):
                event(rec,split+i*unit,split+(i+rec['gate'])*unit,pitch,
                    lower_finger if i==1 else rec['finger'],'mordent_lower',lower['group_id'])
            common=dict(kind=COMBINATION,combination_id=combo_id,component_group_ids=[trill['group_id'],lower['group_id']],
                rate_hz=rate,borrow_ratio=ratio,aux_finger=rec['override'].get('aux_finger'),
                lower_aux_finger=rec['override'].get('lower_aux_finger'),
                upper_performance_finger=upper_finger,lower_performance_finger=lower_finger,
                upper_finger_origin='audio-only' if rec['finger'] is None else 'user' if rec['override'].get('aux_finger') else 'estimated',
                lower_finger_origin='audio-only' if rec['finger'] is None else 'user' if rec['override'].get('lower_aux_finger') else 'estimated',
                sequence=['trill','mordent_lower'],candidates=['trill','mordent_lower',COMBINATION])
            for mark,phase in ((trill,'body'),(lower,'termination')):
                feature(mark['kind'],[rec['id']],mark['group_id'],True,dict(common,phase=phase),
                    '按练习估计先颤音、再主音—下邻音—主音收尾，速度和尾段可改，后续起拍不变')
            continue
        if len({m['kind'] for m in ornament_rows})>1:
            error(rec['source'],'同一音读取到多个不同装饰奏法，需确认符号后再展开')
            candidate=ornament_rows[0];kind=candidate['kind'];gid=candidate.get('group_id')
            choices=sorted({m['kind'] for m in ornament_rows})
            feature(kind,[rec['id']],gid,True,dict(kind=kind,candidates=choices),
                '同一音检测到'+ '、'.join(LABELS[k] for k in choices)+'；请在练习解释中选一种，原谱符号全部保留',realized=False)
            item=next(s for s in state_items[str(rec['id'])] if s['kind']==kind and s['group_id']==str(gid or kind+':'+str(rec['id'])))
            item['editable_fields']=['kind']
            states[str(rec['id'])]=dict(item,items=[dict(item,parameters=dict(item['parameters']))])
            continue
        ornament=next(iter(ornament_rows),None)
        duration=rec['end']-rec['start']
        if ornament is None:
            event(rec,rec['start'],rec['start']+duration*rec['gate'],kind='grace' if rec['grace'] else 'plain',
                group=rec.get('grace_performance_group'))
            continue
        kind=ornament['kind'];opt=ornament['options'];gid=str(ornament.get('group_id') or kind+':'+str(rec['id']))
        if rec['grace'] and kind=='glissando':
            error(rec['source'],'倚音上的滑音尚无可独立核验的借时逐键解释，请确认该奏法');continue
        rate=rec['override'].get('rate_hz',opt.get('rate_hz',policy['ornament_rate_hz']))
        if not finite(rate) or not 1<=rate<=20:error(rec['source'],'装饰速度不正确');continue
        step=bpm/(60*rate);upper=lower=None
        try:
            if kind in ('mordent_upper','turn','inverted_turn','trill'):upper=_neighbor(rec,1,opt)
            if kind in ('mordent_lower','turn','inverted_turn'):lower=_neighbor(rec,-1,opt,generic_accidental=kind=='mordent_lower')
        except ValueError as exc:error(rec['source'],str(exc));continue
        if kind.startswith('mordent'):
            other=upper if kind.endswith('upper') else lower;direction=1 if kind.endswith('upper') else -1
            unit=min(step,duration/3);pitches=[rec['pitch'],other,rec['pitch']];times=[rec['start'],rec['start']+unit,rec['start']+2*unit,rec['end']]
        elif kind in ('turn','inverted_turn'):
            pitches=[upper,rec['pitch'],lower,rec['pitch']] if kind=='turn' else [lower,rec['pitch'],upper,rec['pitch']]
            placement=rec['override'].get('placement','after' if opt.get('delayed') else ornament.get('position','on'))
            delay=duration*.5 if placement in ('after','between') else 0
            if delay:event(rec,rec['start'],rec['start']+delay,kind=kind,group=gid)
            unit=min(step,(duration-delay)/4);times=[rec['start']+delay+i*unit for i in range(4)]+[rec['end']]
        elif kind=='trill':
            count=max(2,math.ceil(duration/step-1e-9));unit=duration/count
            if count>MAX_EVENTS-len(audio):raise ValueError('练习展开超过60000次攻击')
            pitches=[rec['pitch'] if i%2==0 else upper for i in range(count)];times=[rec['start']+i*unit for i in range(count+1)]
        elif kind=='tremolo_single':
            strokes=opt.get('strokes',opt.get('slash_count'));written_step=opt.get('step_beats')
            if 'rate_hz' in rec['override']:written_step=step
            elif not finite(written_step) or written_step<=0:written_step=2**(-strokes) if type(strokes) is int and 1<=strokes<=5 else step
            count=max(2,math.ceil(duration/written_step-1e-9));unit=duration/count
            if count>MAX_EVENTS-len(audio):raise ValueError('练习展开超过60000次攻击')
            pitches=[rec['pitch']]*count;times=[rec['start']+i*unit for i in range(count+1)]
        else:
            target=by_id.get(str(opt.get('target_id',opt.get('end_note_id'))))
            try:end_pitch=target['pitch'] if target else pitch_midi(opt.get('end_pitch'))
            except ValueError:error(rec['source'],'滑音终点音高尚不明确');continue
            finish=target['start'] if target and target['start']>rec['start'] else rec['end']
            direction=1 if end_pitch>=rec['pitch'] else -1
            keyset=opt.get('keyset','white');allowed={0,2,4,5,7,9,11} if keyset=='white' else {1,3,6,8,10} if keyset=='black' else set(range(12))
            pitches=[p for p in range(rec['pitch'],end_pitch+direction,direction) if p%12 in allowed or p in (rec['pitch'],end_pitch)]
            if target and pitches and pitches[-1]==end_pitch:pitches.pop()
            if not pitches:pitches=[rec['pitch']]
            unit=(finish-rec['start'])/len(pitches);times=[rec['start']+i*unit for i in range(len(pitches)+1)]
            motion_extra.append(dict(start=rec['start'],end=finish,pitch=rec['pitch'],finger=rec['finger'],velocity=rec['velocity'],source_note_ids=rec['source_ids'],group_id=gid))
        if len(pitches)+len(audio)>MAX_EVENTS:raise ValueError('练习展开超过60000次攻击')
        for i,pitch in enumerate(pitches):
            direction=1 if pitch>rec['pitch'] else -1 if pitch<rec['pitch'] else 0
            f=rec['finger'] if kind=='glissando' else auxiliary(rec,pitch,direction) if direction else rec['finger']
            event(rec,times[i],times[i]+(times[i+1]-times[i])*rec['gate'],pitch,f,kind,gid,no_motion=kind=='glissando')
        params=dict(rate_hz=rate,aux_finger=rec['override'].get('aux_finger'),performance_finger=rec['finger'],finger_origin=rec['finger_origin'])
        if rec['grace']:
            attacks=len(pitches)+int(kind in ('turn','inverted_turn') and bool(delay))
            params.update(parent_group_id=rec['grace_performance_group'],window_duration_ms=duration*ms,
                attack_count=attacks,actual_rate_hz=attacks*bpm/(60*duration))
            if kind=='trill':params['minimum_two_attacks_applied']=duration<2*step
        source_choices=sorted({m['kind'] for m in _marks(rec['source']) if m['kind'] in ORNAMENTS})
        if rec.get('source_has_compound'):source_choices.append(COMBINATION)
        if rec.get('source_has_long_mordent'):source_choices.append(LONG_MORDENT)
        if len(source_choices)>1:params['candidates']=source_choices
        if kind in ('turn','inverted_turn'):params['placement']=placement
        if kind=='glissando':
            params=dict(motion='source_finger_hold_not_hand_translation',keyset=keyset,
                        performance_finger=rec['finger'],finger_origin=rec['finger_origin'],
                        actual_rate_hz=len(pitches)*bpm/(60*(finish-rec['start'])))
        message=('滑音已生成逐键声音，按起终点安排；所选手指保持，横向移手由人完成'
                 if kind=='glissando' else LABELS[kind]+'已生成实际声音事件；速度及辅助指法为可修改的练习估计')
        feature(kind,[rec['id']],gid,True,params,message)
    # Explicit valid ties merge sounding attacks, while the underlying source
    # finger intervals retain any written finger substitution.
    motion_input=[dict(e) for e in audio if not e['no_motion'] and finger(e['finger'])]+motion_extra
    linked=set()
    for rec in records:
        for mark in rec['marks']:
            if mark['kind']!='tie':continue
            target=by_id.get(str(mark['options'].get('target_id',mark['options'].get('end_note_id'))))
            if target is None:continue
            pair=(str(rec['id']),str(target['id']))
            if pair in linked:continue
            linked.add(pair)
            if rec['pitch']!=target['pitch'] or rec['end'] is None or abs(rec['end']-target['start'])>1e-6:
                if rec['source'].get('tie_to') is not None:error(rec['source'],'延音线须连接连续同音')
                continue
            left=[e for e in audio if rec['id'] in e['source_note_ids'] and e['kind']=='plain']
            right=[e for e in audio if target['id'] in e['source_note_ids'] and e['kind']=='plain']
            if len(left)==len(right)==1:
                a,b=left[0],right[0];a['end']=max(a['end'],b['end']);a['source_note_ids']=list(dict.fromkeys(a['source_note_ids']+b['source_note_ids']));audio.remove(b)
                if a['finger']!=b['finger']:a['finger']=None
                ma=[e for e in motion_input if rec['id'] in e['source_note_ids']]
                mb=[e for e in motion_input if target['id'] in e['source_note_ids']]
                if len(ma)==len(mb)==1 and ma[0]['finger']==mb[0]['finger']:
                    ma[0]['end']=max(ma[0]['end'],mb[0]['end']);ma[0]['source_note_ids']=list(dict.fromkeys(ma[0]['source_note_ids']+mb[0]['source_note_ids']));motion_input.remove(mb[0])
                elif len(ma)==1 and not mb and target['finger'] is None:
                    ma[0]['end']=max(ma[0]['end'],target['end']);ma[0]['source_note_ids']=list(dict.fromkeys(ma[0]['source_note_ids']+target['source_ids']))
                    target['finger']=ma[0]['finger'];target['finger_origin']='tie-continuation'
                    source_map[str(target['id'])].update(performance_finger=target['finger'],finger_origin='tie-continuation')
                feature('tie',a['source_note_ids'],mark.get('group_id'))
    # Slurs connect distinct written attacks, not merge them into one note.
    for rec in records:
        for mark in rec['marks']:
            if mark['kind']!='slur':continue
            target=by_id.get(str(mark['options'].get('target_id',mark['options'].get('end_note_id'))))
            if target is None:continue
            for e in audio:
                if rec['id'] in e['source_note_ids'] and rec['pitch']!=target['pitch']:
                    e['end']=max(e['end'],target['start']+policy['legato_overlap_ms']/ms)
            feature('slur',[rec['id'],target['id']],mark.get('group_id'),True,dict(overlap_ms=policy['legato_overlap_ms']),'连音保持独立起音，声音衔接使用练习连奏量')
    ends=[r['beat']+((r['duration'] or 0) if not r['grace'] else 0) for r in records]
    for rest in project.get('rests',[]):
        beat=rest.get('beat');duration=_duration(rest)
        if rest.get('hand')=='left' or not finite(beat) or duration is None:continue
        coordinates=tuple(rest.get(k) for k in scope['source_fields'])
        if coordinates and all(type(v) is int and v>=1 for v in coordinates) and not scope['source_start']<=coordinates<=scope['source_end']:continue
        if beat+duration<=scope['start_beat'] or (scope.get('end_beat') is not None and beat>=scope['end_beat']):continue
        ends.append(beat+duration)
    if scope.get('end_beat') is not None:ends.append(scope['end_beat'])
    elif not scope['source_fields'] and finite(project.get('written_duration_beats')):ends.append(project['written_duration_beats'])
    source_end=max(ends)
    # Pedal sustains sound only.  It must never hold a finger or delay an attack.
    pedals=[]
    for span,mark in active_span_rows:
        if mark['kind']!='pedal':continue
        opt=mark['options'];a=by_id.get(str(opt.get('start_note_id')));b=by_id.get(str(opt.get('release_note_id',opt.get('end_note_id'))))
        if a is None:
            members=[by_id[str(i)] for i in span.get('source_note_ids',[]) if str(i) in by_id]
            if members:a=min(members,key=lambda r:r['start'])
        lo=warp(opt['start_beat']) if finite(opt.get('start_beat')) else a['start'] if a else None
        hi=warp(opt['end_beat']) if finite(opt.get('end_beat')) else b['start'] if b and opt.get('release_position','before_anchor')=='before_anchor' else b['end'] if b else None
        if hi is None and opt.get('endpoint')=='score_end_estimate':hi=warp(source_end)
        if finite(lo) and finite(hi) and hi>lo:pedals.append((lo,hi,mark))
    opened=None
    for rec in sorted(records,key=lambda r:(r['start'],r['index'])):
        for mark in rec['marks']:
            if mark['kind']!='pedal':continue
            state=mark['options'].get('state',mark.get('position'))
            if state in ('start','down','on'):opened=(rec['start'],mark)
            elif state in ('end','up','off','change') and opened:
                pedals.append((opened[0],rec['start'],opened[1]));opened=(rec['start'],mark) if state=='change' else None
    if opened:
        last=deepcopy(opened[1]);last['options']['end_estimated']=True
        pedals.append((opened[0],warp(source_end),last))
    for lo,hi,mark in pedals:
        ids=[]
        for e in audio:
            if lo<=e['start']<hi and e['end']<hi:e['end']=hi;ids+=e['source_note_ids']
        if ids:feature('pedal',ids,mark.get('group_id'),bool(mark['options'].get('end_estimated')),dict(start_beat=lo,end_beat=hi,motion='none'),'延音踏板已作用于声音；手指动作和后续起拍不延长'+('；尾端未读取，暂按选区结尾抬起' if mark['options'].get('end_estimated') else ''))
    # One string on a piano is re-excited, not accumulated indefinitely.
    for events in _group(audio,lambda e:e['pitch']).values():
        events.sort(key=lambda e:e['start'])
        for a,b in zip(events,events[1:]):
            if a['start']<b['start']<a['end']:a['end']=b['start']
    if errors:
        return dict(version=1,mode='practice',policy=policy,errors=errors,estimates=estimates,features=features,note_states=states)
    # Repeat expansion uses the original written boundaries through the same
    # expressive time map.  No extra beat is added by an ornament group.
    selection=dict(scope['selection']);selection['repeats_reviewed']=True
    try:segments,_=_performance_segments(project,selection,scope['start_beat'],source_end)
    except ValueError as exc:return dict(version=1,mode='practice',policy=policy,errors=[dict(id=None,message=str(exc))],estimates=estimates,features=features,note_states=states)
    audio_ms=[];motion_ms=[];played=0.;occurrence=0
    grace_owners={str(r['id']):r['anchor'] for r in grace_events}
    for lo,hi,_ in segments:
        left,right=warp(lo),warp(hi)
        if right<=left:continue
        for source,target in ((audio,audio_ms),(motion_input,motion_ms)):
            for e in source:
                anchors=[grace_owners[str(i)] for i in e['source_note_ids'] if str(i) in grace_owners]
                owner=warp(anchors[0]['beat']) if anchors else e['start']
                if not left-1e-8<=owner<right-1e-8:continue
                start=e['start'] if anchors else max(left,e['start']);end=min(right,e['end'])
                if end<=start:continue
                t=round((played+start-left)*ms);finish=round((played+end-left)*ms)
                if finish<=t:finish=t+1
                item=dict(t_ms=t,duration_ms=finish-t,pitch=e['pitch'],finger=e['finger'],velocity=e['velocity'],
                    source_note_ids=list(e['source_note_ids']),group_id=e['group_id'],occurrence=occurrence)
                if e.get('parent_group_id'):item['parent_group_id']=e['parent_group_id']
                if source is motion_input:item['amplitude_pct']=100
                target.append(item)
                if len(target)>MAX_EVENTS:raise ValueError('反复展开超过60000次攻击，请缩小范围')
        played+=right-left;occurrence+=1
    audio_ms.sort(key=lambda e:(e['t_ms'],e['pitch'],str(e['source_note_ids'])))
    expected_motion_onsets=sorted({(e['t_ms'],e['finger']) for e in motion_ms if finger(e['finger'])})
    motion_ms,merged=_coalesce_motion(motion_ms)
    actual_motion_onsets=sorted({(e['t_ms'],e['finger']) for e in motion_ms})
    missing_motion_onsets=[list(pair) for pair in expected_motion_onsets if pair not in set(actual_motion_onsets)]
    if missing_motion_onsets:raise ValueError('手指攻击时刻未完整保留')
    for group in merged:
        retrigger=group['handling']=='retrigger'
        feature('finger_overlap',group['ids'],estimated=retrigger,parameters=dict(handling=group['handling']),message=
            '同指重叠按原起音重按，前一次手指保持缩短，长音琴声仍保留' if retrigger else '同指同起音和弦共享一次动作，各音声音保留')
    selected_ids=[r['id'] for r in records]
    sounded={ident for e in audio_ms for ident in e['source_note_ids']}
    moving={ident for e in motion_ms for ident in e['source_note_ids']}
    missing=[ident for ident in selected_ids if ident not in sounded]
    if missing:
        return dict(version=1,mode='practice',policy=policy,errors=[dict(id=i,message='该原音未能编入声音事件') for i in missing],estimates=estimates,features=features,note_states=states)
    duration_ms=max([round(played*ms),1]+[e['t_ms']+e['duration_ms'] for e in audio_ms+motion_ms])
    if duration_ms>MAX_DURATION:raise ValueError('练习曲时长超过24小时')
    for feature_row in features:
        for ident in feature_row['source_note_ids']:
            if str(ident) in source_map:source_map[str(ident)]['group_ids'].append(feature_row['group_id'])
    for rec in records:
        ident=str(rec['id']);state=states.setdefault(ident,dict(group_id='note:'+ident,kind='written',label='基础音符',estimated=False,warning_root=False,reviewed=False,realized=True,message='已按原谱基础节奏编入',parameters={}))
        state['parameters'].setdefault('performance_finger',rec['finger']);state['parameters'].setdefault('finger_origin',rec['finger_origin'])
        items=state_items[ident] or [dict(state)]
        for item in items:
            kind=item['kind'];editable=set()
            if kind in EDITABLE_KINDS:editable.add('kind');item['parameters'].setdefault('kind',kind)
            if kind in GRACES:editable.update(('placement','borrow_ratio'))
            if kind in ('mordent_upper','mordent_lower','turn','inverted_turn','trill'):editable.update(('rate_hz','aux_finger'))
            if item['parameters'].get('kind')==COMBINATION:editable.update(('borrow_ratio','lower_aux_finger'))
            if kind in ('turn','inverted_turn'):editable.add('placement')
            if kind in ('tremolo_single','tremolo_alternating'):editable.add('rate_hz')
            if kind=='arpeggio':editable.add('borrow_ratio')
            if kind=='fermata':editable.add('hold_factor')
            if kind in ('staccato','staccatissimo','tenuto'):editable.add('gate_ratio')
            if kind=='accent':editable.add('velocity')
            item['editable_fields']=sorted(editable)
            item['parameters'].setdefault('performance_finger',rec['finger']);item['parameters'].setdefault('finger_origin',rec['finger_origin'])
        clean_items=[dict(item,parameters=dict(item['parameters'])) for item in items]
        for item in clean_items:
            item['parameters']['performance_finger']=rec['finger'];item['parameters']['finger_origin']=rec['finger_origin']
        parameters=dict(state['parameters']);parameters.update(performance_finger=rec['finger'],finger_origin=rec['finger_origin'])
        states[ident]=dict(state,items=clean_items,parameters=parameters,editable_fields=sorted({key for item in clean_items for key in item['editable_fields']}))
        source_map[ident]['group_ids']=list(dict.fromkeys(source_map[ident]['group_ids']))
    coverage=dict(selected_sources=len(selected_ids),sounded_sources=len(sounded),motion_sources=len(moving),audio_attacks=len(audio_ms),motion_events=len(motion_ms),
        unmarked_audio_only=sum(r['source'].get('source_fingering_state')=='unmarked' and r['id'] not in moving for r in records),
        estimated_source_fingers=sum(r['finger_origin']=='estimated' for r in records),selected_source_ids=selected_ids,
        sounded_source_ids=[i for i in selected_ids if i in sounded],motion_source_ids=[i for i in selected_ids if i in moving],missing_source_ids=[],
        motion_expected_attacks=len(expected_motion_onsets),motion_actual_attacks=len(actual_motion_onsets),missing_motion_onsets=[])
    result=dict(version=1,mode='practice',policy=policy,duration_ms=duration_ms,audio_events=audio_ms,motion_events=motion_ms,
        estimates=estimates,features=features,coverage=coverage,source_map=source_map,note_states=states,errors=[])
    result['performance_complete']=not missing
    identity=project.get('source_sha256')
    if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',identity):
        written=[[r['id'],r['source'].get('pitch'),r['source'].get('finger'),r['source'].get('beat'),r['source'].get('duration_beats',r['source'].get('duration'))] for r in records]
        identity=hashlib.sha256(json.dumps(written,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()
    result['source_identity']=identity.lower()
    semantic=[1,result['source_identity'],duration_ms,[[e['t_ms'],e['duration_ms'],e['pitch'],e['velocity'],e['finger'] or 0,e['source_note_ids']] for e in audio_ms]]
    result['arrangement_id']=hashlib.sha256(json.dumps(semantic,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()
    return result


def _group(values,key):
    groups=defaultdict(list)
    for value in values:groups[key(value)].append(value)
    return groups


def _coalesce_motion(events):
    """Share simultaneous presses, but preserve every later finger attack.

    A finger cannot keep holding one key while pressing another.  Practice
    motion releases the old hold before the later attack, while independent
    audio keeps the full original voice.  No source attack is hidden in a union.
    """
    groups=_group([e for e in events if finger(e['finger'])],lambda e:e['finger']);result=[];merged=[]
    for value,notes in groups.items():
        notes.sort(key=lambda e:(e['t_ms'],e['duration_ms'],e['pitch']))
        presses=[];component=[];component_end=-1
        def finish_component():
            if len(component)>1:
                merged.append(dict(ids=list(dict.fromkeys(i for e in component for i in e['source_note_ids'])),
                    handling='retrigger' if len({e['t_ms'] for e in component})>1 else 'simultaneous-shared'))
        for n in notes:
            if component and n['t_ms']>=component_end:
                finish_component();component=[];component_end=-1
            component.append(n);component_end=max(component_end,n['t_ms']+n['duration_ms'])
            if presses and presses[-1]['t_ms']==n['t_ms']:
                prior=presses[-1];end=max(prior['t_ms']+prior['duration_ms'],n['t_ms']+n['duration_ms'])
                prior['duration_ms']=end-prior['t_ms'];prior['velocity']=max(prior['velocity'],n['velocity'])
                prior['source_note_ids']=list(dict.fromkeys(prior['source_note_ids']+n['source_note_ids']))
                prior['group_id']='finger-shared:'+str(value)+':'+str(prior['t_ms'])
            else:presses.append(dict(n))
        finish_component()
        for prior,nxt in zip(presses,presses[1:]):
            if prior['t_ms']+prior['duration_ms']>nxt['t_ms']:
                distance=nxt['t_ms']-prior['t_ms'];gap=min(10,max(0,distance//4))
                prior['duration_ms']=max(1,distance-gap)
        result.extend(presses)
    result.sort(key=lambda e:(e['t_ms'],e['finger']))
    return result,merged


def summary(performance):
    return {key:performance[key] for key in ('version','mode','policy','estimates','features','coverage','arrangement_id') if key in performance}


def compile_practice_score(project):
    performance=realize_project(project)
    if performance.get('errors'):
        raise ValueError('；'.join(str(e.get('id','?'))+'：'+e['message'] for e in performance['errors'][:8]))
    if not performance['motion_events']:
        raise ValueError('所选范围没有手指动作，原未印指法的音只保留声音；请补指法')
    display_title=_plain_title(project);suffix='（练习·'+performance['arrangement_id'][:16]+'）';title=display_title
    while len((title+suffix).encode('utf8'))>96:title=title[:-1]
    notes=[{k:e[k] for k in ('t_ms','duration_ms','pitch','finger','velocity','amplitude_pct')} for e in performance['motion_events']]
    source_notes=[]
    by_id={str(n.get('id')):n for n in project.get('notes',[])}
    for e in performance['motion_events']:
        ids=e['source_note_ids'];first=by_id.get(str(ids[0]),{})
        source_notes.append(dict({k:first[k] for k in ('id','page','system','measure','origin','bbox') if k in first},
            t_ms=e['t_ms'],duration_ms=e['duration_ms'],finger=e['finger'],pitch=e['pitch'],source_note_ids=ids,
            occurrence=e['occurrence'],source_spans=[dict(id=i,t_ms=e['t_ms'],duration_ms=e['duration_ms']) for i in ids]))
    score=dict(version=1,hand='right',title=title+suffix,display_title=display_title,notes=notes,
        duration_ms=performance['duration_ms'],source_notes=source_notes,performance={k:v for k,v in performance.items() if k not in ('motion_events','note_states','errors')},
        motor_only_pgl=True)
    timed=[n for n in export_scope(project)['notes'] if not n.get('excluded') and n.get('hand')=='right']
    if project.get('right_hand_timing'):
        score['timing']=dict(policy='right-hand-relative',estimated=any(n.get('timing_estimated') for n in timed),
            warnings=[dict(id=n.get('id'),page=n.get('page'),system=n.get('system'),beat=n.get('beat'),message=n['timing_warning']) for n in timed if n.get('timing_warning')])
    # Audio data is intentionally outside the PGL1 payload.  Its full identity
    # appears in the honest practice title, so source/audio associations cannot
    # silently collide when two performances use the same motor union.
    return validate(score)
