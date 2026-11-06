"""Prepare a locally recognized score for ordinary export, without per-note approval.

Unmarked original notes remain recognized and editable without invented fingers.
Raw recognize_pdf stays available unchanged for independent accuracy evaluation.
"""
from copy import deepcopy
from collections import defaultdict
import math

from score_converter import export_reviewed, export_scope, pitch_midi, _merge_reviewed_ties
from score_timing import reflow_right_hand_timing
from score_performance import performance_notice, source_ids
from score_realization import normalize_policy, realize_project, compile_practice_score, summary as performance_summary

TIMING_BLOCKERS=frozenset(('measure_timing_unresolved','rest_duration_unresolved',
    'grace_or_cue_note_requires_review','stem_not_resolved','rhythm_geometry_conflict',
    'flag_anchor_unresolved','beam_attachment_ambiguous','beam_spacing_conflict',
    'ledger_staff_assignment_unresolved','cross_staff_hand_unresolved'))


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _unfingered(note):
    return note.get('finger') is None and note.get('source_fingering_state')=='unmarked'


def _valid_finger(note):
    return type(note.get('finger')) is int and 1<=note['finger']<=5


def _missing(note, continuation=False, allow_unfingered=False):
    errors=[]
    if note.get('hand')!='right':errors.append('确认左右手')
    try:pitch_midi(note.get('pitch'))
    except (ValueError,TypeError):errors.append('选择音高')
    if not ((continuation or allow_unfingered) and note.get('finger') is None) and not _valid_finger(note):
        errors.append('选择指法')
    if not _finite(note.get('beat')) or note['beat']<0:errors.append('确定小节内开始位置')
    # An unfingered, unmeasured ornament has no independent glove action. Its
    # original head remains editable, and the right-hand timing model keeps the
    # principal rhythm. If the user assigns a finger it again needs a duration.
    omitted_grace=(allow_unfingered and _unfingered(note)
                   and note.get('grace_kind') in ('slashed','unmeasured_prefix','unmeasured'))
    if (not _finite(note.get('duration_beats')) or note['duration_beats']<=0) and not omitted_grace:
        errors.append('选择音值')
    return errors


def _export_copy(project):
    candidate=deepcopy(project)
    scope=export_scope(candidate)
    candidate['notes']=scope['notes']
    candidate['selection']=selection=scope['selection']
    selection.update(range_reviewed=True,range_confirmation_source='automatic-structural-check')
    right=[n for n in candidate.get('notes',[]) if not n.get('excluded') and n.get('hand')=='right']
    by_id={n.get('id'):n for n in right}
    for note in right:
        # The converter validates the finger of each resulting attack after
        # merging ties; a continuation is allowed to have no printed digit.
        note['confirmed']=not _missing(note,continuation=True)
        if note.get('tie_to') is not None:
            # Existing explicit user links retain the original converter checks.
            continue
        target=by_id.get(note.get('tie_to_candidate')) if selection.get('apply_tie_candidates') is True else None
        if (target is not None and note.get('pitch')==target.get('pitch')
                and _finite(note.get('beat')) and _finite(note.get('duration_beats'))
                and _finite(target.get('beat'))
                and abs(note['beat']+note['duration_beats']-target['beat'])<1e-6
                and target.get('finger') in (None,note.get('finger'))):
            note.update(tie_to=target['id'],tie_reviewed=True)
    # Candidate links have now been checked individually. Keep an unaccepted
    # candidate out of the explicit-link converter path.
    selection['apply_tie_candidates']=False
    if (selection.get('repeat_mode')=='unfold' and candidate.get('repeat_review_issues')):
        raise ValueError('反复或跳转位置尚不明确，请检查反复设置，或选择按谱面顺序导出')
    if selection.get('repeat_mode')=='unfold':
        selection.update(repeats_reviewed=True,repeats_confirmation_source='automatic-geometry-check')
    if any(_unfingered(note) for note in right):
        # A gray continuation still extends its explicitly fingered attack.
        # Only independent unmarked attacks are omitted from the action copy.
        continuations={source.get('id') for record in _tie_records(candidate)
                       if _valid_finger(record['source']) for source in record['sources'][1:]}
        for note in right:
            if _unfingered(note) and note.get('id') not in continuations:
                note['excluded']=True
        # Omitting an action must not shorten the original musical timeline.
        # Source-range selections already carry a verified end from export_scope.
        if not scope['source_fields'] and selection.get('end_beat') is None:
            ends=[event['beat']+event.get('duration_beats',event.get('duration'))
                  for event in candidate['notes']+candidate.get('rests',[])
                  if event.get('hand')!='left' and _finite(event.get('beat'))
                  and _finite(event.get('duration_beats',event.get('duration')))
                  and event.get('duration_beats',event.get('duration'))>0]
            if _finite(candidate.get('written_duration_beats')):
                ends.append(candidate['written_duration_beats'])
            if ends:candidate['written_duration_beats']=max(ends)
    groups=defaultdict(list)
    for note in candidate.get('notes',[]):
        if note.get('hand')!='right':continue
        if note.get('tremolo_group'):groups[note['tremolo_group']].append(note)
    id_map={}
    if groups:
        ordinary=[n for n in candidate['notes'] if not n.get('tremolo_group') or n.get('hand')!='right']
        for original_members in groups.values():
            members=[n for n in original_members if not n.get('excluded')]
            if not members:continue
            step=members[0].get('tremolo_step_beats');span=members[0].get('tremolo_span_beats');start=members[0].get('beat')
            if (not all(_finite(v) for v in (step,span,start)) or step<=0 or span<=0
                    or {n.get('tremolo_side') for n in original_members}!={0,1}
                    or any(n.get('tremolo_step_beats')!=step or n.get('tremolo_span_beats')!=span
                           or n.get('beat')!=start for n in members)
                    or abs(span/step-round(span/step))>1e-6):
                raise ValueError('震音的两组音或持续位置尚不明确，请检查该小节')
            count=round(span/step)
            if count>60000:raise ValueError('震音展开后的音符过多')
            for pulse in range(count):
                for source in members:
                    if source['tremolo_side']!=pulse%2:continue
                    if source.get('tie_to') is not None:raise ValueError('震音跨越延音线，需要检查该小节')
                    note=deepcopy(source);note.update(id=str(source['id'])+'~t'+str(pulse),
                        beat=start+pulse*step,duration_beats=step,confirmed=True)
                    note.pop('tie_to_candidate',None)
                    ordinary.append(note);id_map[note['id']]=source['id']
        candidate['notes']=ordinary
    candidate['_performance_source_ids']=id_map
    return candidate


def _tie_records(candidate):
    records=[]
    for note in candidate.get('notes',[]):
        if note.get('excluded') or _missing(note,continuation=True):continue
        records.append(dict(beat=note['beat'],duration=note['duration_beats'],
                            pitch=pitch_midi(note['pitch']),source=note))
    return _merge_reviewed_ties(records,candidate.get('selection',{}))


def _validated_export(project,candidate=None):
    if normalize_policy(project)['mode']=='practice':
        return compile_practice_score(project)
    if candidate is None:candidate=_export_copy(project)
    score=export_reviewed(candidate)
    id_map=candidate.get('_performance_source_ids',{})
    for note in score.get('source_notes',[]):
        if 'id' in note:note['id']=id_map.get(note['id'],note['id'])
        note['source_note_ids']=list(dict.fromkeys(id_map.get(i,i) for i in note.get('source_note_ids',[])))
        for span in note.get('source_spans',[]):
            if 'id' in span:span['id']=id_map.get(span['id'],span['id'])
    timed_notes=[n for n in export_scope(project)['notes']
                 if n.get('hand')=='right' and not n.get('excluded')]
    warnings=[dict(id=n.get('id'),page=n.get('page'),system=n.get('system'),
                   beat=n.get('beat'),message=n['timing_warning'])
              for n in timed_notes if n.get('timing_warning')]
    if project.get('right_hand_timing'):
        score['timing']=dict(policy='right-hand-relative',
                             estimated=any(n.get('timing_estimated') for n in timed_notes),warnings=warnings)
    notice=performance_notice(timed_notes,source_ids(score),id_map.values(),exported=True)
    if notice:score['performance_notice']=notice
    return score


def _overlapping_note_ids(project,candidate=None):
    """Find actual same-finger conflicts even if another note is incomplete."""
    try:
        if candidate is None:candidate=_export_copy(project)
    except ValueError:
        # Unresolved repeat/tremolo structure is reported by final validation;
        # ordinary complete notes can still be checked independently.
        candidate=dict(project,notes=export_scope(project)['notes'])
    origin_ids=candidate.get('_performance_source_ids',{})
    try:
        records=_tie_records(candidate)
        notes=[dict(record['source'],duration_beats=record['duration'],
                    _source_ids=[s.get('id') for s in record['sources']])
               for record in records if not _missing(record['source'])]
    except ValueError:
        notes=[n for n in candidate.get('notes',[]) if not n.get('excluded')
               and n.get('hand')=='right' and not _missing(n)]
    active={};conflicts=set()
    for note in sorted(notes,key=lambda n:(n['beat'],str(n.get('id','')))):
        finger=note['finger'];prior_notes=[p for p in active.get(finger,[])
            if p['beat']+p['duration_beats']>note['beat']+1e-6]
        for prior in prior_notes:
            if (prior.get('tremolo_group')
                    and prior.get('tremolo_group')==note.get('tremolo_group')
                    and prior.get('tremolo_side')!=note.get('tremolo_side')):
                continue
            for source in (prior,note):
                conflicts.update(origin_ids.get(ident,ident) for ident in source.get('_source_ids',[source.get('id')]))
        active[finger]=prior_notes+[note]
    return conflicts


def prepare_automatic_project(project):
    first_pass=project.get('automatic_mode') is not True
    project['automatic_mode']=True
    if first_pass and project.get('repeat_sections') and not project.get('repeat_review_issues'):
        project.setdefault('selection',{})['repeat_mode']='unfold'
    notes=project.get('notes',[])
    practice=normalize_policy(project)['mode']=='practice'
    if not practice:project.pop('performance',None)
    small_beam_warning='小音符用途请核对；音值已按同梁几何恢复'
    for note in notes:
        note.pop('performance_state',None)
        note['automatic_ready']=False
        note['automatic_reasons']=[]
        note['in_export_scope']=False
        note['unfingered']=_unfingered(note)
        if small_beam_warning in (note.get('timing_warning') or ''):
            prior=note['timing_warning'].replace(small_beam_warning,'').strip('；')
            note['timing_warning']=prior or None
    for note in notes:
        if note.get('excluded') or note.get('hand')=='left':continue
        # Written position is independently resolved by the rhythm parser. Do
        # not manufacture a position from x-spacing or a previous unknown bar.
        if (note.get('beat') is None and 'beat' not in note.get('manual_fields',[])
                and _finite(note.get('written_beat'))
                and not TIMING_BLOCKERS.intersection(note.get('issues',[]))):
            note['beat']=note['written_beat']
        if (note.get('duration_beats') is None and 'duration_beats' not in note.get('manual_fields',[])
                and _finite(note.get('duration'))):
            note['duration_beats']=note['duration']
    # Right-hand score order remains usable when a local onset needs an
    # estimate. Only the source of an estimate warns; followers keep their
    # relative dependencies and are recalculated after an edit.
    reflow_right_hand_timing(project)
    for note in notes:
        recovery=note.get('rhythm_evidence',{}).get('beam_recovery') or {}
        if (note.get('hand')=='right' and not note.get('excluded')
                and 'small_notated_note_requires_review' in note.get('issues',[])
                and recovery.get('method') in ('shared_original_stem','unique_adjacent_shaft_beam_family')
                and 'duration_beats' not in note.get('manual_fields',[])):
            current=note.get('timing_warning')
            note['timing_warning']=(current+'；'+small_beam_warning) if current else small_beam_warning
            note.setdefault('timing_estimated',False)
    scope_error=None
    try:scope=export_scope(project)
    except ValueError as error:
        scope_error=str(error)
        scope=dict(notes=[],start_beat=None,end_beat=None,source_fields=[])
    for note in scope['notes']:note['in_export_scope']=True
    relevant=[n for n in scope['notes'] if not n.get('excluded') and n.get('hand')!='left']
    right=[n for n in relevant if n.get('hand')=='right']
    if practice:
        return _prepare_practice(project,scope,relevant,right,scope_error)
    continuation_ids=set()
    structure_error=None
    candidate=None
    if not scope_error:
        try:
            candidate=_export_copy(project)
            continuation_ids={source.get('id') for record in _tie_records(candidate)
                              for source in record['sources'][1:]}
        except ValueError as error:structure_error=str(error)
    attention=[]
    for note in relevant:
        reasons=_missing(note,continuation=note.get('id') in continuation_ids,
                         allow_unfingered=note['unfingered'])
        note['automatic_ready']=not reasons
        note['automatic_reasons']=reasons
        if reasons:attention.append(note.get('id'))
    conflicts=_overlapping_note_ids(project,candidate) if not scope_error else set()
    for note in right:
        if note.get('id') in conflicts:
            note['automatic_ready']=False
            note['automatic_reasons'].append('同一手指的两个音重叠，请检查指法或时值')
            if note.get('id') not in attention:attention.append(note.get('id'))
    original_right=[n for n in notes if n.get('hand')=='right']
    ignored=sum(bool(n.get('excluded')) for n in scope['notes'] if n.get('hand')=='right')
    original_printed=sum(type(n.get('finger')) is int and 1<=n['finger']<=5 and
                n.get('finger_source')!='manual' for n in original_right)
    printed=sum(type(n.get('finger')) is int and 1<=n['finger']<=5 and
                n.get('finger_source')!='manual' for n in right)
    project.setdefault('source_has_printed_fingering',original_printed>0)
    unfingered=sum(n['unfingered'] for n in right)
    actions=sum(_valid_finger(n) for n in right)
    unsupported=not original_right
    if not original_right:messages=['没有识别到可处理的右手谱面，当前不支持这份PDF。']
    elif not right:messages=['所选范围内没有可导出的右手音符，请调整范围或右键恢复已忽略音符。']
    else:messages=[]
    if scope_error or structure_error:messages=[scope_error or structure_error]
    recognition_ready=bool(right) and not attention and not unsupported and not scope_error and not structure_error
    ready=recognition_ready and actions>0
    if recognition_ready and not actions:
        messages.append('所选范围没有已设置指法的手指动作。可点击灰色音符补指法后导出。')
    if ready:
        try:_validated_export(project,candidate)
        except ValueError as error:
            ready=False
            text=str(error)
            if 'Overlapping notes on one finger' in text:
                text='同一手指存在重叠音，请检查指法或时值'
            messages.append(text)
    timing_warnings=[n.get('id') for n in right if n.get('timing_warning')]
    result=dict(version=4,ready=ready,recognition_ready=recognition_ready,
                notes=len(right),unfingered_notes=unfingered,action_notes=actions,
                ignored_notes=ignored,attention_notes=len(attention),
                attention_note_ids=attention,
                timing_warning_notes=len(timing_warnings),timing_warning_note_ids=timing_warnings,
                timing_estimated_notes=sum(bool(n.get('timing_estimated')) for n in right),
                unsupported=unsupported,printed_fingers=printed,messages=messages)
    notice=performance_notice(right,expanded_tremolo_ids=(candidate or {}).get('_performance_source_ids',{}).values())
    if notice:result['performance_notice']=notice
    project['automatic']=result
    project['export_scope']=dict(start_beat=scope['start_beat'],end_beat=scope['end_beat'],
        source_fields=scope['source_fields'],selected_note_ids=[n.get('id') for n in scope['notes']])
    project.setdefault('report',{}).update(auto_ready=ready,recognition_ready=recognition_ready,
        unfingered_notes=unfingered,action_notes=actions,attention_notes=len(attention),
        requires_review=not recognition_ready,ready=ready,unsupported=unsupported)
    return project


def _prepare_practice(project,scope,relevant,right,scope_error):
    """Readiness of a real performance, distinct from written-field accuracy."""
    try:
        performance=realize_project(project) if not scope_error else dict(errors=[dict(id=None,message=scope_error)])
    except ValueError as exc:
        performance=dict(errors=[dict(id=None,message=str(exc))])
    performance.setdefault('version',1);performance.setdefault('mode','practice')
    errors=performance.get('errors',[]);local=defaultdict(list);global_errors=[]
    for error in errors:
        if error.get('id') is None:global_errors.append(error['message'])
        else:local[str(error['id'])].append(error['message'])
    attention=[];states=performance.get('note_states',{})
    # 11-05 用户：同一时刻同一根手指不算错（照样显示，想改能改）；播放时同一根手指同一时刻只按一次
    for note in relevant:
        reasons=list(local.get(str(note.get('id')),[]))
        if note.get('hand')!='right':reasons.append('确认右手归属')
        note['automatic_ready']=not reasons and not global_errors
        note['automatic_reasons']=reasons
        if str(note.get('id')) in states:note['performance_state']=states[str(note['id'])]
        if reasons:attention.append(note.get('id'))
    coverage=performance.get('coverage',{})
    actions=coverage.get('motion_sources',0)
    messages=list(global_errors)
    if not right:messages.append('没有可处理的右手音符')
    if right and not errors and not actions:
        messages.append('所选范围没有手指动作；原未印指法的音已保留声音，可补指法')
    ready=bool(right) and not errors and bool(actions) and performance.get('performance_complete') is True
    original_right=[n for n in project.get('notes',[]) if n.get('hand')=='right']
    project.setdefault('source_has_printed_fingering',any(_valid_finger(n) and n.get('finger_source')!='manual' for n in original_right))
    unfingered=sum(_unfingered(n) for n in right)
    written_attention=sum(bool(_missing(n,allow_unfingered=_unfingered(n))) for n in right)
    legacy_strict_ready=False
    if right and written_attention==0 and not scope_error:
        try:
            _validated_export(dict(project,performance_policy=dict(mode='strict')))
            legacy_strict_ready=True
        except ValueError:
            pass
    strict_ready=legacy_strict_ready and not performance.get('estimates')
    result=dict(version=5,mode='practice',ready=ready,recognition_ready=bool(right) and written_attention==0,
        performance_ready=ready,practice_ready=ready,strict_ready=bool(strict_ready),legacy_strict_ready=legacy_strict_ready,
        source_fields_ready=bool(right) and written_attention==0,notes=len(right),unfingered_notes=unfingered,action_notes=actions,
        ignored_notes=sum(bool(n.get('excluded')) for n in scope['notes'] if n.get('hand')=='right'),
        attention_notes=len(attention),attention_note_ids=attention,
        written_attention_notes=written_attention,estimated_performance_groups=len(performance.get('estimates',[])),estimated_groups=len(performance.get('estimates',[])),
        timing_warning_notes=sum(bool(n.get('timing_warning')) for n in right),
        timing_warning_note_ids=[n.get('id') for n in right if n.get('timing_warning')],
        timing_estimated_notes=sum(bool(n.get('timing_estimated')) for n in right),
        unsupported=not original_right,printed_fingers=sum(_valid_finger(n) and n.get('finger_source')!='manual' for n in right),messages=messages)
    project['automatic']=result;project['performance']=performance_summary(performance)
    project['export_scope']=dict(start_beat=scope['start_beat'],end_beat=scope['end_beat'],source_fields=scope['source_fields'],selected_note_ids=[n.get('id') for n in scope['notes']])
    project.setdefault('report',{}).update(auto_ready=ready,recognition_ready=result['recognition_ready'],performance_ready=ready,
        unfingered_notes=unfingered,action_notes=actions,attention_notes=len(attention),requires_review=not ready,ready=ready,unsupported=not original_right)
    return project


def _validation_copy(project):
    """Copy source/edit data, excluding only values preparation regenerates."""
    transient={'performance_state','automatic_ready','automatic_reasons','in_export_scope','unfingered'}
    value={k:v for k,v in project.items() if k not in ('performance','automatic','export_scope')}
    value['notes']=[{k:v for k,v in n.items() if k not in transient} for n in project.get('notes',[])]
    return deepcopy(value)


def check_project(project):
    """Validate a copy and return the dependent timing update for the editor."""
    if not isinstance(project,dict) or not isinstance(project.get('notes'),list):
        raise ValueError('曲谱项目不正确')
    checked=prepare_automatic_project(_validation_copy(project))
    result=dict(automatic=checked['automatic'],report=checked['report'],scope=checked['export_scope'],notes=[])
    timing=checked.get('right_hand_timing')
    for n in checked['notes']:
        state=dict(id=n.get('id'),automatic_ready=n.get('automatic_ready',False),
                   automatic_reasons=n.get('automatic_reasons',[]),in_export_scope=n.get('in_export_scope',False),
                   unfingered=n.get('unfingered',False),source_fingering_state=n.get('source_fingering_state'))
        for key in ('timing_warning','timing_estimated','timing_source_id'):
            if key in n:state[key]=n[key]
        if 'performance_state' in n:state['performance_state']=n['performance_state']
        if timing and n.get('hand')=='right':
            state.update({key:value for key,value in n.items()
                          if key.startswith('timing_') or key in
                          ('beat','start_beat','written_beat','measure_start_beat','measure_beat','main_anchor_beat')})
        result['notes'].append(state)
    if timing:
        result.update(right_hand_timing=timing,written_duration_beats=checked.get('written_duration_beats'),
                      rests=checked.get('rests',[]),repeat_sections=checked.get('repeat_sections',[]),
                      repeat_markers=checked.get('repeat_markers',[]),ending_brackets=checked.get('ending_brackets',[]))
    if checked.get('performance'):result['performance']=checked['performance']
    return result


def export_automatic(project, skip_pending=False):
    if type(skip_pending) is not bool:
        raise ValueError('跳过待处理音的选项不正确')
    candidate=prepare_automatic_project(_validation_copy(project))
    automatic=candidate['automatic']
    skipped=[]
    if skip_pending and automatic['attention_notes']:
        scope=export_scope(candidate)
        if not scope['source_fields'] and scope['selection'].get('end_beat') is None:
            start=scope['start_beat']
            events=scope['notes']+[r for r in candidate.get('rests',[]) if r.get('hand')!='left']
            tails=[]
            for event in events:
                beat=event.get('beat');duration=event.get('duration_beats',event.get('duration'))
                if event.get('hand')=='left' or not _finite(beat) or beat<start:continue
                tails.append(beat+(duration if _finite(duration) and duration>0 else 0))
            if _finite(candidate.get('written_duration_beats')):
                tails.append(candidate['written_duration_beats'])
            if tails:candidate['written_duration_beats']=max(tails)
    while skip_pending and automatic['attention_notes']:
        selected=[n for n in candidate['notes'] if n.get('in_export_scope') and not n.get('excluded') and n.get('hand')!='left']
        identities=[n.get('id') for n in selected]
        if any(i is None for i in identities) or len(set(identities))!=len(identities):
            raise ValueError('待处理音符编号不唯一，无法安全标记跳过位置')
        pending=set(automatic['attention_note_ids'])
        for note in selected:
            if note.get('id') not in pending:continue
            skipped.append(dict(id=note['id'],page=note.get('page'),system=note.get('system'),
                                measure=note.get('measure'),reasons=list(note.get('automatic_reasons',[]))))
            note['excluded']=True
        if not pending.intersection(identities):
            raise ValueError('待处理位置无法定位，无法生成部分动作谱')
        # Keep a valid attack when its explicit tied continuation was skipped;
        # only the export copy is shortened and the source tie remains intact.
        for note in selected:
            if not note.get('excluded') and note.get('tie_to') in pending:
                note.pop('tie_to',None)
                note.pop('tie_reviewed',None)
        candidate=prepare_automatic_project(candidate)
        automatic=candidate['automatic']
    if not automatic['ready']:
        if automatic['unsupported']:raise ValueError(automatic['messages'][0])
        if automatic['attention_notes']:
            details=[]
            for note in candidate['notes']:
                if note.get('id') not in automatic['attention_note_ids']:continue
                location='第'+str(note.get('page','?'))+'页、第'+str(note.get('system','?'))+'行'
                text=location+'：'+'、'.join(note.get('automatic_reasons',[]))
                if text not in details:details.append(text)
                if len(details)==3:break
            raise ValueError('还有 '+str(automatic['attention_notes'])+' 处需要检查。'+'；'.join(details))
        raise ValueError('；'.join(automatic['messages']) or '曲谱尚未就绪')
    score=_validated_export(candidate)
    if skipped:
        suffix='（跳过'+str(len(skipped))+'处待处理）'
        title=score['title']
        identity_suffix=''
        performance=score.get('performance') or {}
        if performance.get('mode')=='practice':
            marker='（练习·'+performance['arrangement_id'][:16]+'）'
            if title.endswith(marker):
                title=title[:-len(marker)]
                identity_suffix=marker
        while len((title+suffix+identity_suffix).encode('utf-8'))>96:title=title[:-1]
        score['title']=title+suffix+identity_suffix
        score['partial_export']=dict(skipped_pending_count=len(skipped),skipped_pending=skipped,
                                     original_project_unchanged=True)
    return score
