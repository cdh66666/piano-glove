"""Editable right-hand written timing, including explicitly marked estimates.

Recognition evidence is captured once.  Reflow always starts from that evidence,
so correcting an early attack or duration moves its dependants instead of adding
the same correction again on each validation request.  This module neither reads
PDF files nor changes pitches, fingers, or actual unknown musical durations.
"""
from copy import deepcopy
from collections import defaultdict
import math
import statistics


VERSION = 2
EPS = 1e-6


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _duration(event):
    value = event.get('duration_beats', event.get('duration'))
    return value if _finite(value) and value > 0 else None


def _key(event):
    values = tuple(event.get(k) for k in ('page', 'system', 'measure'))
    return values if all(type(v) is int and v > 0 for v in values) else None


def _x(event):
    origin = event.get('origin')
    if isinstance(origin, (list, tuple)) and origin and _finite(origin[0]):
        return origin[0]
    box = event.get('glyph_bbox', event.get('bbox'))
    if isinstance(box, (list, tuple)) and len(box) >= 4 and all(_finite(v) for v in box):
        return (box[0] + box[2]) / 2
    return None


def _grace(event):
    return event.get('grace_kind') in ('unmeasured_prefix', 'slashed')


def _stem(event):
    """The same drawn stem joins displaced noteheads into one chord."""
    rhythm=event.get('rhythm_evidence') or {}
    stem=rhythm.get('stem') if isinstance(rhythm,dict) else None
    if isinstance(stem,(tuple,list)) and len(stem)==3 and all(_finite(v) for v in stem):
        return tuple(stem)
    return None


def _chord_groups(captured, gaps):
    groups=[]
    stems={}
    ordered=sorted(captured,key=lambda e:(e['x'] if e['x'] is not None else math.inf,str(e['id'])))
    for event in ordered:
        gap=gaps.get(event['staff'],10.0)
        key=(event['staff'],event['stem'],event['grace']) if event['stem'] is not None else None
        shared=stems.get(key) if key is not None and not event['rest'] else None
        prior=groups[-1] if groups else None
        locals_agree=(prior is not None and (event['local'] is None
            or not any(e['local'] is not None for e in prior['events'])
            or all(e['local'] is None or abs(e['local']-event['local'])<EPS for e in prior['events'])))
        # Independent printed tremolo endpoints are distinct columns; they are
        # joined later only if the recognizer established the complete pair.
        can_near=(not event['rest'] and prior and not prior['rest'] and event['x'] is not None
            and prior['x'] is not None and abs(event['x']-prior['x'])<.35*gap and locals_agree
            and all(e['grace']==event['grace'] for e in prior['events'])
            and not any(event['tremolo_group'] is not None and e['tremolo_group']==event['tremolo_group']
                        and e['tremolo_side']!=event['tremolo_side'] for e in prior['events']))
        group=shared or (prior if can_near else None)
        if group is None:
            group=dict(x=event['x'],rest=event['rest'],events=[])
            groups.append(group)
        group['events'].append(event)
        if key is not None and not event['rest']:
            stems[key]=group
    # Treat the two written endpoints of a measured tremolo as one occupied
    # interval. Without both sides and consistent printed values do not guess.
    tremolos=defaultdict(list)
    for group in groups:
        for event in group['events']:
            if event['tremolo_group'] is not None:
                tremolos[event['tremolo_group']].append((group,event))
    for members in tremolos.values():
        sides={e['tremolo_side'] for _,e in members}
        spans={e['span'] for _,e in members}
        steps={e['tremolo_step'] for _,e in members}
        selected=[]
        for group,_ in members:
            if all(group is not existing for existing in selected):selected.append(group)
        if (sides!={0,1} or len(spans)!=1 or len(steps)!=1
                or not all(_finite(v) and v>0 for v in (*spans,*steps))
                or any(any(e['tremolo_group']!=members[0][1]['tremolo_group'] for e in g['events'])
                       for g in selected)):
            continue
        first=min(selected,key=lambda g:g['x'] if g['x'] is not None else math.inf)
        for group in selected:
            if group is not first:
                first['events'].extend(group['events'])
                groups.remove(group)
    return sorted(groups,key=lambda g:g['x'] if g['x'] is not None else math.inf)


def _capture(project, previous=None):
    if previous is not None:
        # Hand edits can add/remove source notes. Retain original rhythmic
        # evidence for existing members while capturing the newly selected RH.
        project = deepcopy(project)
        originals = {e['id']: e for m in previous['measures'] for g in m['groups'] for e in g['events']}
        for event in project.get('notes', [])+project.get('rests', []):
            original = originals.get(event.get('id'))
            if original is not None:
                event['measure_beat'] = original['local']
                event['duration_beats'] = original['duration']
                if original.get('left_derived'):
                    event['onset_evidence'] = dict(method='aligned_to_paired_complete_voice')
    notes = [n for n in project.get('notes', []) if n.get('hand') == 'right'
             and _key(n) is not None and _x(n) is not None]
    # Existing hand-authored/legacy projects without source geometry retain their
    # own absolute times.  Merely having a measure number does not opt them in.
    if not notes:
        return None
    ids = {n.get('staff') for n in notes}
    # Cross-staff RH notes still belong to the right hand. Their printed staff
    # supplies geometry, but LH-computed bar lengths below are never imported.
    staves = [s for s in project.get('staves', []) if s.get('id') in ids]
    if not staves:
        return None
    staff_ids = {s.get('id') for s in staves}
    events = defaultdict(list)
    for n in notes:
        if n.get('staff') in staff_ids:
            events[_key(n)].append((n, False))
    for r in project.get('rests', []):
        if r.get('hand') == 'right' and r.get('staff') in staff_ids and _key(r) is not None:
            events[_key(r)].append((r, True))
    records = defaultdict(list)
    gaps = {}
    all_events = project.get('notes', [])+project.get('rests', [])
    left_derived = {e.get('id') for e in all_events if e.get('hand') == 'left'
                    or e.get('onset_evidence', {}).get('method') in
                    ('aligned_to_paired_complete_voice', 'complete_principal_rhythm_with_paired_voice_anchor')}
    changed = True
    while changed:
        changed = False
        for event in all_events:
            evidence = event.get('onset_evidence', {})
            anchors = evidence.get('anchor_ids', [])
            if (event.get('id') not in left_derived and anchors
                    and all(identity in left_derived for identity in anchors)):
                left_derived.add(event.get('id'))
                changed = True
    for staff in staves:
        lines = staff.get('lines', [])
        gaps[staff['id']] = abs(lines[1] - lines[0]) if len(lines) >= 2 else 10.0
        for record in staff.get('measures', []):
            key = (staff.get('page'), staff.get('system'), record.get('measure'))
            if all(type(v) is int and v > 0 for v in key):
                if staff.get('hand') == 'right':
                    records[key].append((staff, record))
                    events.setdefault(key, [])
    plans = []
    all_keys = sorted(events)
    for index, key in enumerate(all_keys):
        members = events[key]
        measure_records = records[key]
        meters = {r.get('meter_beats', s.get('meter_beats')) for s, r in measure_records}
        meters = {m for m in meters if _finite(m) and m > 0}
        meter = next(iter(meters)) if len(meters) == 1 else None
        verified_lengths = {r.get('length_beats') for _, r in measure_records
                            if r.get('timing_resolved') and _finite(r.get('length_beats'))
                            and r['length_beats'] > 0}
        verified_length = next(iter(verified_lengths)) if len(verified_lengths) == 1 else None
        captured = []
        for event, rest in members:
            captured.append(dict(id=event.get('id'), rest=rest, x=_x(event),
                staff=event.get('staff'), voice=event.get('voice'),
                local=event.get('measure_beat') if _finite(event.get('measure_beat'))
                      and event.get('id') not in left_derived else None,
                duration=_duration(event), grace=_grace(event),
                span=event.get('tremolo_span_beats'), stem=_stem(event),
                tremolo_group=event.get('tremolo_group'),tremolo_side=event.get('tremolo_side'),
                tremolo_step=event.get('tremolo_step_beats'),
                main_anchor=event.get('main_anchor_measure_beat'),
                main_anchor_id=event.get('main_anchor_id'),
                main_anchor_ids=event.get('main_anchor_ids') or [],
                main_anchor_inferred=False,
                left_derived=event.get('id') in left_derived))
        groups = _chord_groups(captured,gaps)
        # Only an explicitly identified ornament is eligible for a fallback
        # anchor. A single nearby next principal chord on the same staff is
        # unambiguous; never infer grace solely from a small notehead.
        for group_index,group in enumerate(groups):
            if group['rest'] or not all(e['grace'] for e in group['events']):continue
            if any(e['main_anchor_id'] or e['main_anchor_ids'] for e in group['events']):continue
            last_x=max((e['x'] for e in group['events'] if e['x'] is not None),default=None)
            staffs={e['staff'] for e in group['events']}
            if last_x is None or len(staffs)!=1:continue
            staff=next(iter(staffs));gap=gaps.get(staff,10.0)
            candidates=[]
            for later in groups[group_index+1:]:
                if later['x'] is None or later['x']-last_x>3*gap:break
                if later['rest']:break
                if all(e['grace'] for e in later['events']):continue
                if any(e['staff']==staff and not e['grace'] for e in later['events']):
                    candidates.append(later)
            if not candidates:continue
            first=candidates[0]
            if any(abs(g['x']-first['x'])<.35*gap for g in candidates[1:]):continue
            target=next(e['id'] for e in first['events'] if e['staff']==staff and not e['grace'])
            for event in group['events']:
                event['main_anchor_id']=target
                event['main_anchor_inferred']=True
        known = [e['duration'] for e in captured if e['duration'] is not None and not e['grace']]
        fallback = statistics.median(known) if known else .5
        fallback = min(1.0, max(.125, fallback))
        cursor = 0.0
        lanes = defaultdict(float)
        missing_duration = []
        local_missing = False
        local_conflicts = []
        for group in groups:
            known_local = [e['local'] for e in group['events'] if e['local'] is not None]
            if known_local and max(known_local)-min(known_local)>EPS:
                local_conflicts.append(next((e['id'] for e in group['events'] if not e['rest']),None))
            voices = {e['voice'] for e in group['events'] if e['voice'] is not None}
            voice = next(iter(voices)) if len(voices) == 1 else None
            values = [e['span'] if _finite(e['span']) and e['span'] > 0 else e['duration']
                      for e in group['events']]
            # Unmeasured grace notes retain their unresolved real duration.
            # Their placeholder occupies no principal meter time; the actual
            # editable attack can be placed after a user chooses its duration.
            placeholder = 0.0 if all(e['grace'] for e in group['events']) else fallback
            duration = max((d for d in values if d is not None), default=placeholder)
            if known_local:
                local = known_local[0]
            else:
                local = lanes[voice] if voice is not None else cursor
                if not all(e['grace'] for e in group['events']):
                    local_missing = True
            group.update(local=local, duration=duration, voice=voice)
            cursor = max(cursor, local+duration)
            if voice is not None:
                lanes[voice] = local+duration
            else:
                for event in group['events']:
                    if event['voice'] is not None:
                        lanes[event['voice']] = local+(event['duration'] if event['duration'] is not None else placeholder)
            for event in group['events']:
                if event['duration'] is None and not event['grace']:
                    missing_duration.append(event['id'])
        # A proven ornament belongs to its principal attack. Resolve this
        # after building the principal groups, without changing meter duration.
        group_by_id={e['id']:g for g in groups for e in g['events']}
        for group in groups:
            if not all(e['grace'] for e in group['events']):continue
            candidates=[group_by_id.get(i) for e in group['events']
                        for i in ([e['main_anchor_id']] + list(e['main_anchor_ids'])) if i is not None]
            anchors=[g['local'] for g in candidates if g is not None and g is not group]
            if anchors and max(anchors)-min(anchors)<EPS:
                group['local']=anchors[0]
        content_end = max((g['local']+g['duration'] for g in groups), default=0.0)
        # A pickup/terminal bar may be shorter. Inside the piece a printed meter
        # provides the missing trailing interval, without consulting the LH.
        length = verified_length
        length_estimated = length is None
        if length is None:
            if index == 0 or index == len(all_keys)-1:
                length = content_end or meter or 4.0
            else:
                length = max(content_end, meter or 0.0) or 4.0
        roots = []
        note_ids = [e['id'] for g in groups for e in g['events'] if not e['rest']]
        roots.extend(dict(id=identity,kind='onset') for identity in local_conflicts if identity is not None)
        roots.extend(dict(id=group['events'][0]['id'],kind='grace') for group in groups
                     if not group['rest'] and all(e['grace'] for e in group['events'])
                     and any(e['duration'] is None for e in group['events']))
        for identity in missing_duration:
            event = next(e for e in captured if e['id'] == identity)
            if event['rest']:
                after = [e for g in groups for e in g['events'] if not e['rest']
                         and e['x'] is not None and (event['x'] is None or e['x'] > event['x'])]
                target = after[0]['id'] if after else (note_ids[-1] if note_ids else None)
                roots.append(dict(id=target, cause_id=identity, kind='rest'))
            else:
                roots.append(dict(id=identity, kind='duration'))
        # A complete, single rhythmic layer can establish local positions by
        # addition even if the former paired-staff calculation rejected it.
        anchored_graces=all((e['main_anchor_id'] in group_by_id or
                            any(i in group_by_id for i in e['main_anchor_ids']))
                           for e in captured if e['grace'])
        exact_sum = (meter is not None and abs(content_end-meter) < EPS
                     and not missing_duration and anchored_graces)
        estimated = bool(missing_duration or local_conflicts or any(e['left_derived'] for e in captured)
                         or (local_missing and not exact_sum)
                         or (length_estimated and not exact_sum))
        if estimated and not any(r['kind']!='grace' for r in roots) and note_ids:
            roots.append(dict(id=note_ids[0], kind='onset'))
        elif estimated and not roots:
            roots.append(dict(id=None, kind='onset'))
        plans.append(dict(page=key[0], system=key[1], measure=key[2], meter_beats=meter,
            groups=groups, content_end=content_end, length_beats=length,
            roots=roots, estimated=estimated, note_ids=note_ids))
    for index, plan in enumerate(plans):
        for root in plan['roots']:
            if root['id'] is None:
                after = [identity for later in plans[index+1:] for identity in later['note_ids']]
                before = [identity for earlier in plans[:index] for identity in earlier['note_ids']]
                root['id'] = after[0] if after else (before[-1] if before else None)
    return dict(measures=plans, initial_start=0.0,
                source_note_ids=sorted(str(n['id']) for n in notes))


def _manual(event, field):
    return field in event.get('manual_fields', []) and _finite(event.get(field))


def _measure_anchor(event):
    """Only newly explicit local edits opt in; old projects stay absolute."""
    return (event.get('timing_anchor_scope') == 'measure'
            and _manual(event, 'beat') and _finite(event.get('measure_beat'))
            and event['measure_beat'] >= 0)


def _anchor_absolute(event, base):
    return round(base + event['measure_beat'], 6) if _measure_anchor(event) else event['beat']


def _known_complete_tail(plan, notes, rests, meter):
    """Return a safe warning target only for an unambiguous full measure."""
    sources=[source for group in plan['groups'] for source in group['events']]
    plan_notes=[notes[e['id']] for e in sources if not e['rest'] and e['id'] in notes]
    note_ids={n['id'] for n in plan_notes}
    tie_keys=('tie_to','tie_from','tie_to_candidate','tie_from_candidate')
    def target_here(value):
        return isinstance(value,(str,int)) and value in note_ids
    if (any(any(n.get(k) is not None for k in tie_keys) for n in plan_notes)
            or any(target_here(n.get('tie_to')) or target_here(n.get('tie_to_candidate'))
                   for n in notes.values())):
        return None
    voices={e['voice'] for e in sources if e.get('voice') is not None}
    mixed_voice=bool(voices) and any(e.get('voice') is None for e in sources)
    if (len(voices)>1 or mixed_voice
            or any(e.get('grace') or e.get('span') is not None
                   or not _finite(e.get('duration')) for e in sources)
            or any(n.get('excluded') or 'multiple_voices_require_review' in (n.get('issues') or [])
                   for n in plan_notes)
            or any(_duration((rests if e['rest'] else notes).get(e['id'],{})) is None
                   for e in sources)):
        return None
    groups=sorted(plan['groups'],key=lambda g:(g['local'],g['x'] if g['x'] is not None else 0))
    if any(next_group['local'] < group['local']+group['duration']-EPS
           for group,next_group in zip(groups,groups[1:])):
        # A missing voice label is not proof of a single layer: overlapping
        # printed groups can be legitimate independent voices.
        return None
    tail=[g for g in plan['groups']
          if _finite(g.get('local')) and _finite(g.get('duration'))
          and abs(g['local']+g['duration']-meter)<EPS
          and all(_finite(e.get('duration')) and e['duration']>0 for e in g['events'])]
    if not tail:
        return None
    return '末尾休止' if any(g['rest'] for g in tail) else '末尾音长'


def _map_navigation(project, measures, old_boundaries):
    boundaries = {}
    for measure in measures:
        page, system, number = (measure[k] for k in ('page', 'system', 'measure'))
        boundaries[(page, system, number-1)] = measure['start_beat']
        boundaries[(page, system, number)] = measure['start_beat']+measure['length_beats']
    for marker in project.get('repeat_markers', []):
        value = boundaries.get((marker.get('page'), marker.get('system'), marker.get('boundary')))
        if value is not None:
            marker['written_beat'] = round(value, 6)
    brackets = project.get('ending_brackets', [])
    for bracket in brackets:
        for field in ('start', 'end'):
            value = boundaries.get((bracket.get('page'), bracket.get('system'),
                                    bracket.get(field+'_boundary')))
            if value is not None:
                bracket[field+'_beat'] = round(value, 6)
    # Existing section identity, count, user confirmation and marker association
    # survive. Marker-bound sections use source boundaries even when old beats
    # were unknown. Unassociated manual sections retain their explicit times.
    markers = project.get('repeat_markers', [])
    for section in project.get('repeat_sections', []):
        indices = section.get('marker_indices')
        old_end = section.get('end_beat')
        old_first = section.get('first_ending_start_beat')
        old_second = section.get('second_ending_end_beat')
        if isinstance(indices, (list, tuple)) and len(indices) == 2:
            start_index, end_index = indices
            if start_index is None:
                section['start_beat'] = measures[0]['start_beat'] if measures else 0.0
            elif type(start_index) is int and 0 <= start_index < len(markers):
                section['start_beat'] = markers[start_index].get('written_beat')
            if type(end_index) is int and 0 <= end_index < len(markers):
                section['end_beat'] = markers[end_index].get('written_beat')
        else:
            for field in ('start_beat', 'end_beat'):
                original = section.get(field)
                candidates = [boundaries[key] for key, value in old_boundaries.items()
                              if _finite(original) and _finite(value) and abs(original-value) < EPS
                              and key in boundaries]
                if candidates and max(candidates)-min(candidates) < EPS:
                    section[field] = round(candidates[0], 6)
        for field, original in (('first_ending_start_beat', old_first),
                                ('second_ending_end_beat', old_second)):
            if original is None:
                continue
            candidates = [boundaries[key] for key, value in old_boundaries.items()
                          if _finite(value) and abs(original-value) < EPS and key in boundaries]
            if candidates and max(candidates)-min(candidates) < EPS:
                section[field] = round(candidates[0], 6)
        # Source bracket association remains unambiguous after the shift.
        if old_first is not None or old_second is not None:
            first = [b for b in brackets if b.get('end_beat') == section.get('end_beat')
                     and _finite(b.get('start_beat'))
                     and section.get('start_beat', 0) < b['start_beat'] < section['end_beat']]
            second = [b for b in brackets if b.get('start_beat') == section.get('end_beat')
                      and _finite(b.get('end_beat')) and b['end_beat'] > section['end_beat']]
            if len(first) == len(second) == 1:
                section['first_ending_start_beat'] = first[0]['start_beat']
                section['second_ending_end_beat'] = second[0]['end_beat']


def reflow_right_hand_timing(project):
    """Mutate automatic score timing; return project for convenient composition."""
    # A deliberately authored project already has its intended performance
    # timing. Its source picture/staff geometry is for display, not inference.
    if project.get('source_kind')=='manual' and project.get('recognition_performed') is False:
        return project
    state = project.get('right_hand_timing')
    if not isinstance(state, dict) or state.get('version') != VERSION or not state.get('basis'):
        previous=state.get('basis') if isinstance(state,dict) and isinstance(state.get('basis'),dict) else None
        basis = _capture(project,previous)
        if basis is None:
            return project
        state = dict(version=VERSION, basis=basis)
        project['right_hand_timing'] = state
    basis = state['basis']
    notes = {n.get('id'): n for n in project.get('notes', []) if n.get('hand') == 'right'}
    rests = {r.get('id'): r for r in project.get('rests', []) if r.get('hand') == 'right'}
    current_source_ids = sorted(str(n['id']) for n in notes.values()
                                if _key(n) is not None and _x(n) is not None)
    if current_source_ids != basis.get('source_note_ids', current_source_ids):
        refreshed = _capture(project, basis)
        if refreshed is not None:
            basis = state['basis'] = refreshed
    old_boundaries = {}
    for m in state.get('measures', []):
        key = (m['page'], m['system'])
        old_boundaries[key+(m['measure']-1,)] = m['start_beat']
        old_boundaries[key+(m['measure'],)] = m['start_beat']+m['length_beats']
    if not old_boundaries:
        # For first-pass remapping only, absolute source beat is an association
        # key for repeats; it never controls RH measure durations or onsets.
        for event in list(notes.values())+list(rests.values()):
            if _key(event) is None:
                continue
            start = event.get('measure_start_beat')
            local = event.get('measure_beat')
            if not _finite(start) and _finite(event.get('beat')) and _finite(local):
                start = event['beat']-local
            if _finite(start):
                p, s, m = _key(event)
                old_boundaries[(p, s, m-1)] = start
    base = basis.get('initial_start', 0.0)
    dependency = None
    dependency_origin = None
    measures = []
    warnings = defaultdict(set)
    warning_origins = defaultdict(set)
    unresolved_by_measure = []
    for plan_index, plan in enumerate(basis['measures']):
        unresolved = []
        roots=list(plan['roots'])
        for group in plan['groups']:
            for source in group['events']:
                event=notes.get(source['id']) if not source['rest'] else None
                if (event is not None and 'duration_beats' in event.get('manual_fields',[])
                        and _duration(event) is None and source['duration'] is not None
                        and not any(r['id']==source['id'] and r['kind']=='duration' for r in roots)):
                    roots.append(dict(id=source['id'],kind='duration'))
        for root in roots:
            event = notes.get(root['id'])
            if event is None:
                continue
            if root['kind'] in ('duration','grace'):
                fixed = _duration(event) is not None
            elif root['kind'] == 'rest':
                cause = rests.get(root.get('cause_id'), {})
                fixed = _manual(event, 'beat') or _duration(cause) is not None
            else:
                fixed = _manual(event, 'beat')
            if not fixed:
                unresolved.append(root)
                warnings[root['id']].add(root['kind'])
                warning_origins[root['id']].add(plan_index)
        unresolved_by_measure.append(unresolved)
    for index, plan in enumerate(basis['measures']):
        unresolved = unresolved_by_measure[index]
        # An explicit source anchor severs its inherited estimated timing.
        first_members = plan['groups'][0]['events'] if plan['groups'] else []
        first_anchor = next((notes[e['id']] for e in first_members
                             if e['id'] in notes and _manual(notes[e['id']], 'beat')
                             and not _measure_anchor(notes[e['id']])), None)
        if first_anchor is not None:
            first_local = plan['groups'][0]['local']
            # A displayed beat is rounded to six places. Confirming exactly
            # that published value must not replace the full-precision basis
            # with its rounding residue, which would move later notes by 1e-6.
            # Exact comparison preserves a deliberate one-unit edit.
            if first_anchor['beat'] != round(base+first_local, 6):
                base = first_anchor['beat']-first_local
            dependency = None
            dependency_origin = None
        duration_edits = []
        anchor_shift = 0.0
        current_ends = []
        changed_local_anchors = []
        changed_duration_anchors = []
        for group in sorted(plan['groups'], key=lambda g: (g['local'], g['x'] or 0)):
            # An uncertainty affects this attack and its successors, never the
            # earlier attacks in the same measure. A rest-only measure can
            # attach its editable warning to the next printed RH attack.
            group_roots = [e['id'] for e in group['events']
                           if e['id'] in warnings and warnings[e['id']]-{'grace'}]
            if group_roots:
                dependency = group_roots[0]
                dependency_origin = min(warning_origins.get(dependency, {index}))
            original_local = group['local']
            duration_shift = sum(delta for end, delta, voice in duration_edits
                if end <= original_local+EPS and (voice is None or group['voice'] is None
                                                   or voice == group['voice']))
            local = original_local+duration_shift+anchor_shift
            live = [(notes if not e['rest'] else rests).get(e['id']) for e in group['events']]
            live = [e for e in live if e is not None]
            manual_anchors=[e for e in live if _manual(e,'beat')]
            # Explicitly entered beats are user data, not noisy geometric
            # estimates: preserve even a one-microbeat disagreement rather
            # than silently overwriting the second anchor.
            manual_conflict=(len(manual_anchors)>1 and
                             any(_anchor_absolute(e,base)!=_anchor_absolute(manual_anchors[0],base)
                                 for e in manual_anchors[1:]))
            anchor = next(iter(manual_anchors),None)
            if anchor is not None:
                if _measure_anchor(anchor):
                    target = anchor['measure_beat']
                    if target != round(original_local,6) and not anchor.get('excluded'):
                        changed_local_anchors.append(anchor['id'])
                    delta = 0.0 if target==round(local,6) else target-local
                else:
                    predicted = base+local
                    delta = 0.0 if anchor['beat']==round(predicted,6) else anchor['beat']-predicted
                anchor_shift += delta
                local += delta
                if not any(r['kind'] == 'duration' and r['id'] == anchor.get('id')
                           for r in unresolved):
                    # A local anchor confirms position within this measure,
                    # not the unknown absolute start inherited from earlier.
                    if not _measure_anchor(anchor) or dependency_origin == index:
                        dependency = None
                        dependency_origin = None
            current_values = []
            for source in group['events']:
                event = (rests if source['rest'] else notes).get(source['id'])
                if event is None:
                    continue
                value = _duration(event)
                if _finite(source['span']) and source['span'] > 0:
                    value = source['span']
                current_values.append(value if value is not None else group['duration'])
                explicitly_cleared=('beat' in event.get('manual_fields',[]) and not _finite(event.get('beat')))
                absolute=(event.get('beat') if explicitly_cleared
                          else _anchor_absolute(event,base) if manual_conflict and _manual(event,'beat')
                          else round(base+local,6))
                event.update(beat=absolute, start_beat=absolute, written_beat=absolute,
                    measure_start_beat=round(base, 6),
                    measure_beat=round(absolute-base,6) if _finite(absolute) else None,
                    global_measure_index=index+1,
                    timing_estimated=dependency is not None,
                    timing_source_id=dependency, timing_warning=None)
                if _finite(source.get('main_anchor')):
                    event['main_anchor_beat'] = round(base+source['main_anchor']+duration_shift+anchor_shift, 6)
                if not source['rest'] and source['id'] in warnings:
                    rest_warning = 'rest' in warnings[source['id']]
                    grace_warning = 'grace' in warnings[source['id']]
                    if grace_warning:
                        event.update(timing_estimated=True,timing_source_id=source['id'])
                    event['timing_warning'] = ('装饰音无固定时值，主拍位置保留；可设置时值与开始位置。'
                        + ('小节起拍也需要核对。' if warnings[source['id']]-{'grace'} else '')
                        if grace_warning else '相邻休止时长未确定，此处开始时间暂作估计；'
                        '修改此音起拍后，后续时间自动更新。' if rest_warning else
                        '此处开始时间为估计值，后续已按右手节奏接排；'
                        '修改此音起拍或时值后，后续时间自动更新。')
                if manual_conflict and _manual(event,'beat'):
                    event.update(timing_estimated=True,timing_source_id=event.get('id'),
                                 timing_warning='同组音的手动起拍不同，已保留输入，请核对。')
            duration = max(current_values, default=group['duration'])
            voice_groups = defaultdict(list)
            for source in group['events']:
                voice_groups[source['voice']].append(source)
            for voice, sources in voice_groups.items():
                old_length = max((e['span'] if _finite(e['span']) and e['span'] > 0 else e['duration']
                                  if e['duration'] is not None else group['duration']) for e in sources)
                current_lengths = []
                manual_duration_changed = False
                manual_duration_increases = []
                for source in sources:
                    event = (rests if source['rest'] else notes).get(source['id'])
                    value = _duration(event) if event is not None else source['duration']
                    if _finite(source['span']) and source['span'] > 0:
                        value = source['span']
                    original = (source['span'] if _finite(source['span']) and source['span'] > 0
                                else source['duration'])
                    if (event is not None and _manual(event,'duration_beats')
                            and value != original):
                        manual_duration_changed = True
                        if (not source['rest'] and _finite(value) and _finite(original) and value>original
                                and not event.get('excluded')):
                            manual_duration_increases.append((event['id'],value))
                    current_lengths.append(value if value is not None else group['duration'])
                difference = max(current_lengths)-old_length
                if difference>0:
                    changed_duration_anchors.extend(identity for identity,value in manual_duration_increases
                                                    if value==max(current_lengths))
                # Below-EPS noise in untouched values retains old behaviour.
                # Explicit duration edits must still propagate at the 1e-6
                # output-precision boundary, regardless of floating sign.
                if abs(difference) > EPS or (difference != 0 and manual_duration_changed):
                    duration_edits.append((original_local+old_length, difference, voice))
            current_ends.append(local+duration)
        # Manual edits of the principal attack must update its ornament anchor.
        # A deliberately set grace duration retains its own editable start.
        for group in plan['groups']:
            for source in group['events']:
                if not source['grace'] or source['rest']:continue
                event=notes.get(source['id'])
                if event is None:continue
                identifiers=[source.get('main_anchor_id')]+list(source.get('main_anchor_ids') or [])
                targets=[notes[i] for i in identifiers if i in notes and _finite(notes[i].get('beat'))]
                anchors={n['beat'] for n in targets}
                if len(anchors)!=1:continue
                target=targets[0];anchor_beat=target['beat'];event['main_anchor_beat']=anchor_beat
                event['timing_main_anchor_id']=target['id']
                event['timing_anchor_inferred']=source.get('main_anchor_inferred',False)
                if _duration(event) is None and 'beat' not in event.get('manual_fields',[]):
                    event.update(beat=anchor_beat,start_beat=anchor_beat,written_beat=anchor_beat,
                                 measure_beat=round(anchor_beat-base,6))
        content_end = max(current_ends, default=plan['content_end'])
        length = max(EPS, plan['length_beats']+content_end-plan['content_end'])
        # Strict, evidence-bounded warning only. A previously complete,
        # unambiguous single-voice measure with a known printed tail is
        # now longer than its meter after an explicit local onset edit or a
        # manual duration increase. Do not shorten or reinterpret any rests.
        meter=plan.get('meter_beats')
        if ((changed_local_anchors or changed_duration_anchors) and _finite(meter) and meter>0 and not plan.get('estimated')
                and abs(plan['length_beats']-meter)<EPS and abs(plan['content_end']-meter)<EPS
                and content_end>meter+EPS):
            tail=_known_complete_tail(plan,notes,rests,meter)
            if tail:
                source_id=(changed_duration_anchors or changed_local_anchors)[0]
                source_note=notes[source_id]
                reason='音长' if changed_duration_anchors else '开始位置'
                message='本小节超过%g拍，请核对%s和%s。' % (meter,reason,tail)
                existing=source_note.get('timing_warning')
                source_note.update(timing_warning=(existing+'；'+message) if existing else message,
                                   timing_estimated=True,timing_source_id=source_id)
                dependency=source_id
                dependency_origin=index
        measures.append(dict(page=plan['page'], system=plan['system'], measure=plan['measure'],
            start_beat=round(base, 6), length_beats=round(length, 6),
            meter_beats=plan['meter_beats'], timing_estimated=dependency is not None,
            timing_source_id=dependency))
        base += length
    warning_ids = [n.get('id') for n in notes.values() if n.get('timing_warning')]
    state.update(measures=measures, warning_note_ids=warning_ids,
                 warning_notes=len(warning_ids), written_duration_beats=round(base, 6))
    project['written_duration_beats'] = round(base, 6)
    _map_navigation(project, measures, old_boundaries)
    return project
