"""Refine visibly printed fingering evidence without score-specific answers.

This pass runs after the ordinary geometry assignment. It can recover an
unclaimed music-font digit at a unique free stem, and distinguishes a visible
but ambiguous text digit from confirmed absence. Original notes and assigned
digits always win. Musical pitch, rhythm, hand and coordinates are untouched.
"""
from collections import defaultdict
import math
from recognizer_geometry import digit_overlaps_attached_beam

MUSIC_DIGITS={chr(0x130+n):n for n in range(1,6)}
TEXT_DIGITS={str(n):n for n in range(1,6)}
_EPS=1e-7


def _box(value):
    return tuple(round(float(x),3) for x in value)


def _same_ink(a,b):
    """Duplicate glyph draws overlap in relative size, independent of scale."""
    a=_box(a);b=_box(b)
    aw=max(0,a[2]-a[0]);ah=max(0,a[3]-a[1]);bw=max(0,b[2]-b[0]);bh=max(0,b[3]-b[1])
    if not aw or not ah or not bw or not bh:return a==b
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return overlap/min(aw*ah,bw*bh)>=.8


def _claimed_digit(box,value,claims):
    return any((other_value is None or value==other_value) and _same_ink(box,other_box)
               for other_box,other_value in claims)


def _claimed_rhythmic(box,value,claims):
    """A contained overlapping glyph is not the same rhythmic glyph.

    Rhythmic markers carry their exact source box.  A second, smaller printed
    character may be overlaid by the typesetter; ordinary overlap-of-smaller-ink
    is inadequate to identify these two independent glyphs.  Require the two
    glyph bounds to cover nearly the same area before treating them as one.
    """
    a=_box(box)
    aa=max(0,a[2]-a[0])*max(0,a[3]-a[1])
    for other_box,other_value in claims:
        if other_value is not None and value!=other_value:continue
        b=_box(other_box)
        ba=max(0,b[2]-b[0])*max(0,b[3]-b[1])
        if not aa or not ba:
            if a==b:return True
            continue
        intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
        if intersection/max(aa,ba)>=.8:return True
    return False


def _independent_overlapping_rhythm(box,value,claims):
    return _claimed_digit(box,value,claims) and not _claimed_rhythmic(box,value,claims)


def _multiple_source_glyphs(box,value,chars):
    """Same-size, overlaid glyphs of different fonts lack unique identity."""
    fonts=set()
    for char in chars:
        v=MUSIC_DIGITS.get(char.get('char'),TEXT_DIGITS.get(char.get('char')))
        if v==value and char.get('bbox') and _claimed_rhythmic(box,value,[(char['bbox'],v)]):
            fonts.add(char.get('font'))
    return len(fonts)>1


def _outside_tip(digit, event, gap):
    """Return free-stem distances; no note-name or score identity is used."""
    rhythm=event.get('rhythm_evidence',{});stem=rhythm.get('stem')
    if not isinstance(stem,(list,tuple)) or len(stem)!=3:return None
    if not all(type(v) in (int,float) and math.isfinite(v) for v in stem):return None
    if abs(digit['x']-stem[0])>=.35*gap:return None
    direction=rhythm.get('stem_direction');box=digit['bbox']
    if direction=='up':distance=stem[1]-box[3]
    elif direction=='down':distance=box[1]-stem[2]
    else:return None
    if not 0<distance<2*gap:return None
    return distance+abs(digit['x']-stem[0])


def _music_gap(digit,event):
    rhythm=event.get('rhythm_evidence',{});stem=rhythm.get('stem')
    head=event.get('glyph_bbox');y=event['origin'][1]
    low,high=(head[1],head[3]) if isinstance(head,(list,tuple)) and len(head)==4 else (y,y)
    if isinstance(stem,(list,tuple)) and len(stem)==3:
        low=min(low,stem[1]);high=max(high,stem[2])
    return max(low-digit['bbox'][3],digit['bbox'][1]-high,0)


def _head_gap(digit,event):
    head=event.get('glyph_bbox');y=event['origin'][1]
    low,high=(head[1],head[3]) if isinstance(head,(list,tuple)) and len(head)==4 else (y,y)
    return max(low-digit['bbox'][3],digit['bbox'][1]-high,0)


def _other_staff_head_competition(digit,staff,group,jobs,gap):
    """A nearby other-staff head can own ink beyond this staff's long stem.

    A different digit already assigned to that other head is separate evidence
    that this glyph may belong to the target instead, so it is not discarded.
    """
    own=min(_head_gap(digit,e) for e in group)
    own_music=min(_music_gap(digit,e) for e in group)
    value=MUSIC_DIGITS.get(digit.get('char'),TEXT_DIGITS.get(digit.get('char')))
    state=None
    for other_staff,other,_ in jobs:
        if other_staff is staff or other is group:continue
        for event in other:
            if abs(event['origin'][0]-digit['x'])>=1.5*gap:continue
            other_gap=_head_gap(digit,event)
            if other_gap>=1.5*gap:continue
            other_box=event.get('finger_bbox')
            if other_box and (event.get('finger')!=value or not _same_ink(other_box,digit['bbox'])):continue
            if other_gap+.5*gap<own:return 'other'
            if other_gap<=own_music+.5*gap:state='ambiguous'
    return state


def _close_text_neighbor(digit,text_chars,gap):
    """Don't interpret a digit embedded in a word, chord name or page number."""
    box=digit['bbox'];cy=(box[1]+box[3])/2
    for c in text_chars:
        if c is digit or not str(c.get('char','')).isalnum():continue
        b=c.get('bbox')
        if not b or abs((b[1]+b[3])/2-cy)>.3*gap:continue
        if min(abs(b[0]-box[2]),abs(box[0]-b[2]))<.35*gap:return True
    return False


def _bracketed_tuplet(digit, jobs, lines, gap, value, target_staff, target_group):
    """A capped bracket enclosing exactly the numbered note groups is rhythmic."""
    if value not in (2,3,4,5):return False
    b=digit['bbox'];segments=[]
    for x1,y1,x2,y2,width in lines:
        if (abs(y1-y2)<.15*gap and abs(x2-x1)>.7*gap and 0<width<.25*gap
            and b[1]-.3*gap<=y1<=b[3]+.3*gap):
            segments.append((min(x1,x2),max(x1,x2),(y1+y2)/2))
    left=[s for s in segments if 0<=b[0]-s[1]<gap]
    right=[s for s in segments if 0<=s[0]-b[2]<gap]
    matches=[]
    for a in left:
        for z in right:
            if abs(a[2]-z[2])>.2*gap:continue
            y=(a[2]+z[2])/2
            def cap(x):
                return any(abs(x1-x2)<.1*gap and abs(x1-x)<.2*gap
                           and .2*gap<abs(y1-y2)<2*gap
                           and min(abs(y1-y),abs(y2-y))<.2*gap
                           for x1,y1,x2,y2,_ in lines)
            if not (cap(a[0]) and cap(z[1])):continue
            groups=[]
            for staff,group,_ in jobs:
                if staff is not target_staff or not group or not target_group:continue
                if group[0].get('hand')!=target_group[0].get('hand') or group[0].get('measure')!=target_group[0].get('measure'):continue
                members=[e for e in group if e.get('rhythm_evidence',{}).get('stem')
                         and a[0]-.2*gap<=e['rhythm_evidence']['stem'][0]<=z[1]+.2*gap]
                if not members:continue
                stems={tuple(e['rhythm_evidence']['stem']) for e in members}
                for stem in stems:
                    if stem not in groups:groups.append(stem)
            if len(groups)==value:matches.append((a[0],z[1],y))
    return len(matches)==1


def _possible_tuplet(digit,owner,groups,gap,value):
    """A centered numeral near a same-voice beam has unresolved semantics."""
    if value not in (2,3,4,5):return False
    rhythm=owner.get('rhythm_evidence',{});stem=rhythm.get('stem')
    if not stem or not rhythm.get('beams'):return False
    items=[]
    for group in groups:
        events=[e for e in group if e.get('hand')==owner.get('hand')
                and e.get('measure')==owner.get('measure') and e.get('rhythm_evidence',{}).get('stem')
                and e['rhythm_evidence'].get('stem_direction')==rhythm.get('stem_direction')
                and e['rhythm_evidence'].get('beams')]
        if events:items.append(events[0]['rhythm_evidence']['stem'][0])
    items=sorted(set(items));x=stem[0]
    # The candidate must lie within a contiguous n-column window and near its
    # center. Without independent bracket/beam semantics, keep it unresolved.
    for start in range(max(0,len(items)-value+1)):
        window=items[start:start+value]
        if len(window)==value and x in window and abs(digit['x']-(window[0]+window[-1])/2)<.5*gap:
            return True
    return False


def _assign_printed(event,digit,value,gap,method):
    box=list(_box(digit['bbox']))
    event.update(finger=value,finger_source='printed',finger_bbox=box,finger_candidates=[],
                 finger_evidence={'method':method,
                                  'position':'above' if digit['y']<event['origin'][1] else 'below'},
                 source_fingering_state='printed',
                 source_fingering_evidence={'method':'assigned_original_digit','bbox':box})
    event['issues']=[i for i in event.get('issues',[]) if i not in
                     ('fingering_missing_or_ambiguous','right_fingering_below_requires_review',
                      'chord_fingering_order_requires_review')]
    if event.get('hand')=='right' and digit['y']>=event['origin'][1]-.3*gap:
        event['issues'].append('right_fingering_below_requires_review')
    event['confidence']=.55 if event['issues'] else .85


def _reconcile_complete_chord_columns(jobs,digits,rhythmic,lines):
    """Restore only one complete, visible, uniquely owned chord column."""
    all_events=[e for _,group,_ in jobs for e in group]
    count=0;heads=0
    for staff,group,_ in jobs:
        if not 2<=len(group)<=5 or any(e.get('excluded') or e.get('confirmed')
                or e.get('finger_source')=='manual' or 'finger' in e.get('manual_fields',[]) for e in group):
            continue
        if len({e.get('hand') for e in group})!=1 or len({e.get('measure') for e in group})!=1:continue
        rhythms=[e.get('rhythm_evidence',{}) for e in group]
        if any(not isinstance(r.get('stem'),(list,tuple)) or len(r['stem'])!=3 for r in rhythms):continue
        stems={tuple(r['stem']) for r in rhythms};directions={r.get('stem_direction') for r in rhythms}
        if len(stems)!=1 or len(directions)!=1 or next(iter(directions)) not in ('up','down'):continue
        stem=next(iter(stems));direction=next(iter(directions));gap=staff['gap']
        owned_other=[(_box(e['finger_bbox']),e['finger']) for e in all_events
                     if all(e is not member for member in group) and e.get('finger_bbox')
                     and type(e.get('finger')) is int and 1<=e['finger']<=5]
        candidates=[]
        for digit,value,music in digits:
            if (not music or digit['size']>=1.7*gap or abs(digit['x']-stem[0])>=.35*gap
                    or _claimed_digit(digit['bbox'],value,owned_other)
                    or _claimed_rhythmic(digit['bbox'],value,rhythmic)):continue
            distance=(stem[1]-digit['bbox'][3]) if direction=='up' else (digit['bbox'][1]-stem[2])
            if not 0<distance<(2+1.8*(len(group)-1))*gap:continue
            if _other_staff_head_competition(digit,staff,group,jobs,gap):continue
            if _bracketed_tuplet(digit,jobs,lines,gap,value,staff,group):continue
            candidates.append((digit,value))
        if len(candidates)!=len(group) or len({value for _,value in candidates})!=len(group):continue
        ordered=sorted(candidates,key=lambda item:(item[0]['bbox'][1]+item[0]['bbox'][3])/2)
        centers=[(d['bbox'][1]+d['bbox'][3])/2 for d,_ in ordered]
        spacings=[b-a for a,b in zip(centers,centers[1:])]
        if any(not .8*gap<delta<1.8*gap for delta in spacings):continue
        if max(spacings,default=0)-min(spacings,default=0)>.3*gap:continue
        if any(a[0]['bbox'][3]>b[0]['bbox'][1]+.1*gap for a,b in zip(ordered,ordered[1:])):continue
        anchor=ordered[-1][0] if direction=='up' else ordered[0][0]
        if not any(_outside_tip(anchor,e,gap) is not None for e in group):continue
        # Do not claim a label that also reaches another unresolved voice or
        # stem, including another voice on the same staff. Already-resolved
        # neighbors with a distinct label cannot take this column glyph.
        competing=False
        for digit,value in ordered:
            own=min(_music_gap(digit,e) for e in group)
            for _,other,_ in jobs:
                if other is group:continue
                for event in other:
                    if event.get('excluded'):continue
                    other_box=event.get('finger_bbox')
                    if (event.get('finger') is not None and other_box
                            and not _same_ink(other_box,digit['bbox'])):continue
                    if (_outside_tip(digit,event,gap) is not None
                            or abs(event['origin'][0]-digit['x'])<1.5*gap
                            and _music_gap(digit,event)+.5*gap<own):
                        competing=True;break
                if competing:break
            if competing:break
        if competing:continue
        # Every preexisting printed value must refer to an actual column digit;
        # this prevents silently taking a separate neighboring note's label.
        if any(e.get('finger') is not None and (e.get('finger_source')!='printed' or not e.get('finger_bbox')
            or not any(e['finger']==value and _same_ink(e['finger_bbox'],d['bbox']) for d,value in ordered))
               for e in group):continue
        ordered_notes=sorted(group,key=lambda e:e['origin'][1])
        if all(e.get('finger')==value and e.get('finger_bbox') and _same_ink(e['finger_bbox'],d['bbox'])
               for e,(d,value) in zip(ordered_notes,ordered)):continue
        prior_missing=sum(e.get('finger') is None for e in group)
        for event,(digit,value) in zip(ordered_notes,ordered):
            _assign_printed(event,digit,value,gap,'complete_unique_chord_fingering_column')
        count+=1;heads+=prior_missing
    return count,heads


def _reconcile_head_side_columns(jobs,digits,rhythmic,lines):
    """A complete chord column may be aligned with a displaced note head.

    Its nearest label must be on the head side, and closer to this chord
    than to any competing unlabelled note. Already claimed digits, tuplets,
    extra labels, user edits, and competing ownership are never guessed.
    """
    all_events=[e for _,group,_ in jobs for e in group]
    restored=0
    for staff,group,groups in jobs:
        if not group or any(e.get('hand')!='right' for e in group):continue
        if not 2<=len(group)<=5 or any(e.get('excluded') or e.get('confirmed')
                or e.get('finger_source')=='manual' or 'finger' in e.get('manual_fields',[]) for e in group):continue
        if len({e.get('hand') for e in group})!=1 or len({e.get('measure') for e in group})!=1:continue
        rhythms=[e.get('rhythm_evidence',{}) for e in group]
        if any(not isinstance(r.get('stem'),(list,tuple)) or len(r['stem'])!=3 for r in rhythms):continue
        stems={tuple(r['stem']) for r in rhythms};directions={r.get('stem_direction') for r in rhythms}
        if len(stems)!=1 or len(directions)!=1 or next(iter(directions)) not in ('up','down'):continue
        direction=next(iter(directions));gap=staff['gap']
        head_x=[e['origin'][0] for e in group];head_y=[e['origin'][1] for e in group]
        owned_other=[(_box(e['finger_bbox']),e['finger']) for e in all_events
                     if all(e is not member for member in group) and e.get('finger_bbox')
                     and type(e.get('finger')) is int and 1<=e['finger']<=5]
        candidates=[]
        for digit,value,music in digits:
            if not music or digit['size']>=1.7*gap:continue
            if not any(abs(digit['x']-x)<.35*gap for x in head_x):continue
            if _claimed_digit(digit['bbox'],value,owned_other) or _claimed_rhythmic(digit['bbox'],value,rhythmic):continue
            if direction=='up':distance=digit['bbox'][1]-max(head_y)
            else:distance=min(head_y)-digit['bbox'][3]
            if not 0<distance<(2+1.8*(len(group)-1))*gap:continue
            if _bracketed_tuplet(digit,jobs,lines,gap,value,staff,group):continue
            if any(_possible_tuplet(digit,e,groups,gap,value) for e in group):continue
            candidates.append((digit,value))
        if len(candidates)!=len(group) or len({v for _,v in candidates})!=len(group):continue
        ordered=sorted(candidates,key=lambda item:(item[0]['bbox'][1]+item[0]['bbox'][3])/2)
        centers=[(d['bbox'][1]+d['bbox'][3])/2 for d,_ in ordered]
        spacings=[b-a for a,b in zip(centers,centers[1:])]
        if any(not .8*gap<delta<1.8*gap for delta in spacings):continue
        if max(spacings,default=0)-min(spacings,default=0)>.3*gap:continue
        if max(d['x'] for d,_ in ordered)-min(d['x'] for d,_ in ordered)>=.35*gap:continue
        if any(a[0]['bbox'][3]>b[0]['bbox'][1]+.1*gap for a,b in zip(ordered,ordered[1:])):continue
        anchor=ordered[0][0] if direction=='up' else ordered[-1][0]
        anchor_gap=min(_head_gap(anchor,e) for e in group)
        if not 0<anchor_gap<2*gap:continue
        # A nearby other voice/head can own the label. Existing separate
        # labelled notes do not compete, but unlabelled heads do.
        ambiguous=False
        for _,other,_ in jobs:
            if other is group:continue
            for event in other:
                if event.get('excluded'):continue
                if abs(event['origin'][0]-anchor['x'])>=1.5*gap:continue
                other_box=event.get('finger_bbox')
                if event.get('finger') is not None and other_box and not _same_ink(other_box,anchor['bbox']):continue
                if _head_gap(anchor,event)<=anchor_gap+.5*gap:
                    ambiguous=True;break
            if ambiguous:break
        if ambiguous:continue
        # Do not extend an apparently complete column into an unlabelled
        # neighboring note's own space, even when the first digit is clearly
        # anchored to this chord. The distant digit may be the other hand's.
        for digit,value in ordered:
            own=min(_head_gap(digit,e) for e in group)
            for _,other,_ in jobs:
                if other is group:continue
                for event in other:
                    if event.get('excluded') or abs(event['origin'][0]-digit['x'])>=1.5*gap:continue
                    other_box=event.get('finger_bbox')
                    if event.get('finger') is not None and other_box and not _same_ink(other_box,digit['bbox']):continue
                    if _head_gap(digit,event)+.5*gap<own:
                        ambiguous=True;break
                if ambiguous:break
            if ambiguous:break
        if ambiguous:continue
        # Every existing assignment must be explained by this very column.
        if any(e.get('finger') is not None and (e.get('finger_source')!='printed' or not e.get('finger_bbox')
            or not any(e['finger']==v and _same_ink(e['finger_bbox'],d['bbox']) for d,v in ordered)) for e in group):continue
        ordered_notes=sorted(group,key=lambda e:e['origin'][1])
        if all(e.get('finger')==value and e.get('finger_bbox') and _same_ink(e['finger_bbox'],d['bbox'])
               for e,(d,value) in zip(ordered_notes,ordered)):continue
        for event,(digit,value) in zip(ordered_notes,ordered):
            _assign_printed(event,digit,value,gap,'complete_head_side_chord_fingering_column')
        restored+=1
    return restored


def _mark_competing_chord_columns(jobs,digits,rhythmic,lines):
    """Expose a plausible right chord column already owned by another staff.

    A competing complete music-font column is evidence of uncertainty, not
    proof to steal a label. Preserve manual/confirmed notes and the other hand.
    """
    all_events=[e for _,group,_ in jobs for e in group];count=0
    for staff,group,groups in jobs:
        if not 2<=len(group)<=5 or any(e.get('hand')!='right' or e.get('excluded') or e.get('confirmed')
               or e.get('finger_source')=='manual' or 'finger' in e.get('manual_fields',[]) for e in group):continue
        if len({e.get('measure') for e in group})!=1:continue
        rhythms=[e.get('rhythm_evidence',{}) for e in group]
        if any(not isinstance(r.get('stem'),(list,tuple)) or len(r['stem'])!=3 for r in rhythms):continue
        stems={tuple(r['stem']) for r in rhythms};directions={r.get('stem_direction') for r in rhythms}
        if len(stems)!=1 or len(directions)!=1 or next(iter(directions)) not in ('up','down'):continue
        stem=next(iter(stems));gap=staff['gap'];head_x=[e['origin'][0] for e in group]
        low=min(stem[1],*(e['origin'][1] for e in group));high=max(stem[2],*(e['origin'][1] for e in group))
        possible=[]
        for digit,value,music in digits:
            if not music or digit['size']>=1.7*gap or _claimed_rhythmic(digit['bbox'],value,rhythmic):continue
            if not any(abs(digit['x']-x)<.35*gap for x in [stem[0],*head_x]):continue
            side='above' if digit['bbox'][3]<low else 'below' if digit['bbox'][1]>high else None
            if side is None:continue
            distance=low-digit['bbox'][3] if side=='above' else digit['bbox'][1]-high
            if not 0<distance<(2+1.8*(len(group)-1))*gap:continue
            if _bracketed_tuplet(digit,jobs,lines,gap,value,staff,group):continue
            if any(_possible_tuplet(digit,e,groups,gap,value) for e in group):continue
            owners=[e for e in all_events if e.get('finger_bbox') and e.get('finger')==value
                    and _same_ink(e['finger_bbox'],digit['bbox'])]
            if any(e not in group and e.get('hand')!='left' for e in owners):continue
            possible.append((digit,value,side,owners))
        if len(possible)!=len(group) or len({v for _,v,_,_ in possible})!=len(group):continue
        if len({s for _,_,s,_ in possible})!=1:continue
        ordered=sorted(possible,key=lambda p:(p[0]['bbox'][1]+p[0]['bbox'][3])/2)
        if max(p[0]['x'] for p in ordered)-min(p[0]['x'] for p in ordered)>=.35*gap:continue
        centers=[(p[0]['bbox'][1]+p[0]['bbox'][3])/2 for p in ordered]
        spacings=[b-a for a,b in zip(centers,centers[1:])]
        if any(not .8*gap<delta<1.8*gap for delta in spacings):continue
        if max(spacings,default=0)-min(spacings,default=0)>.3*gap:continue
        if any(a[0]['bbox'][3]>b[0]['bbox'][1]+.1*gap for a,b in zip(ordered,ordered[1:])):continue
        anchor=ordered[-1][0] if ordered[0][2]=='above' else ordered[0][0]
        anchor_distance=low-anchor['bbox'][3] if ordered[0][2]=='above' else anchor['bbox'][1]-high
        if not 0<anchor_distance<2*gap:continue
        if not any(any(e not in group and e.get('hand')=='left' for e in owners) for _,_,_,owners in ordered):continue
        # One digit of this very column must already belong to this right
        # chord; otherwise an intact left-hand column may be only coincident.
        if not any(any(any(owner is member for member in group) for owner in owners) for _,_,_,owners in ordered):continue
        boxes=[list(_box(p[0]['bbox'])) for p in ordered];values=[p[1] for p in ordered]
        for event,(_,expected,_,_) in zip(sorted(group,key=lambda e:e['origin'][1]),ordered):
            # A competing column is not sufficient proof to remove an
            # existing printed assignment, even if ordering looks suspicious.
            if event.get('finger') is not None:continue
            event['finger_candidates']=values[:]
            event['source_fingering_state']='unresolved'
            event['source_fingering_evidence']={'method':'possible_shared_column_between_staves','candidate_bboxes':boxes}
            if 'fingering_missing_or_ambiguous' not in event.get('issues',[]):event.setdefault('issues',[]).append('fingering_missing_or_ambiguous')
            event['confidence']=.55;count+=1
    return count


def _reconcile_two_unique_stems(jobs,digits,rhythmic,lines):
    """Repair crossed ownership only when both physical stem labels are unique."""
    singles=[(staff,group,groups,group[0]) for staff,group,groups in jobs if len(group)==1]
    all_events=[e for _,group,_ in jobs for e in group]
    music=[(c,v) for c,v,is_music in digits if is_music]
    music_by_box=defaultdict(list)
    for c,v in music:music_by_box[_box(c['bbox'])].append((c,v))
    repaired=0
    for staff,group,groups,target in singles:
        if target.get('excluded') or target.get('finger') is not None or 'finger' in target.get('manual_fields',[]):continue
        gap=staff['gap'];possibilities=[]
        for other_staff,other_group,other_groups,owner in singles:
            if (other_staff is not staff or other_group is group or owner.get('excluded') or owner.get('finger') is None
                    or owner.get('finger_source')!='printed' or 'finger' in owner.get('manual_fields',[])
                    or owner.get('confirmed')):continue
            if target.get('hand')!=owner.get('hand') or target.get('measure')!=owner.get('measure'):continue
            current_box=owner.get('finger_bbox')
            if not current_box:continue
            first=music_by_box.get(_box(current_box),[]) or [(c,v) for c,v in music
                    if v==owner.get('finger') and _same_ink(c['bbox'],current_box)]
            if len(first)!=1:continue
            first_digit,first_value=first[0]
            if (_claimed_rhythmic(first_digit['bbox'],first_value,rhythmic) or _outside_tip(first_digit,target,gap) is None
                    or _outside_tip(first_digit,owner,gap) is not None):continue
            owned=[(_box(e['finger_bbox']),e['finger']) for e in all_events if e.get('finger_bbox') and e.get('finger') is not None]
            choices=[]
            for second_digit,second_value in music:
                if (_claimed_digit(second_digit['bbox'],second_value,owned) or _claimed_rhythmic(second_digit['bbox'],second_value,rhythmic) or second_digit['size']>=1.7*gap
                        or _outside_tip(second_digit,owner,gap) is None
                        or _outside_tip(second_digit,target,gap) is not None):continue
                choices.append((second_digit,second_value))
            if len(choices)!=1:continue
            second_digit,second_value=choices[0]
            if (_other_staff_head_competition(first_digit,staff,group,jobs,gap)
                    or _other_staff_head_competition(second_digit,staff,other_group,jobs,gap)):continue
            if (_possible_tuplet(first_digit,target,groups,gap,first_value)
                    or _possible_tuplet(second_digit,owner,other_groups,gap,second_value)
                    or _bracketed_tuplet(first_digit,jobs,lines,gap,first_value,staff,group)
                    or _bracketed_tuplet(second_digit,jobs,lines,gap,second_value,staff,other_group)):
                continue
            others=[e for e in all_events if e is not target and e is not owner]
            if any(_outside_tip(first_digit,e,gap) is not None or _outside_tip(second_digit,e,gap) is not None
                   for e in others):continue
            if any(abs(e['origin'][0]-first_digit['x'])<1.5*gap
                   and _music_gap(first_digit,e)+.5*gap<_music_gap(first_digit,target)
                   or abs(e['origin'][0]-second_digit['x'])<1.5*gap
                   and _music_gap(second_digit,e)+.5*gap<_music_gap(second_digit,owner) for e in others):
                continue
            possibilities.append((owner,first_digit,first_value,second_digit,second_value))
        if len(possibilities)==1:
            owner,first_digit,first_value,second_digit,second_value=possibilities[0]
            _assign_printed(owner,second_digit,second_value,gap,'unique_free_stem_ownership_reconciled')
            _assign_printed(target,first_digit,first_value,gap,'unique_free_stem_ownership_reconciled')
            repaired+=1
    return repaired


def _mark_owned_digit_competition(jobs,digits,rhythmic,lines):
    """Expose a genuine stem/head ownership tie without moving the digit."""
    singles=[(staff,group,groups,group[0]) for staff,group,groups in jobs if len(group)==1]
    all_events=[e for _,group,_ in jobs for e in group];count=0
    music_by_box=defaultdict(list)
    for digit,value,is_music in digits:
        if is_music:music_by_box[_box(digit['bbox'])].append((digit,value))
    for staff,group,groups,target in singles:
        if target.get('excluded') or target.get('finger') is not None or target.get('source_fingering_state')!='unmarked':continue
        if 'finger' in target.get('manual_fields',[]):continue
        gap=staff['gap'];possible=[]
        for other_staff,other_group,_,owner in singles:
            if (other_staff is not staff or other_group is group or owner.get('excluded') or owner.get('finger_source')!='printed'
                    or owner.get('finger') is None or not owner.get('finger_bbox')):continue
            if target.get('hand')!=owner.get('hand') or target.get('measure')!=owner.get('measure'):continue
            matches=music_by_box.get(_box(owner['finger_bbox']),[]) or [(d,v) for d,v,is_music in digits
                    if is_music and v==owner.get('finger') and _same_ink(d['bbox'],owner['finger_bbox'])]
            if len(matches)!=1:continue
            digit,value=matches[0];box=_box(digit['bbox'])
            if (_claimed_rhythmic(box,value,rhythmic) or _outside_tip(digit,target,gap) is None
                    or _outside_tip(digit,owner,gap) is not None
                    or _other_staff_head_competition(digit,staff,group,jobs,gap)=='other'
                    or _possible_tuplet(digit,target,groups,gap,value)
                    or _bracketed_tuplet(digit,jobs,lines,gap,value,staff,group)):continue
            others=[e for e in all_events if e is not target and e is not owner]
            if any(_outside_tip(digit,e,gap) is not None for e in others):continue
            if any(abs(e['origin'][0]-digit['x'])<1.5*gap
                   and _music_gap(digit,e)+.5*gap<_music_gap(digit,target) for e in others):continue
            possible.append(box)
        if len(possible)==1:
            target['source_fingering_state']='unresolved'
            target['source_fingering_evidence']={'method':'printed_digit_competes_with_adjacent_stem',
                                                  'candidate_bboxes':[list(possible[0])]}
            if 'fingering_missing_or_ambiguous' not in target.get('issues',[]):
                target.setdefault('issues',[]).append('fingering_missing_or_ambiguous')
            count+=1
    return count


def refine_fingering_evidence(jobs,staves,chars,head_rhythms,text_chars=(),lines=()):
    """Mutate only source fingering fields; return small diagnostic counts.

    `jobs` is the existing `(staff, group, groups)` structure. Call immediately
    after the existing `_assign_page_fingerings` and pass the actual page lines.
    Unassigned/competing text and beam-centered numbers are never guessed.
    """
    del staves,head_rhythms
    events=[e for _,group,_ in jobs for e in group]
    rhythmic=[(_box(t['marker_bbox']),t.get('actual')) for e in events
              for t in [e.get('rhythm_evidence',{}).get('tuplet')]
              if isinstance(t,dict) and t.get('marker_bbox')]
    digits=[];seen=[]
    for c in list(chars)+list(text_chars):
        char=c.get('char');music=char in MUSIC_DIGITS
        if not music and (char not in TEXT_DIGITS or c.get('font')=='Aloisen'):continue
        if not c.get('bbox') or 'x' not in c or 'size' not in c:continue
        key=_box(c['bbox'])
        value=MUSIC_DIGITS[char] if music else TEXT_DIGITS[char]
        if _claimed_digit(key,value,seen):continue
        seen.append((key,value));digits.append((c,value,music))
    stats=defaultdict(int)
    # Even if the old head-column heuristic already noticed a number, a
    # physically capped tuplet bracket supplies independent contrary evidence.
    for digit,value,_ in digits:
        key=_box(digit['bbox'])
        for staff,group,_ in jobs:
            visible=any(key in {_box(b) for b in e.get('source_fingering_evidence',{}).get('candidate_bboxes',[])}
                        or (e.get('finger_bbox') and _box(e['finger_bbox'])==key) for e in group)
            if not visible:continue
            if (_claimed_rhythmic(key,value,rhythmic)
                    and _multiple_source_glyphs(key,value,list(chars)+list(text_chars))):
                for event in group:
                    if (event.get('finger_source')!='printed' or not event.get('finger_bbox')
                            or _box(event['finger_bbox'])!=key or event.get('confirmed')
                            or 'finger' in event.get('manual_fields',[])):continue
                    event.update(finger=None,finger_source=None,finger_candidates=[],source_fingering_state='unresolved',
                                 source_fingering_evidence={'method':'overlapping_source_glyphs_require_review','candidate_bboxes':[list(key)]})
                    event.pop('finger_bbox',None);event.pop('finger_evidence',None)
                    if 'fingering_missing_or_ambiguous' not in event.get('issues',[]):
                        event.setdefault('issues',[]).append('fingering_missing_or_ambiguous')
                    event['confidence']=.55
                    stats['overlapping_glyphs_unresolved']+=1
                continue
            proved=(_claimed_rhythmic(key,value,rhythmic) or (not _independent_overlapping_rhythm(key,value,rhythmic) and _bracketed_tuplet(digit,jobs,lines,staff['gap'],value,staff,group)))
            if not proved:continue
            if not _claimed_rhythmic(key,value,rhythmic):stats['bracketed_tuplets']+=1
            rhythmic.append((key,value))
            for event in group:
                if (event.get('excluded') or event.get('finger_source')!='printed' or not event.get('finger_bbox')
                        or _box(event['finger_bbox'])!=key or event.get('confirmed')
                        or 'finger' in event.get('manual_fields',[])):continue
                event.update(finger=None,finger_source=None,finger_candidates=[],source_fingering_state='unmarked',
                             source_fingering_evidence={'method':'number_proved_rhythmic','candidate_bboxes':[]})
                event.pop('finger_bbox',None);event.pop('finger_evidence',None)
                event['issues']=[i for i in event.get('issues',[]) if i not in
                                 ('right_fingering_below_requires_review','chord_fingering_order_requires_review')]
                event['confidence']=.55 if event['issues'] else .85
                stats['incorrect_tuplet_assignments_removed']+=1
    stats['reconciled_chord_columns'],stats['chord_heads_recovered']=_reconcile_complete_chord_columns(jobs,digits,rhythmic,lines)
    stats['head_side_chord_columns']=_reconcile_head_side_columns(jobs,digits,rhythmic,lines)
    stats['reconciled_pairs']=_reconcile_two_unique_stems(jobs,digits,rhythmic,lines)
    stats['cross_staff_column_uncertain']=_mark_competing_chord_columns(jobs,digits,rhythmic,lines)
    owned=[(_box(e['finger_bbox']),e['finger']) for e in events
           if e.get('finger_bbox') and type(e.get('finger')) is int and 1<=e['finger']<=5]
    stats['ownership_conflicts']=_mark_owned_digit_competition(jobs,digits,rhythmic,lines)
    for digit,value,music in digits:
        box=_box(digit['bbox'])
        if _claimed_digit(box,value,owned) or _claimed_rhythmic(box,value,rhythmic):continue
        claims=[]
        for index,(staff,group,groups) in enumerate(jobs):
            gap=staff['gap']
            if digit['size']>=1.7*gap:continue
            if not music and _close_text_neighbor(digit,text_chars,gap):continue
            unresolved=[e for e in group if not e.get('excluded') and e.get('finger') is None]
            if not unresolved:continue
            distances=[_outside_tip(digit,e,gap) for e in unresolved]
            distances=[d for d in distances if d is not None]
            if distances:claims.append((min(distances)/gap,index,staff,group,groups))
        if not claims:continue
        claims.sort(key=lambda item:item[0]);best=claims[0][0]
        tied=[c for c in claims if c[0]-best<.5]
        if not _independent_overlapping_rhythm(box,value,rhythmic) and _bracketed_tuplet(digit,jobs,lines,tied[0][2]['gap'],value,tied[0][2],tied[0][3]):
            rhythmic.append((box,value));stats['bracketed_tuplets']+=1;continue
        for _,index,staff,group,groups in tied:
            gap=staff['gap']
            competition=_other_staff_head_competition(digit,staff,group,jobs,gap)
            if competition=='other':continue
            # A visible glyph belonging clearly closer to a different music
            # envelope must not become a candidate for this group.
            own=min(_music_gap(digit,e) for e in group)
            closer=any(other is not group and any(
                abs(e['origin'][0]-digit['x'])<1.5*gap and _music_gap(digit,e)+.5*gap<own
                for e in other) for _,other,_ in jobs)
            if closer:continue
            overlapping_different_value=any(other_value!=value and _same_ink(box,other_box)
                                            for other_box,other_value in seen)
            ambiguous=(len(tied)>1 or len(group)!=1 or not music or competition=='ambiguous'
                       or overlapping_different_value)
            ambiguous |= any(_possible_tuplet(digit,e,groups,gap,value) for e in group)
            for event in group:
                if event.get('excluded') or event.get('finger') is not None or 'finger' in event.get('manual_fields',[]):continue
                if ambiguous:
                    evidence=event.setdefault('source_fingering_evidence',{})
                    boxes=evidence.setdefault('candidate_bboxes',[])
                    if list(box) not in boxes:boxes.append(list(box))
                    evidence['method']='unassigned_free_stem_digit_requires_review'
                    event['source_fingering_state']='unresolved'
                    stats['ambiguous']+=1
                else:
                    _assign_printed(event,digit,value,gap,'unique_unclaimed_digit_at_free_stem')
                    owned.append((box,value));stats['recovered']+=1
    # Existing unresolved candidates are sometimes actually the already-owned
    # digit of the other hand or an explicitly bracketed tuplet. Remove only
    # such proven candidates; preserve partial-chord ambiguity otherwise.
    for staff,group,_ in jobs:
        for event in group:
            if event.get('excluded') or event.get('finger') is not None or event.get('source_fingering_state')!='unresolved':continue
            evidence=event.get('source_fingering_evidence',{});prior=evidence.get('candidate_bboxes',[])
            if evidence.get('method') in ('printed_digit_competes_with_adjacent_stem','overlapping_source_glyphs_require_review','possible_shared_column_between_staves'):continue
            if not prior:continue
            kept=[]
            for b in prior:
                key=_box(b)
                matches=[(d,v) for d,v,_ in digits if _box(d['bbox'])==key]
                if not matches:matches=[(d,v) for d,v,_ in digits if _same_ink(d['bbox'],key)]
                if len({v for _,v in matches})>1:
                    kept.append(b);continue
                candidate,value=matches[0] if matches else (None,None)
                if value is not None and (_claimed_digit(key,value,owned) or _claimed_rhythmic(key,value,rhythmic)):continue
                if candidate is not None:
                    gap=staff['gap'];own=min(_music_gap(candidate,e) for e in group)
                    if _other_staff_head_competition(candidate,staff,group,jobs,gap)=='other':continue
                    closer=any(other is not group and any(
                        abs(e['origin'][0]-candidate['x'])<1.5*gap
                        and _music_gap(candidate,e)+.5*gap<own for e in other)
                        for _,other,_ in jobs)
                    if closer:continue
                kept.append(b)
            if kept==prior:continue
            event['source_fingering_evidence']={'method':'unassigned_visible_digit' if kept else 'no_unassigned_digit_in_column',
                                                 'candidate_bboxes':kept}
            if not kept:
                event['source_fingering_state']='unmarked';stats['proven_not_fingering']+=1
    # Some exporters expose a numeral-shaped text object inside the already
    # drawn stem and beam ink. It is not safe to call that printed fingering.
    # Keep the source ambiguity explicit; never overwrite a reviewed value.
    event_gaps={id(e):staff['gap'] for staff,group,_ in jobs for e in group}
    for digit,value,music in digits:
        if not music:continue
        key=_box(digit['bbox'])
        assigned=[e for e in events if e.get('finger_source')=='printed' and e.get('finger_bbox')
                  and _box(e['finger_bbox'])==key and not e.get('confirmed')
                  and 'finger' not in e.get('manual_fields',[])]
        for event in assigned:
            if not digit_overlaps_attached_beam(digit,[event],event_gaps[id(event)],lines):continue
            event.update(finger=None,finger_source=None,finger_candidates=[],source_fingering_state='unresolved',
                source_fingering_evidence={'method':'digit_overlaps_attached_music_beam','candidate_bboxes':[list(key)]})
            event.pop('finger_bbox',None);event.pop('finger_evidence',None)
            event['issues']=[i for i in event.get('issues',[]) if i not in
                ('right_fingering_below_requires_review','chord_fingering_order_requires_review')]
            if 'fingering_missing_or_ambiguous' not in event['issues']:
                event['issues'].append('fingering_missing_or_ambiguous')
            event['confidence']=.55;stats['music_ink_assignments_unresolved']+=1
    return dict(stats)
