"""Conservative engraving geometry; no score identity or learned parameters.

Candidates require directly printed shapes and unique voice/group ownership.
Coordinates and tolerances scale with the detected staff spacing.
"""
from statistics import median


def _line_y(line,x):
    x1,y1,x2,y2,_=line
    return y1+(y2-y1)*(x-x1)/(x2-x1)


def _beam_stems(line,items,gap):
    x1,y1,x2,y2,width=line
    if not .3*gap<=width<=.9*gap or abs(x2-x1)<gap:return []
    lo,hi=sorted((x1,x2));tol=max(.2*gap,width/2+.05*gap)
    matches={}
    for head,staff,rhythm in items:
        stem=rhythm.get('stem');direction=rhythm.get('stem_direction')
        if not stem or direction not in ('up','down') or not lo-tol<=stem[0]<=hi+tol:continue
        end=stem[1] if direction=='up' else stem[2]
        if abs(_line_y(line,stem[0])-end)>.6*gap:continue
        matches.setdefault(tuple(stem),[]).append((head,staff,rhythm))
    return sorted(matches.values(),key=lambda g:g[0][2]['stem'][0])


def _isolated_marker(marker,text_chars):
    """A numeral inside a same-line character run has ambiguous semantics.

    Fingering such as '3 2 1' may use ordinary text fonts. Nearby characters
    separated by less than one glyph width disqualify the whole marker.
    This is a typography condition, independent of musical note spacing.
    """
    box=marker['bbox'];cy=(box[1]+box[3])/2
    for other in text_chars:
        if other is marker or other.get('font')!=marker.get('font'):continue
        if not str(other.get('char','')).isalnum() or not other.get('bbox'):continue
        b=other['bbox'];oy=(b[1]+b[3])/2
        if abs(cy-oy)>.5*max(box[3]-box[1],b[3]-b[1]):continue
        separation=max(box[0]-b[2],b[0]-box[2],0)
        if separation<max(box[2]-box[0],b[2]-b[0]):return False
    return True


def cross_staff_beam_hands(staves,head_rhythms,lines):
    """A beam anchored inside one staff can carry a remote head's long stem.

    At least two ordinary stems in the anchor staff are required.  An
    inter-staff beam with equal competing staff anchors stays unresolved.
    Printed staff ownership and pitch are deliberately untouched.
    """
    claims={}
    for upper in staves:
        lower=next((s for s in staves if s.get('upper_partner') is not None
                    and staves[s['upper_partner']] is upper),None)
        if lower is None or upper.get('hand')!='right' or lower.get('hand')!='left':continue
        if upper.get('system')!=lower.get('system'):continue
        gap=upper['gap']
        if abs(lower['gap']-gap)>.1*gap:continue
        items=[(h,s,head_rhythms[id(h)][1]) for s in (upper,lower) for h in s.get('heads',[])]
        for line in lines:
            groups=_beam_stems(line,items,gap)
            if len(groups)<3:continue
            flat=[i for g in groups for i in g]
            directions={r.get('stem_direction') for _,_,r in flat}
            if len(directions)!=1:continue
            direction=next(iter(directions))
            anchors=[(h,s,r) for h,s,r in flat if s is upper
                     and r['stem'][2]-r['stem'][1]<6*gap]
            if len({tuple(r['stem']) for _,_,r in anchors})<2:continue
            targets=[(h,s,r) for h,s,r in flat if s is lower]
            if not targets:continue
            if any(r['stem'][2]-r['stem'][1]<=8*gap for _,_,r in targets):continue
            if direction!='up':continue
            if any(not upper['top']-gap<=r['stem'][1]<=upper['bottom']+gap for _,_,r in targets):continue
            for head,_,rhythm in targets:
                claims.setdefault(id(head),[]).append({
                    'hand':'right','voice_staff':upper['id'],
                    'method':'continuous_beam_from_paired_staff_voice',
                    'beam':[round(v,3) for v in line],
                    'anchor_stems':[r['stem'] for _,_,r in anchors]})
    return {key:values[0] for key,values in claims.items()
            if len({(v['hand'],v['voice_staff']) for v in values})==1}


def _marker_in_fingering_row(marker,text_chars,groups,gap,line):
    """Other digit labels on distinct stems disqualify a tuplet reading.

    A finger row is spaced by notes, so typography's one-glyph-width word
    test cannot detect it. Its digits may mix text and music fonts. Require
    another visible finger-value column in this actual beam family. Even a
    partial finger row makes the numeral's role ambiguous.
    """
    box=marker['bbox'];cx=(box[0]+box[2])/2
    row_offset=(box[1]+box[3])/2-_line_y(line,cx)
    actual=int(marker['char']);columns=set()
    for char in text_chars:
        if char is marker or not char.get('bbox'):continue
        value=(int(char['char']) if str(char.get('char','')) in ('1','2','3','4','5')
               else ord(char['char'])-0x130 if isinstance(char.get('char'),str) and len(char['char'])==1
                    and 0x131<=ord(char['char'])<=0x135 else None)
        if value is None or value==actual:continue
        other=char['bbox'];ox=(other[0]+other[2])/2
        other_offset=(other[1]+other[3])/2-_line_y(line,ox)
        # Finger labels can follow the actual beam slope; compare their
        # offsets from that observed beam rather than a flat page baseline.
        if abs(row_offset-other_offset)>.5*max(box[3]-box[1],other[3]-other[1]):continue
        for index,group in enumerate(groups):
            # A font's text origin can be shifted from its visible digit.
            # Column ownership follows the actual glyph ink bounds.
            if any(min(max(other[0]-x,x-other[2],0) for x in (rhythm['stem'][0],note['origin'][0]))<.35*gap
                   for note,_,rhythm in group):columns.add(index)
    return bool(columns)


def subdivided_beam_tuplets(events,staff,lines,text_chars):
    """Recover a uniquely marked prefix and retain a shorter ordinary tail.

    Each isolated marker must identify exactly one consecutive stem window.
    The windows must tile a prefix without overlap. A residual tail shorter
    than the printed count remains nominal; an entire unmarked group stays
    unresolved rather than extending the marked ratio through missing ink.
    """
    gap=staff['gap'];ratios={3:2,5:4,6:4,7:4,9:8};plans={}
    items=[(n,staff,n.get('rhythm_evidence',{})) for n in events]
    for line in lines:
        groups=_beam_stems(line,items,gap)
        if not groups:continue
        notes=[n for g in groups for n,_,_ in g]
        if any(n.get('duration') is None or n.get('rhythm_evidence',{}).get('tuplet')
               or n.get('confirmed') or any(f in n.get('manual_fields',[]) for f in ('duration','duration_beats','beats'))
               or any(i in n.get('issues',[]) for i in
                      ('grace_or_cue_note_requires_review','small_notated_note_requires_review')) for n in notes):continue
        if len({n.get('measure') for n in notes})!=1 or len({n.get('hand') for n in notes})!=1:continue
        if len({n['duration'] for n in notes})!=1:continue
        directions={r.get('stem_direction') for g in groups for _,_,r in g}
        if len(directions)!=1:continue
        direction=next(iter(directions));lo,hi=sorted((line[0],line[2]))
        for actual,normal in ratios.items():
            if len(groups)<=actual:continue
            markers=[]
            for c in text_chars:
                if c.get('font')=='Aloisen' or c.get('char')!=str(actual):continue
                if not _isolated_marker(c,text_chars):continue
                if _marker_in_fingering_row(c,text_chars,groups,gap,line):continue
                box=c.get('bbox');cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
                if not lo-.5*gap<=cx<=hi+.5*gap:continue
                by=_line_y(line,cx)
                if not .15*gap<abs(cy-by)<2.5*gap:continue
                if direction=='up' and cy>=by or direction=='down' and cy<=by:continue
                markers.append(c)
            if not markers:continue
            windows=[groups[i:i+actual] for i in range(len(groups)-actual+1)]
            assigned=[]
            for marker in markers:
                center=(marker['bbox'][0]+marker['bbox'][2])/2
                choices=[(i,part) for i,part in enumerate(windows)
                         if abs(center-(part[0][0][2]['stem'][0]+part[-1][0][2]['stem'][0])/2)<=1.1*gap]
                if len(choices)!=1:break
                index,part=choices[0];assigned.append((index,part,marker))
            if len(assigned)!=len(markers):continue
            assigned.sort(key=lambda item:item[0])
            # Exact successive starts prove disjoint coverage from the beam's
            # first stem. A full unmarked residual group is still ambiguous.
            if [i for i,_,_ in assigned]!=list(range(0,actual*len(assigned),actual)):continue
            if not 0<=len(groups)-actual*len(assigned)<actual:continue
            for _,part,marker in assigned:
                group_notes=[n for g in part for n,_,_ in g]
                key=tuple(n['id'] for n in group_notes)
                plans.setdefault(key,[]).append((group_notes,actual,normal,marker))
    for choices in plans.values():
        signatures={(actual,normal,tuple(marker['bbox'])) for _,actual,normal,marker in choices}
        if len(signatures)!=1:continue
        notes,actual,normal,marker=choices[0]
        own={n['id'] for n in notes}
        if any(set(other_key)!=own and own.intersection(other_key) for other_key in plans):continue
        if any(n['rhythm_evidence'].get('tuplet') for n in notes):continue
        for note in notes:
            nominal=note['duration'];note['duration']=note['beats']=nominal*normal/actual
            note['rhythm_evidence']={**note['rhythm_evidence'],'tuplet':{
                'actual':actual,'normal':normal,'marker_bbox':[round(v,3) for v in marker['bbox']],
                'nominal_duration_beats':nominal,'method':'unique_marked_beam_prefix_with_nominal_tail'}}


def digit_overlaps_attached_beam(digit,events,gap,lines):
    """A numeral-shaped source object inside a stem/beam is not a safe label.

    Geometry proves conflicting music ink, not the absence of a real digit.
    The caller should retain an explicit source warning and manual values.
    """
    box=digit['bbox']
    for event in events:
        rhythm=event.get('rhythm_evidence',{});stem=rhythm.get('stem')
        if not stem or rhythm.get('beams',0)<2:continue
        if not box[0]-.1*gap<=stem[0]<=box[2]+.1*gap:continue
        if not stem[1]-.1*gap<=median((box[1],box[3]))<=stem[2]+.1*gap:continue
        attached=[]
        for line in lines:
            x1,y1,x2,y2,width=line
            if not .3*gap<=width<=.9*gap or abs(x2-x1)<.7*gap:continue
            lo,hi=sorted((x1,x2));tol=width/2+.1*gap
            if not lo-tol<=stem[0]<=hi+tol:continue
            sy=_line_y(line,stem[0])
            tip=stem[1] if rhythm.get('stem_direction')=='up' else stem[2]
            if abs(sy-tip)>gap:continue
            overlap_lo=max(box[0],lo);overlap_hi=min(box[2],hi)
            if overlap_hi<=overlap_lo:continue
            ys=[_line_y(line,x) for x in (overlap_lo,overlap_hi)]
            if max(box[1],min(ys)-width/2)<min(box[3],max(ys)+width/2):attached.append(line)
        # A single primary beam can legitimately collide with poorly placed
        # fingering in existing engravings. Require the characteristic paired
        # ink of a short secondary hook and its long primary beam.
        short=[l for l in attached if .7*gap<abs(l[2]-l[0])<2.5*gap]
        long=[l for l in attached if abs(l[2]-l[0])>3*gap]
        if any(abs((s[3]-s[1])/(s[2]-s[0])-(l[3]-l[1])/(l[2]-l[0]))<.15
               and .3*gap<abs(_line_y(s,stem[0])-_line_y(l,stem[0]))<gap for s in short for l in long):return True
    return False
