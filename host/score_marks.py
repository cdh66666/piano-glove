"""Read printed performance marks independently of their chosen realization.

The character tables describe music fonts/Unicode, never a score or a page.
Associations use staff-relative distances and unique musical anchors. Source
note values are retained; ambiguous grace performance remains explicitly so.
"""
from __future__ import annotations
from collections import defaultdict
from score_compound import annotate_combinations
import math,re

# Visually verified from original CID glyphs in bundled development fonts.
ALOISEN_MARKS={
    '\u01a0':'trill','\u01a3':'mordent_upper','\u01a4':'mordent_lower',
    '\u01a6':'turn','\u01ac':'arpeggio','\u01b2':'fermata','\u01b3':'fermata',
    '\u01c0':'accent','\u01c1':'accent_staccato','\u01c7':'staccato',
    '\u01c8':'tenuto','\u01d0':'pedal_down',
}
# W3C SMuFL common-ornaments/articulation/holds/keyboard tables and Unicode.
STANDARD_MARKS={
    '\ue566':'trill','\U0001d196':'trill',
    '\ue567':'turn','\U0001d197':'turn','\ue568':'inverted_turn','\U0001d198':'inverted_turn',
    '\ue56c':'mordent_upper','\ue56d':'mordent_lower',
    '\ue4a0':'accent','\ue4a1':'accent','\U0001d17b':'accent',
    '\ue4a2':'staccato','\ue4a3':'staccato','\U0001d17c':'staccato',
    '\ue4a4':'tenuto','\ue4a5':'tenuto','\U0001d17d':'tenuto',
    '\ue4a6':'staccatissimo','\ue4a7':'staccatissimo','\ue4a8':'staccatissimo',
    '\ue4a9':'staccatissimo','\U0001d17e':'staccatissimo',
    '\ue4ac':'accent','\ue4ad':'accent','\U0001d17f':'accent',
    '\ue4ae':'accent_staccato','\ue4af':'accent_staccato','\U0001d180':'accent_staccato',
    '\ue4b0':'accent_staccato','\ue4b1':'accent_staccato','\U0001d181':'accent_staccato',
    '\ue4b2':'tenuto_staccato','\ue4b3':'tenuto_staccato','\U0001d182':'tenuto_staccato',
    '\ue650':'pedal_down','\U0001d1ae':'pedal_down','\ue655':'pedal_up','\U0001d1af':'pedal_up',
    '\ue656':'pedal_half','\U0001d1b0':'pedal_half',
    '\U0001d1b1':'glissando','\U0001d1b2':'glissando',
    '\U0001d167':'tremolo_single','\U0001d168':'tremolo_single','\U0001d169':'tremolo_single',
}
for _code in range(0xE4C0,0xE4CE):STANDARD_MARKS[chr(_code)]='fermata'
STANDARD_MARKS.update({'\U0001d110':'fermata','\U0001d111':'fermata'})
ACCIDENTAL_MARKS={'\u0121':1,'\u0122':-1,'\u0123':0,'\u0124':2,'\u0125':-2,
                    '\u266f':1,'\u266d':-1,'\u266e':0,'\ue260':-1,'\ue261':0,'\ue262':1}
ORNAMENTS={'trill','mordent_upper','mordent_lower','turn','inverted_turn'}
TEXT_MARKS=((r'(?<![A-Za-z])tr\.?\b','trill'),
 (r'(?<![A-Za-z])(?:inv\.?\s*turn|inverted\s+turn)\b','inverted_turn'),
 (r'(?<![A-Za-z])turn\b','turn'),(r'(?<![A-Za-z])(?:upper\s+mord(?:ent)?|mord\.?)(?![A-Za-z])','mordent_upper'),
 (r'(?<![A-Za-z])lower\s+mord(?:ent)?\b','mordent_lower'),
 (r'(?<![A-Za-z])gliss\.?\b','glissando'),
 (r'(?<![A-Za-z])staccatissimo\b','staccatissimo'),(r'(?<![A-Za-z])stacc(?:ato)?\.?(?![A-Za-z])','staccato'),
 (r'(?<![A-Za-z])ten(?:uto)?\.?(?![A-Za-z])','tenuto'),
 (r'(?<![A-Za-z])fermata\b','fermata'),(r'(?<![A-Za-z])Ped\.?\b','pedal_down'),
 (r'(?<![A-Za-z])appogg(?:iatura)?\.?(?![A-Za-z])','grace_long'),
 (r'(?<![A-Za-z])acciaccatura\b','grace_short'))


def _finite(v):return type(v) in (int,float) and math.isfinite(v)
def _box(c):return c.get('bbox') or [c['x'],c['y']-c.get('size',1),c['x']+c.get('size',1),c['y']]
def _center(c):
    b=_box(c);return ((b[0]+b[2])/2,(b[1]+b[3])/2)
def _mark_center(c):
    x,y=_center(c)
    return (c['x']+.5*c.get('size',10),y) if c.get('text_mark') and c.get('kind')!='glissando' else (x,y)
def _gap(staff):return float(staff.get('gap') or (staff['bbox'][3]-staff['bbox'][1])/4)
def _nx(note):return note.get('origin',[0,0])[0]
def _ny(note):return note.get('origin',[0,0])[1]
def _source(c,method='printed_music_glyph'):
    value=dict(method=method,font=c.get('font'),char=c.get('char'),bbox=[round(float(v),3) for v in _box(c)])
    if c.get('glyph_bboxes'):
        value.update(glyph_bboxes=[[round(float(v),3) for v in box] for box in c['glyph_bboxes']],component_count=len(c['glyph_bboxes']))
    if c.get('composite_notation'):
        value.update(composite_notation=c['composite_notation'],components=c['components'])
    return value


def _append(note,kind,*,source=None,group=None,position='on',options=None):
    marks=note.setdefault('performance_marks',[])
    source=dict(source or {'method':'verified_written_structure'})
    source.setdefault('page',note.get('page'));source.setdefault('system',note.get('system'));source.setdefault('staff',note.get('staff'))
    group=group or str(note['id'])+':'+kind
    if any(m['kind']==kind and m.get('group_id')==group for m in marks):return
    if kind=='arpeggio':
        old=next((m for m in marks if m['kind']==kind),None)
        if old is not None:
            if source and source.get('method')!='printed_arpeggio_glyph':
                old.update(group_id=group,position=position,source=source,options=options or {})
            return
    marks.append(dict(kind=kind,group_id=group,position=position,source=source,options=options or {}))


def _span(project,kind,staff,members,source,options=None,group=None):
    if not members:return None
    spans=project.setdefault('performance_spans',[])
    group=group or str(members[0]['id'])+':'+kind
    if any(s['id']==group for s in spans):return group
    source=dict(source);source.setdefault('page',members[0].get('page'));source.setdefault('system',members[0].get('system'));source.setdefault('staff',staff['id'])
    spans.append(dict(id=group,kind=kind,page=members[0].get('page'),system=members[0].get('system'),
        staff=staff['id'],source=source,source_note_ids=[n['id'] for n in members],
        start_note_id=members[0]['id'],end_note_id=members[-1]['id'],options=options or {}))
    for n in members:_append(n,kind,source=source,group=group,position='span',options=options)
    return group


def _groups(notes,gap):
    out=[]
    for n in sorted(notes,key=lambda n:(_nx(n),_ny(n))):
        stem=n.get('rhythm_evidence',{}).get('stem')
        def displaced_whole(other):
            a=n.get('rhythm_evidence',{});b=other.get('rhythm_evidence',{})
            left=n.get('glyph_bbox');right=other.get('glyph_bbox')
            return (a.get('head')==b.get('head')=='whole' and not stem and not b.get('stem')
                and .35*gap<abs(_ny(n)-_ny(other))<.65*gap and .9*gap<abs(_nx(n)-_nx(other))<1.8*gap
                and left and right and max(left[0],right[0])<=min(left[2],right[2])+.15*gap)
        group=next((g for g in out if g[0].get('measure')==n.get('measure') and
                    (abs(_nx(n)-_nx(g[0]))<.35*gap or stem and any(other.get('rhythm_evidence',{}).get('stem')==stem for other in g)
                     or any(displaced_whole(other) for other in g))),None)
        if group is None:out.append([n])
        else:group.append(n)
    return out


def _text_symbols(chars):
    ordinary=[c for c in chars if c.get('font')!='Aloisen' and c.get('char','').strip()]
    rows=[]
    for c in sorted(ordinary,key=lambda c:(c['y'],c['x'])):
        row=next((r for r in rows if abs(r[0]['y']-c['y'])<.3*min(r[0].get('size',10),c.get('size',10))),None)
        if row is None:rows.append([c])
        else:row.append(c)
    result=[]
    for row in rows:
        row.sort(key=lambda c:c['x']);runs=[]
        for c in row:
            if runs and c['x']-_box(runs[-1][-1])[2]<1.3*max(c.get('size',10),runs[-1][-1].get('size',10)):runs[-1].append(c)
            else:runs.append([c])
        for run in runs:
            # Insert spaces when physical text spacing separates words.
            text='';owners=[]
            for i,c in enumerate(run):
                if i and c['x']-_box(run[i-1])[2]>.3*max(c.get('size',10),run[i-1].get('size',10)):
                    text+=' ';owners.append(c)
                value=c.get('char','');text+=value;owners.extend([c]*len(value))
            consumed=set()
            for pattern,kind in TEXT_MARKS:
                for match in re.finditer(pattern,text,re.I):
                    ids=set(range(match.start(),match.end()))
                    if ids&consumed:continue
                    subset=owners[match.start():match.end()]
                    if not subset:continue
                    consumed.update(ids);b=[min(_box(c)[0] for c in subset),min(_box(c)[1] for c in subset),max(_box(c)[2] for c in subset),max(_box(c)[3] for c in subset)]
                    result.append(dict(char=match[0],kind=kind,font='text',x=b[0],y=run[0]['y'],bbox=b,size=max(c.get('size',10) for c in subset),text_mark=True))
    return result


def _normalize_composite_trills(symbols):
    """A printed 'tr' over the same short wave is one trill, with both inks.

    This grammar applies only to one-to-one same-font overlapping glyphs.
    Separate upper/lower mordents, text words and ambiguous multi-pairs retain
    their identities, allowing the compiler to report conflicting ornaments.
    """
    pairs=[]
    for ti,trill in enumerate(symbols):
        if trill.get('kind')!='trill' or trill.get('text_mark'):continue
        a=_box(trill);area_a=max(0,a[2]-a[0])*max(0,a[3]-a[1])
        if not area_a:continue
        for wi,wave in enumerate(symbols):
            if (wave.get('kind')!='mordent_upper' or wave.get('text_mark')
                    or not trill.get('font') or trill.get('font')!=wave.get('font')):continue
            b=_box(wave);area_b=max(0,b[2]-b[0])*max(0,b[3]-b[1])
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            if area_b and overlap>.5*area_a and overlap>.5*area_b:pairs.append((ti,wi))
    accepted=[(ti,wi) for ti,wi in pairs if sum(t==ti for t,w in pairs)==1 and sum(w==wi for t,w in pairs)==1]
    consumed={wi for ti,wi in accepted};by_trill=dict(accepted);result=[]
    for index,symbol in enumerate(symbols):
        if index in consumed:continue
        if index not in by_trill:result.append(symbol);continue
        wave=symbols[by_trill[index]];boxes=[_box(symbol),_box(wave)]
        components=[dict(kind=s['kind'],font=s.get('font'),char=s.get('char'),bbox=list(_box(s))) for s in (symbol,wave)]
        result.append(dict(symbol,bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
                           glyph_bboxes=[list(b) for b in boxes],composite_notation='overlapping_trill_and_short_wave',components=components))
    return result


def _glyph_symbols(chars):
    # PDFium exposes some non-BMP ToUnicode values as two UTF-16 character
    # records at the same glyph origin. Decode that printed scalar before
    # consulting Unicode music-symbol names; never join unrelated text.
    normalized=[];index=0
    while index<len(chars):
        c=chars[index];value=c.get('char','');next_c=chars[index+1] if index+1<len(chars) else None
        if (len(value)==1 and 0xD800<=ord(value)<=0xDBFF and next_c is not None
            and len(next_c.get('char',''))==1 and 0xDC00<=ord(next_c['char'])<=0xDFFF
            and c.get('font')==next_c.get('font') and abs(c['x']-next_c['x'])<.01 and abs(c['y']-next_c['y'])<.01
            and all(abs(a-b)<.01 for a,b in zip(_box(c),_box(next_c)))):
            scalar=0x10000+((ord(value)-0xD800)<<10)+(ord(next_c['char'])-0xDC00)
            normalized.append(dict(c,char=chr(scalar)));index+=2
        else:normalized.append(c);index+=1
    chars=normalized
    result=[]
    for c in chars:
        value=c.get('char','');kind=ALOISEN_MARKS.get(value) if c.get('font')=='Aloisen' else STANDARD_MARKS.get(value)
        if not kind:continue
        if len(value)==1 and 0xE000<=ord(value)<=0xF8FF and not any(name in c.get('font','').lower() for name in ('bravura','petaluma','leland','sebastian','norfolk','november2','smufl')):continue
        out=dict(c,kind=kind)
        if kind=='tremolo_single':out['stroke_count']=ord(value)-0x1D167+1
        result.append(out)
    result.extend(_text_symbols(chars))
    return _normalize_composite_trills(result)


def _staff_choices(symbol,staves,by_staff,kind):
    x,y=_mark_center(symbol);choices=[]
    for staff in staves:
        notes=by_staff.get(staff['id'],[])
        if not notes:continue
        gap=_gap(staff);left=staff.get('left',staff.get('bbox',[0])[0]);right=staff.get('right',staff.get('bbox',[0,0,0])[2]);top=staff.get('top',staff.get('bbox',[0,0])[1]);bottom=staff.get('bottom',staff.get('bbox',[0,0,0,0])[3])
        if not left-gap<=x<=right+gap:continue
        if kind.startswith('pedal'):
            if not bottom+gap<y<bottom+14*gap:continue
            cost=(y-bottom)/gap
        else:
            if not top-10*gap<y<bottom+7*gap:continue
            if kind=='fermata' and _fermata_side(symbol):
                anchors=_anchor(symbol,staff,notes,kind)
                if not anchors:continue
                cost=min(abs(_nx(n)+.6*gap-x)/gap*2+abs(y-_ny(n))/gap*.2 for n in anchors)
                choices.append((cost,staff));continue
            close=min(notes,key=lambda n:abs(_nx(n)+.6*gap-x))
            dx=abs(_nx(close)+.6*gap-x)/gap
            if dx>2.5 and kind not in ('glissando','turn','inverted_turn'):continue
            cost=dx*2+min(abs(y-_ny(close)),abs(y-top),abs(y-bottom))/gap*.2
        choices.append((cost,staff))
    if not choices and kind=='fermata' and _fermata_side(symbol):
        # Retain a detected sign even when its conventional side has no owner.
        # A provisional legacy anchor keeps the source visible and blocked.
        return _staff_choices(dict(symbol,fermata_orientation_unresolved=True),staves,by_staff,kind)
    choices.sort(key=lambda x:x[0]);return choices


def _fermata_side(symbol):
    """Return its printed side of the music: -1 above, +1 below."""
    if symbol.get('fermata_orientation_unresolved'):return 0
    value=symbol.get('char','')
    if symbol.get('font')=='Aloisen':return {'\u01b2':-1,'\u01b3':1}.get(value,0)
    if value in ('\U0001d110','\U0001d111'):return -1 if value=='\U0001d110' else 1
    if len(value)==1 and 0xE4C0<=ord(value)<=0xE4CD:return -1 if ord(value)%2==0 else 1
    return 0


def _anchor(symbol,staff,notes,kind):
    gap=_gap(staff);x,y=_mark_center(symbol)
    if kind in ('arpeggio',):
        groups=[g for g in _groups(notes,gap) if .1*gap<min(_nx(n) for n in g)-x<3.2*gap]
        if not groups:return []
        group=min(groups,key=lambda g:min(_nx(n) for n in g)-x)
        b=_box(symbol)
        if min(abs(_ny(n)-y) for n in group)>6*gap:return []
        return [n for n in group if b[1]-1.5*gap<=_ny(n)<=b[3]+1.5*gap] or group
    choices=[]
    for n in notes:
        dx=abs(_nx(n)+.55*gap-x)/gap;dy=abs(_ny(n)-y)/gap
        if dx>1.7 or dy>8:continue
        if kind=='fermata' and _fermata_side(symbol)*(y-_ny(n))<=.35*gap and _fermata_side(symbol):continue
        if symbol.get('text_mark') and dy>5.5:continue
        if kind in ('staccato','staccatissimo','tenuto','accent','accent_staccato','tenuto_staccato'):
            # This same dot glyph is used for augmentation. A dot at notehead
            # height and to its right must stay a duration dot, not touch.
            if dy<.65:continue
            if kind in ('staccato','accent_staccato','tenuto_staccato') and any(
                .5*gap<x-_nx(other)<3*gap and abs(_ny(other)-y)<.45*gap for other in notes):continue
        if kind in ORNAMENTS and dy<.6:continue
        if kind.startswith('grace') and not (n.get('grace_kind') or 'grace_or_cue_note_requires_review' in n.get('issues',[])):continue
        choices.append((dx*3+dy*.15,n))
    choices.sort(key=lambda v:v[0])
    if not choices and kind in ('turn','inverted_turn'):
        columns=_groups([n for n in notes if not n.get('grace_kind')],gap)
        left=[g for g in columns if max(_nx(n) for n in g)<x];right=[g for g in columns if min(_nx(n) for n in g)>x]
        if left and right:
            a=max(left,key=lambda g:max(_nx(n) for n in g));b=min(right,key=lambda g:min(_nx(n) for n in g))
            if (a[0].get('measure')==b[0].get('measure') and a[0].get('hand')==b[0].get('hand')
                and min(abs(_ny(n)-y) for n in a)<8*gap and min(abs(_ny(n)-y) for n in b)<8*gap):return a
    if not choices:return []
    best=choices[0][1]
    if kind=='fermata':
        # A pause on a stemmed voice or whole-note chord does not also mark a
        # different voice's rest at the same x. Opposed voices stay separate.
        rhythm=best.get('rhythm_evidence') or {};stem=rhythm.get('stem')
        if stem:return [n for n in notes if n.get('measure')==best.get('measure') and n.get('rhythm_evidence',{}).get('stem')==stem]
        if rhythm.get('head'):
            peers=[n for n in notes if n.get('measure')==best.get('measure') and n.get('rhythm_evidence',{}).get('head')==rhythm['head']
                and n.get('duration',n.get('duration_beats'))==best.get('duration',best.get('duration_beats'))]
            column=[best]
            for _ in peers:
                added=[n for n in peers if n not in column and any(abs(_nx(n)-_nx(other))<.35*gap or
                    rhythm['head']=='whole' and .35*gap<abs(_ny(n)-_ny(other))<.65*gap
                    and .9*gap<abs(_nx(n)-_nx(other))<1.8*gap and n.get('glyph_bbox') and other.get('glyph_bbox')
                    and max(n['glyph_bbox'][0],other['glyph_bbox'][0])<=min(n['glyph_bbox'][2],other['glyph_bbox'][2])+.15*gap for other in column)]
                if not added:break
                column.extend(added)
            return column
        return [best]
    # A printed mark over a chord applies to the attack column, not an
    # arbitrary lower chord member. Multiple opposed voices stay separate.
    direction=best.get('rhythm_evidence',{}).get('stem_direction')
    column=[n for n in notes if abs(_nx(n)-_nx(best))<.4*gap and n.get('hand')==best.get('hand')
        and (not direction or n.get('rhythm_evidence',{}).get('stem_direction')==direction)]
    return column or [best]


def _merge_arpeggio_segments(symbols,staves,by_staff):
    """A vertical ink-continuous wave is often several font glyph pieces.

    Keep disjoint waves separate. Font, unique physical-staff ownership,
    horizontal ink overlap and a short vertical ink gap are all required.
    """
    waves=[];others=[]
    for symbol in symbols:
        if symbol.get('kind')!='arpeggio' or symbol.get('text_mark'):others.append(symbol);continue
        choices=_staff_choices(symbol,staves,by_staff,'arpeggio')
        if not choices or len(choices)>1 and abs(choices[1][0]-choices[0][0])<.15:
            others.append(symbol);continue
        value=dict(symbol,owner_staff_id=choices[0][1]['id'],staff_gap=_gap(choices[0][1]),glyph_bboxes=[list(_box(symbol))]);waves.append(value)
    components=[]
    for wave in sorted(waves,key=lambda c:(c['owner_staff_id'],c.get('font',''),_box(c)[1],_center(c)[0])):
        b=_box(wave);gap=wave['staff_gap'];matches=[]
        for component in components:
            if component['owner_staff_id']!=wave['owner_staff_id'] or component.get('font')!=wave.get('font') or component.get('char')!=wave.get('char'):continue
            a=_box(component);overlap=min(a[2],b[2])-max(a[0],b[0]);minimum=min(a[2]-a[0],b[2]-b[0])
            vertical_gap=max(a[1],b[1])-min(a[3],b[3])
            if (abs(_center(component)[0]-_center(wave)[0])<=.25*gap and overlap>=.5*minimum
                and vertical_gap<=.45*gap):matches.append(component)
        if len(matches)!=1:components.append(wave);continue
        component=matches[0];a=_box(component);component['bbox']=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
        component['glyph_bboxes'].extend(wave['glyph_bboxes'])
    return others+components


def _add_legacy_marks(project,staves,notes):
    by_id={n['id']:n for n in notes};staff_map={s['id']:s for s in staves};graces=defaultdict(list)
    for n in notes:
        staff=staff_map.get(n.get('staff'))
        if not staff:continue
        rhythm=n.get('rhythm_evidence',{})
        if rhythm.get('dots'):
            _append(n,'dots',source={'method':'printed_augmentation_dots'},options={'count':rhythm['dots'],'applied_to_duration':True})
        if rhythm.get('tuplet'):
            _append(n,'tuplet',source={'method':rhythm['tuplet'].get('method','printed_tuplet'),'bbox':rhythm['tuplet'].get('marker_bbox')},options={**rhythm['tuplet'],'applied_to_duration':True})
        if n.get('tie_to') or n.get('tie_to_candidate'):
            target=n.get('tie_to') or n.get('tie_to_candidate')
            _append(n,'tie',source={'method':'printed_tie_arc',**n.get('tie_evidence',{})},options={'target_id':target,'reviewed':bool(n.get('tie_reviewed'))})
        if n.get('octave_shift') or n.get('octave_evidence'):
            evidence=n.get('octave_evidence') or {}
            _append(n,'ottava',source={'method':'bounded_octave_line','bbox':evidence.get('marker_bbox')},options={'semitones':n.get('octave_shift'),'applied_to_pitch':n.get('octave_shift') is not None})
        if n.get('tremolo_group'):
            proof=dict(n.get('tremolo_evidence') or {'method':'printed_tremolo'});strokes=proof.get('strokes',[])
            if strokes and all(len(s)>=3 for s in strokes):proof['bbox']=[min(s[0] for s in strokes),min(s[2] for s in strokes)-.2*_gap(staff),max(s[1] for s in strokes),max(s[2] for s in strokes)+.2*_gap(staff)]
            _append(n,'tremolo_alternating',group=n['tremolo_group'],source=proof,
                options={'side':n.get('tremolo_side'),'step_beats':n.get('tremolo_step_beats'),'span_beats':n.get('tremolo_span_beats')})
        if n.get('grace_kind'):
            anchor=n.get('main_anchor_id')
            key=(n.get('staff'),n.get('measure'),n.get('hand'),anchor) if anchor is not None else n.get('grace_group',n['id'])
            graces[key].append(n)
        if 'arpeggio_requires_review' in n.get('issues',[]):
            _append(n,'arpeggio',group=str(n.get('staff'))+':'+str(n.get('measure'))+':arpeggio:'+str(round(_nx(n),2)),
                source={'method':'printed_arpeggio_glyph'},options={'direction':'up'})
        beat=n.get('measure_beat');duration=n.get('duration')
        if _finite(beat) and _finite(duration) and duration>0 and abs(beat-round(beat))>.01 and beat+duration>math.ceil(beat)+.01:
            _append(n,'syncopation',source={'method':'explicit_written_offset_and_duration','bbox':n.get('glyph_bbox') or n.get('bbox')},options={'applied_to_timing':True})
    for original_ident,members in graces.items():
        members.sort(key=lambda n:(_nx(n),_ny(n)))
        staff=staff_map[members[0]['staff']];columns=_groups(members,_gap(staff))
        ident=str(members[0].get('main_anchor_id') or members[0].get('grace_group') or members[0]['id'])+':grace'
        slashed=any(n.get('grace_kind')=='slashed' for n in members)
        for order,column in enumerate(columns):
            for n in column:
                kind='grace_cluster' if len(columns)>1 else 'grace_short' if slashed else 'grace_unspecified'
                _append(n,kind,group=ident,position='before_anchor',source={'method':'verified_small_note_and_principal_anchor','bbox':n.get('glyph_bbox') or n.get('bbox')},
                    options={'anchor_id':n.get('main_anchor_id'),'member_ids':[m['id'] for m in members],'order':order,'slashed':slashed,
                             'semantic_estimated':not slashed,'variants':['grace_long','grace_short'] if not slashed else []})


def _slurs(project,staff,notes,curves):
    gap=_gap(staff);groups=_groups(notes,gap)
    for box in curves:
        x0,y0,x1,y1=box
        if not 2*gap<x1-x0<100*gap or y1-y0>4*gap:continue
        left=[g for g in groups if abs(_nx(g[0])+.6*gap-x0)<1.4*gap and min(abs(_ny(n)-y0) for n in g)<8*gap]
        right=[g for g in groups if abs(_nx(g[0])+.6*gap-x1)<1.4*gap and min(abs(_ny(n)-y1) for n in g)<8*gap]
        if not left or not right:continue
        a=min(left,key=lambda g:abs(_nx(g[0])+.6*gap-x0));b=min(right,key=lambda g:abs(_nx(g[0])+.6*gap-x1))
        if _nx(b[0])<=_nx(a[0])+gap:continue
        if any(n.get('tie_to_candidate') in {t['id'] for t in b} for n in a):continue
        members=[n for n in notes if _nx(a[0])-.3*gap<=_nx(n)<=_nx(b[0])+.3*gap]
        if len(members)<2:continue
        _span(project,'slur',staff,sorted(members,key=lambda n:(_nx(n),_ny(n))),{'method':'bounded_printed_slur_curve','bbox':list(box)})


def _single_tremolos(project,staff,notes,lines):
    gap=_gap(staff)
    for n in notes:
        rhythm=n.get('rhythm_evidence',{});stem=rhythm.get('stem')
        if not stem or rhythm.get('beams') or n.get('grace_kind') or n.get('tremolo_group'):continue
        x,lo,hi=stem;strokes=[]
        for x1,y1,x2,y2,w in lines:
            if abs(x2-x1)<.8*gap or abs(x2-x1)>2.7*gap or not .25*gap<=w<=.95*gap:continue
            if not min(x1,x2)+.1*gap<x<max(x1,x2)-.1*gap:continue
            slope=(y2-y1)/(x2-x1)
            if not .12<abs(slope)<1.8:continue
            y=y1+slope*(x-x1)
            if not lo+.55*gap<y<hi-.55*gap or abs(y-_ny(n))<.7*gap:continue
            # A stroke also meeting another note's shaft is a beam family.
            if any(other is not n and (s:=other.get('rhythm_evidence',{}).get('stem'))
                and min(x1,x2)-.1*gap<=s[0]<=max(x1,x2)+.1*gap
                and min(abs(y1+slope*(s[0]-x1)-s[1]),abs(y1+slope*(s[0]-x1)-s[2]))<.4*gap for other in notes):continue
            strokes.append((y,slope,(x1,y1,x2,y2,w)))
        strokes.sort()
        if len(strokes) not in (1,2,3):continue
        if any(abs(s[1]-strokes[0][1])>.15 for s in strokes) or any(not .35*gap<b[0]-a[0]<1.1*gap for a,b in zip(strokes,strokes[1:])):continue
        boxes=[s[2] for s in strokes]
        _append(n,'tremolo_single',source={'method':'parallel_internal_stem_tremolo_strokes','lines':[list(s[2]) for s in strokes],
            'bbox':[min(min(b[0],b[2]) for b in boxes),min(min(b[1],b[3]) for b in boxes),max(max(b[0],b[2]) for b in boxes),max(max(b[1],b[3]) for b in boxes)]},options={'strokes':len(strokes),'step_beats':1/(2**len(strokes))})


def _after_graces(staff,notes):
    gap=_gap(staff)
    for measure in sorted({n.get('measure') for n in notes}):
        ordered=sorted((n for n in notes if n.get('measure')==measure),key=lambda n:(_nx(n),_ny(n)))
        small=[n for n in ordered if not n.get('grace_kind') and 'grace_or_cue_note_requires_review' in n.get('issues',[])]
        for n in small:
            before=[a for a in ordered if _nx(a)<_nx(n)-.5*gap and a not in small and not a.get('grace_kind')]
            after=[a for a in ordered if _nx(a)>_nx(n)+.5*gap and a not in small and not a.get('grace_kind')]
            if not before or after:continue
            anchor=max(before,key=_nx)
            if _nx(n)-_nx(anchor)>7*gap:continue
            members=[g for g in small if _nx(g)>_nx(anchor) and _nx(g)-_nx(anchor)<7*gap]
            group=str(anchor['id'])+':after-grace'
            for i,g in enumerate(members):_append(g,'grace_after',group=group,position='after_anchor',source={'method':'slashed_small_suffix_after_last_principal','bbox':g.get('glyph_bbox') or g.get('bbox')},options={'anchor_id':anchor['id'],'member_ids':[m['id'] for m in members],'order':i,'semantic_estimated':True})


def _broken_chords(project,staff,notes):
    gap=_gap(staff)
    for measure in sorted({n.get('measure') for n in notes}):
        groups=_groups([n for n in notes if n.get('measure')==measure and not n.get('grace_kind')],gap)
        run=[]
        def finish():
            if len(run)<3:return
            pitches=[n.get('midi') for n in run]
            if any(not _finite(p) for p in pitches):return
            steps=[b-a for a,b in zip(pitches,pitches[1:])]
            if not (all(2<=s<=7 for s in steps) or all(-7<=s<=-2 for s in steps)):return
            if abs(pitches[-1]-pitches[0])<7 or len({p%12 for p in pitches})>4:return
            _span(project,'broken_chord',staff,list(run),{'method':'explicit_monotone_written_chord_tones'},options={'written_attacks':True,'classification_estimated':True})
        for group in groups:
            if len(group)==1 and _finite(group[0].get('duration')) and 0<group[0]['duration']<=1:
                run.append(group[0])
            else:finish();run=[]
        finish()


def _pair_cross_staff_fermatas(project,page):
    """Unify a uniquely shared printed pause without guessing an onset.

    Original mark rectangles remain on their original heads/rests. Pairing
    requires the same page/system/bar, one staff on each side, one finite
    original duration, actual horizontal ink overlap and no known end conflict.
    """
    groups=defaultdict(list)
    events=[n for n in project.get('notes',[])+project.get('rests',[]) if n.get('page')==page and not n.get('excluded')]
    for event in events:
        for mark in event.get('performance_marks',[]):
            if mark.get('kind')=='fermata':groups[mark.get('group_id')].append((event,mark))
    proofs={}
    for gid,items in groups.items():
        staffs={e.get('staff') for e,m in items};contexts={(e.get('page'),e.get('system'),e.get('measure')) for e,m in items}
        durations={e.get('duration',e.get('duration_beats')) for e,m in items}
        boxes={tuple(m['source']['bbox']) for e,m in items if m.get('source',{}).get('bbox')}
        ends={round(e['measure_beat']+e.get('duration',e.get('duration_beats')),6) for e,m in items
              if _finite(e.get('measure_beat')) and _finite(e.get('duration',e.get('duration_beats')))}
        if (not gid or len(staffs)!=1 or None in staffs or len(contexts)!=1 or len(durations)!=1
                or not all(_finite(d) and d>0 for d in durations) or len(boxes)!=1 or len(ends)>1):continue
        proofs[gid]=dict(staff=next(iter(staffs)),context=next(iter(contexts)),duration=next(iter(durations)),box=next(iter(boxes)),end=next(iter(ends)) if ends else None)
    edges=defaultdict(list);ids=sorted(proofs)
    for i,a in enumerate(ids):
        p=proofs[a]
        for b in ids[i+1:]:
            q=proofs[b]
            if (p['staff']==q['staff'] or p['context']!=q['context'] or abs(p['duration']-q['duration'])>1e-6
                    or min(p['box'][2],q['box'][2])<=max(p['box'][0],q['box'][0])
                    or p['end'] is not None and q['end'] is not None and abs(p['end']-q['end'])>1e-5):continue
            edges[a].append(b);edges[b].append(a)
    pairs=[(a,others[0]) for a,others in edges.items() if len(others)==1 and len(edges[others[0]])==1 and a<others[0]]
    for a,b in pairs:
        ordered=sorted((a,b),key=lambda gid:(not any(e.get('hand')=='right' for e,m in groups[gid]),proofs[gid]['end'] is None,gid))
        canonical,alias=ordered;items=groups[canonical]+groups[alias]
        sources=[]
        for e,m in items:
            source=m.get('source',{})
            if source not in sources:sources.append(dict(source))
        evidence=dict(method='unique_cross_staff_fermata_ink_and_equal_written_duration',original_group_ids=ordered,
                      paired_staff_ids=[proofs[g]['staff'] for g in ordered],sources=sources)
        for event,mark in items:
            mark['group_id']=canonical;mark.setdefault('options',{})['cross_staff_pause_pairing']=dict(evidence)
        spans=project.get('performance_spans',[]);matching=[s for s in spans if s.get('kind')=='fermata' and s.get('id') in (a,b)]
        keep=next((s for s in matching if s.get('id')==canonical),matching[0] if matching else None)
        if keep is not None:
            keep['id']=canonical;keep['sources']=sources;keep.setdefault('options',{})['cross_staff_pause_pairing']=dict(evidence)
            keep['options']['paired_anchor_note_ids']=[e['id'] for e,m in items if e in project.get('notes',[])]
            keep['options']['paired_anchor_rest_ids']=[e['id'] for e,m in items if e in project.get('rests',[])]
            keep['source_note_ids']=list(dict.fromkeys(nid for s in matching for nid in s.get('source_note_ids',[])))
            project['performance_spans']=[s for s in spans if s not in matching or s is keep]
    return len(pairs)


def _sustained_fermata_measure(project,items,events):
    """An isolated full-bar printed voice can share the other staff's ending.

    This proves a relation between pause signs, never a LH onset or duration.
    Require the recognizer's explicit common bar boundaries and a complete
    physical voice beginning at the first column (including an opposed unison).
    """
    first=items[0][0];context=tuple(first.get(k) for k in ('page','system','measure'))
    if any(e.get('hand')!='left' or e.get('staff')!=first.get('staff') or
           tuple(e.get(k) for k in ('page','system','measure'))!=context for e,_ in items):return None
    if any(_finite(e.get('beat')) or _finite(e.get('measure_beat')) or
           set(e.get('manual_fields') or [])&{'beat','measure_beat','duration_beats'} for e,_ in items):return None
    staff=next((s for s in project.get('staves',[]) if s.get('id')==first.get('staff')),{})
    measure=next((m for m in staff.get('measures',[]) if m.get('measure')==first.get('measure')),{})
    extent=measure.get('metric_extent_evidence') or {};meter=extent.get('quarter_beats');bounds=extent.get('boundary_x') or []
    value=first.get('duration',first.get('duration_beats'));gap=_gap(staff) if staff else None
    if (extent.get('method')!='explicit_meter_shared_ordinary_barlines' or not _finite(meter) or meter<=0
        or len(bounds)!=2 or not all(_finite(x) for x in bounds) or not _finite(value) or abs(value-meter)>1e-6
        or not gap or any(e.get('duration',e.get('duration_beats'))!=value for e,_ in items)):return None
    members=[e for e in events if e.get('staff')==first.get('staff') and tuple(e.get(k) for k in ('page','system','measure'))==context]
    notes=[e for e in members if (e.get('rhythm_evidence') or {}).get('head') and not e.get('grace_kind')]
    rhythm=first.get('rhythm_evidence') or {};direction=rhythm.get('stem_direction');stem=rhythm.get('stem')
    voice=[e for e in notes if (e.get('rhythm_evidence') or {}).get('stem_direction')==direction] if stem and direction in ('up','down') else [e for e in notes if (e.get('rhythm_evidence') or {}).get('head')=='whole'] if rhythm.get('head')=='whole' else []
    if not voice or {e['id'] for e in voice}!={e['id'] for e,_ in items}:return None
    if stem and any((e.get('rhythm_evidence') or {}).get('stem')!=stem for e in voice):return None
    first_x=min(_nx(e) for e in members)
    for event,_ in items:
        if _nx(event)-first_x<=.35*gap:continue
        # Opposed unison heads are horizontally displaced, but their real ink,
        # pitch and opposite shafts still identify the same first attack.
        a=event.get('glyph_bbox');opposed=[e for e in notes if _nx(e)-first_x<=.35*gap and
            e.get('midi')==event.get('midi') and _finite(event.get('midi')) and abs(_ny(e)-_ny(event))<.15*gap and
            (e.get('rhythm_evidence') or {}).get('stem_direction') in ({'down'} if direction=='up' else {'up'}) and e.get('glyph_bbox') and a and
            max(a[0],e['glyph_bbox'][0])<=min(a[2],e['glyph_bbox'][2])+.15*gap]
        if not opposed:return None
    return dict(context=context,boundary_x=list(bounds),meter_beats=meter,staff_gap=gap,source_note_ids=[e['id'] for e,_ in items])


def _pair_sustained_measure_fermatas(project,page):
    events=[e for e in project.get('notes',[])+project.get('rests',[]) if e.get('page')==page and not e.get('excluded')]
    groups=defaultdict(list)
    for event in events:
        for mark in event.get('performance_marks',[]):
            if mark.get('kind')=='fermata':groups[mark.get('group_id')].append((event,mark))
    for alias,items in list(groups.items()):
        proof=_sustained_fermata_measure(project,items,events)
        if proof is None:continue
        candidates=[]
        for gid,peers in groups.items():
            right=[e for e,_ in peers if e.get('hand')=='right' and tuple(e.get(k) for k in ('page','system','measure'))==proof['context']]
            if not right or gid==alias or len({e.get('staff') for e in right})!=1:continue
            staff=next((s for s in project.get('staves',[]) if s.get('id')==right[0].get('staff')),{})
            measure=next((m for m in staff.get('measures',[]) if m.get('measure')==right[0].get('measure')),{})
            extent=measure.get('metric_extent_evidence') or {};bounds=extent.get('boundary_x') or []
            if (extent.get('method')!='explicit_meter_shared_ordinary_barlines' or len(bounds)!=2
                or extent.get('quarter_beats')!=proof['meter_beats'] or any(abs(a-b)>.2*proof['staff_gap'] for a,b in zip(bounds,proof['boundary_x']))):continue
            printed=[e for e in events if e.get('staff')==right[0].get('staff') and tuple(e.get(k) for k in ('page','system','measure'))==proof['context'] and not e.get('grace_kind')]
            if printed and all(_nx(e)>=max(_nx(n) for n in printed)-.35*proof['staff_gap'] for e in right):candidates.append((gid,right))
        if len(candidates)!=1:continue
        canonical,right=candidates[0]
        evidence=dict(method='unique_sustained_measure_voice_and_terminal_fermata',original_group_ids=[canonical,alias],
            boundary_x=proof['boundary_x'],meter_beats=proof['meter_beats'],sustained_source_ids=proof['source_note_ids'],terminal_source_ids=[e['id'] for e in right])
        for event,mark in items+groups[canonical]:
            mark['group_id']=canonical;mark.setdefault('options',{})['cross_staff_pause_pairing']=dict(evidence)
        spans=project.get('performance_spans',[]);matching=[s for s in spans if s.get('kind')=='fermata' and s.get('id') in (canonical,alias)]
        keep=next((s for s in matching if s.get('id')==canonical),None)
        if keep is not None:
            keep.setdefault('options',{})['cross_staff_pause_pairing']=dict(evidence)
            keep['source_note_ids']=list(dict.fromkeys(nid for s in matching for nid in s.get('source_note_ids',[])))
            keep['sources']=[dict(m.get('source') or {}) for _,m in items+groups[canonical]]
            project['performance_spans']=[s for s in spans if s not in matching or s is keep]


def annotate_performance_page(project,page,staves,chars,text_chars,lines,curves):
    """Attach actual detected marks; never create performance note guesses here."""
    records={s['id']:s for s in project.get('staves',[]) if s.get('page')==page}
    staves=[{**s,'key_signature':records.get(s['id'],{}).get('key_signature',s.get('key_signature',{}))} for s in staves]
    notes=[n for n in project.get('notes',[]) if n.get('page')==page and not n.get('excluded')]
    by_staff=defaultdict(list)
    for n in notes:by_staff[n.get('staff')].append(n)
    by_staff_events=defaultdict(list)
    for n in notes+[r for r in project.get('rests',[]) if r.get('page')==page and not r.get('excluded')]:by_staff_events[n.get('staff')].append(n)
    _add_legacy_marks(project,staves,notes)
    symbols=_merge_arpeggio_segments(_glyph_symbols(text_chars),staves,by_staff)
    pedals=defaultdict(list)
    for symbol in sorted(symbols,key=lambda c:(c['x'],c['y'])):
        kind=symbol['kind'];targets=by_staff_events if kind=='fermata' or kind.startswith('pedal') else by_staff
        owner=next((s for s in staves if s['id']==symbol.get('owner_staff_id')),None)
        choices=[(0,owner)] if owner is not None else _staff_choices(symbol,staves,targets,kind)
        if not choices:continue
        if len(choices)>1 and abs(choices[1][0]-choices[0][0])<.15:continue
        staff=choices[0][1];members=targets[staff['id']];gap=_gap(staff)
        source=_source(symbol,'printed_text_notation' if symbol.get('text_mark') else 'printed_music_glyph')
        source.update(page=page,system=staff.get('system'),staff=staff['id'])
        if kind.startswith('pedal'):
            pedals[staff['id']].append((symbol,kind,source));continue
        if kind=='glissando':
            x,y=_center(symbol);groups=_groups(members,gap)
            left=[g for g in groups if _nx(g[0])<=x];right=[g for g in groups if _nx(g[0])>x]
            if not left or not right:continue
            a=max(left,key=lambda g:_nx(g[0]));b=min(right,key=lambda g:_nx(g[0]))
            # Explicit gliss text/glyph plus a thin connecting diagonal avoids
            # reclassifying an ordinary beam or a decorative title word.
            connecting=[line for line in lines if abs(line[2]-line[0])>2*gap and line[4]<.3*gap
                and abs(line[3]-line[1])>.2*gap
                and abs(min(line[0],line[2])-(_nx(a[0])+gap))<2*gap
                and abs(max(line[0],line[2])-_nx(b[0]))<2*gap]
            if not connecting and symbol.get('text_mark'):continue
            _span(project,'glissando',staff,a+b,source,options={'start_id':a[0]['id'],'target_id':b[0]['id'],'direction':'up' if (b[0].get('midi',0) or 0)>(a[0].get('midi',0) or 0) else 'down'})
            continue
        anchored=_anchor(symbol,staff,members,kind);unresolved_fermata=False
        if not anchored and kind=='fermata' and _fermata_side(symbol):
            anchored=_anchor(dict(symbol,fermata_orientation_unresolved=True),staff,members,kind);unresolved_fermata=bool(anchored)
        if not anchored:continue
        if kind=='fermata' and _fermata_side(symbol):
            source['attachment']=dict(method='unresolved_printed_fermata_side' if unresolved_fermata else 'printed_fermata_side_and_voice',side='above' if _fermata_side(symbol)<0 else 'below',anchor_ids=[n['id'] for n in anchored])
        options={'source_anchor_unresolved':True} if unresolved_fermata else {}
        if kind in ('grace_long','grace_short'):
            groups={m['group_id'] for n in anchored for m in n.get('performance_marks',[]) if m['kind'].startswith('grace')}
            updated=False
            for n in members:
                for m in n.get('performance_marks',[]):
                    if m.get('group_id') not in groups or not m['kind'].startswith('grace'):continue
                    m['kind']=kind;m['source']=dict(source);m['options'].update(semantic_estimated=False,variants=[]);updated=True
            if updated:continue
        if kind in ORNAMENTS:
            sx,sy=_center(symbol)
            upper=[c for c in text_chars if c.get('char') in ACCIDENTAL_MARKS and abs(_center(c)[0]-sx)<1.3*gap and 0<sy-_center(c)[1]<3*gap]
            if kind in ('turn','inverted_turn'):
                lower=[c for c in text_chars if c.get('char') in ACCIDENTAL_MARKS and abs(_center(c)[0]-sx)<1.3*gap and .2*gap<_center(c)[1]-sy<3*gap]
                if len(upper)==1:options['upper_auxiliary_accidental']=ACCIDENTAL_MARKS[upper[0]['char']]
                if len(lower)==1:options['lower_auxiliary_accidental']=ACCIDENTAL_MARKS[lower[0]['char']]
                if len(upper)>1 or len(lower)>1:options['auxiliary_accidental_ambiguous']=True
            else:
                if len(upper)==1:options['auxiliary_accidental']=ACCIDENTAL_MARKS[upper[0]['char']]
                if len(upper)>1:options['auxiliary_accidental_ambiguous']=True
            if kind in ('turn','inverted_turn') and sx>_nx(anchored[0])+1.3*gap:
                options['delayed']=True
                following=[n for n in members if _nx(n)>sx and n.get('measure')==anchored[0].get('measure') and n.get('hand')==anchored[0].get('hand')]
                if following:options['next_anchor_id']=min(following,key=_nx)['id']
        if kind=='arpeggio':
            arrows=[c for c in text_chars if c.get('char') in ('↓','↑') and abs(_center(c)[0]-_center(symbol)[0])<gap and abs(_center(c)[1]-_center(symbol)[1])<6*gap]
            options['direction']='down' if any(c['char']=='↓' for c in arrows) else 'up'
        if kind=='tremolo_single':options.update(strokes=symbol.get('stroke_count',1),step_beats=1/(2**symbol.get('stroke_count',1)))
        group=str(anchored[0]['id'])+':'+kind
        if kind=='fermata':
            event=anchored[0];start=event.get('measure_beat');duration=event.get('duration',event.get('duration_beats'))
            position=round(start+duration,6) if _finite(start) and _finite(duration) else 'x'+str(round(_nx(event)/gap,1))
            group=f"p{page}:s{event.get('system')}:m{event.get('measure')}:fermata:{position}"
            local_end=position if _finite(position) else None
            related=[n for n in notes if n.get('hand')=='right' and n.get('system')==event.get('system') and n.get('measure')==event.get('measure')
                     and (local_end is None or _finite(n.get('measure_beat')) and _finite(n.get('duration')) and abs(n['measure_beat']+n['duration']-local_end)<1e-5)]
            spans=project.setdefault('performance_spans',[]);pause=next((s for s in spans if s['id']==group),None)
            if pause is None:
                pause=dict(id=group,kind='fermata',page=page,system=event.get('system'),staff=staff['id'],source=dict(source),
                    source_note_ids=[n['id'] for n in related],start_note_id=related[0]['id'] if related else None,end_note_id=related[-1]['id'] if related else None,
                    options=dict(page=page,system=event.get('system'),measure=event.get('measure'),local_end_beat=local_end))
                spans.append(pause)
            for anchor in anchored:
                key='anchor_rest_id' if anchor in project.get('rests',[]) else 'anchor_note_id'
                pause['options'].setdefault(key,anchor['id'])
        for n in anchored:
            for part in ('accent','staccato') if kind=='accent_staccato' else ('tenuto','staccato') if kind=='tenuto_staccato' else (kind,):
                _append(n,part,source=source,group=group,options=dict(options))
    # Preserve pedal directions across system/page boundaries. Their paired
    # span is built after all pages, not arbitrarily released at a page edge.
    staff_map={s['id']:s for s in staves}
    for ident,markers in pedals.items():
        staff=staff_map[ident];gap=_gap(staff);markers.sort(key=lambda t:t[0]['x'])
        targets=[s for s in staves if s.get('system')==staff.get('system') and s.get('hand')=='right']
        if not targets:continue
        target=targets[0]
        for symbol,kind,source in markers:
            project.setdefault('performance_directions',[]).append(dict(kind=kind,page=page,system=staff['system'],staff=target['id'],x=round(symbol['x'],3),gap=gap,source=source))
        downs=[s for s,k,_ in markers if k in ('pedal_down','pedal_half')]
        for c in text_chars:
            if c.get('char') not in ('*','∗') or not downs:continue
            x,y=_center(c)
            if not any(s['x']<x and abs(_center(s)[1]-y)<1.2*gap for s in downs):continue
            project.setdefault('performance_directions',[]).append(dict(kind='pedal_up',page=page,system=staff['system'],staff=target['id'],x=round(x,3),gap=gap,source=_source(c,'printed_pedal_release_star')))
        for symbol,kind,source in markers:
            if kind not in ('pedal_down','pedal_half'):continue
            b=_box(symbol)
            for x1,y1,x2,y2,width in lines:
                lo,hi=sorted((x1,x2))
                if abs(y2-y1)>.15*gap or hi-lo<3*gap or width>.25*gap:continue
                if not abs(lo-b[2])<2*gap or not b[1]-gap<y1<b[3]+gap:continue
                hook=next((line for line in lines if abs(line[0]-line[2])<.15*gap and abs(line[0]-hi)<.4*gap
                           and abs(max(line[1],line[3])-y1)<.3*gap and .3*gap<abs(line[3]-line[1])<2.5*gap),None)
                if hook:
                    project.setdefault('performance_directions',[]).append(dict(kind='pedal_up',page=page,system=staff['system'],staff=target['id'],x=round(hi,3),gap=gap,
                        source={'method':'printed_pedal_line_terminal_hook','bbox':[lo,min(y1,hook[1],hook[3]),hi,max(y1,hook[1],hook[3])]}))
    for staff in staves:
        members=by_staff.get(staff['id'],[])
        if not members:continue
        _single_tremolos(project,staff,members,lines)
        _after_graces(staff,members)
        _slurs(project,staff,members,curves)
        _broken_chords(project,staff,members)
    annotate_combinations(notes,{s['id']:_gap(s) for s in staves})
    staff_map={s['id']:s for s in staves}
    for n in notes:
        if not any(m['kind'] in ORNAMENTS|{'glissando','grace_unspecified','grace_long','grace_short','grace_cluster','grace_after'} for m in n.get('performance_marks',[])):continue
        context=dict(key_signature=dict(staff_map[n['staff']].get('key_signature',{})))
        match=re.fullmatch(r'([A-G])(bb|##|b|#|)(-?\d+)',str(n.get('written_pitch') or n.get('pitch')))
        if match:context.update(letter=match[1],alter={'bb':-2,'b':-1,'':0,'#':1,'##':2}[match[2]],octave=int(match[3]))
        n['pitch_context']=context
    for n in notes:
        dot=next((m for m in n.get('performance_marks',[]) if m['kind']=='dots'),None)
        if not dot:continue
        gap=_gap(staff_map[n['staff']]);head=n.get('glyph_bbox') or n.get('bbox')
        if not head:continue
        candidates=[c for c in chars if c.get('char')=='\u01c7' and head[2]+.02*gap<_center(c)[0]<head[2]+3*gap and abs(_center(c)[1]-_ny(n))<.7*gap]
        columns=[]
        for c in sorted(candidates,key=lambda c:c['x']):
            if not columns or c['x']-columns[-1]['x']>.25*gap:columns.append(c)
        if len(columns)==dot['options']['count']:
            dot['source']['bbox']=[min(_box(c)[0] for c in columns),min(_box(c)[1] for c in columns),max(_box(c)[2] for c in columns),max(_box(c)[3] for c in columns)]
    _pair_cross_staff_fermatas(project,page)
    _pair_sustained_measure_fermatas(project,page)
    if any(n.get('performance_marks') for n in notes):
        project['performance_mark_version']=1
    return project


def finalize_performance_spans(project):
    """Resolve global pedal spans using printed directions and real note IDs."""
    directions=sorted(project.get('performance_directions',[]),key=lambda d:(d['page'],d['system'],d['x'],0 if d['kind']=='pedal_up' else 1))
    notes=sorted((n for n in project.get('notes',[]) if n.get('hand')=='right' and not n.get('excluded')),key=lambda n:(n['page'],n['system'],_nx(n),_ny(n)))
    key=lambda e:(e['page'],e['system'],_nx(e))
    staff_map={s['id']:s for s in project.get('staves',[])}
    for index,direction in enumerate(directions):
        if direction['kind'] not in ('pedal_down','pedal_half'):continue
        end=directions[index+1] if index+1<len(directions) else None
        start_key=(direction['page'],direction['system'],direction['x']-direction['gap'])
        end_key=(end['page'],end['system'],end['x']) if end else None
        near=[n for n in notes if end and n['page']==end['page'] and n['system']==end['system'] and abs(_nx(n)-end['x'])<.6*end['gap']]
        columns=_groups(near,end['gap']) if end else []
        aligned=len(columns)==1
        release=columns[0][0] if aligned else next((n for n in notes if end_key is not None and key(n)>=end_key),None)
        if aligned:end_key=(end['page'],end['system'],min(_nx(n) for n in columns[0]))
        selected=[n for n in notes if key(n)>=start_key and (end_key is None or key(n)<end_key)]
        if not selected:continue
        options=dict(depth=.5 if direction['kind']=='pedal_half' else 1.0,
            end_estimated=not aligned,endpoint='printed_release_anchor' if aligned else 'next_attack_estimate' if end else 'score_end_estimate',
            release_note_id=release['id'] if release else None,release_position='before_anchor')
        _span(project,'pedal',staff_map.get(direction['staff'],{'id':direction['staff']}),selected,direction['source'],options=options)
    return project
