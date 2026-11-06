"""Conservative, coordinate-based recognizer for vector Aloisen piano PDFs.

No OCR, file-name answer keys, automatic fingering, MIDI export, or hardware I/O.
All notes require review. PDF coordinates are points, top-left origin; pages are
one-based. Duration is nominal quarter-note beats, never milliseconds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from contextlib import closing
from pathlib import Path
from statistics import median

from pdf_backend import open_document
from fingering_evidence import refine_fingering_evidence
from recognizer_geometry import cross_staff_beam_hands, subdivided_beam_tuplets
from score_marks import annotate_performance_page, finalize_performance_spans
from conversion_progress import notify as _notify_conversion_progress

DIGITS = {chr(0x130 + n): n for n in range(1, 10)}
METER_DIGITS = {chr(0x130 + n): n for n in range(10)}
HEADS = {"Ŵ": "filled", "ż": "open", "Ł": "whole"}
CLEFS = {"ƀ": "treble", "Ɓ": "bass"}
ACCIDENTALS = {"ġ": 1, "Ģ": -1, "ģ": 0, "Ĥ": 2, "ĥ": -2}
FLAGS = {"ř": 1, "ŉ": 1, "Ś": 2, "Ŋ": 2, "ŋ": 3}
RESTS = {"Ţ": 2.0, "ţ": 1.0, "Ť": 0.5, "ť": 0.25, "Ŧ": 0.125}
MEASURE_REST = "š"
UNKNOWN_RESTS = set()
ARPEGGIOS = {"Ƭ"}
LETTERS = "CDEFGAB"
SEMITONES = [0, 2, 4, 5, 7, 9, 11]


def _round_box(box):
    return [round(float(x), 3) for x in box]


def _chars(page):
    return page.chars()


def _initial_printed_tempo(chars, staves, lines):
    """Recognize an explicit metronome note plus '= number' above the music."""
    if not staves:
        return None
    top=min(s['top'] for s in staves);gap=median(s['gap'] for s in staves)
    results=[]
    for equal in chars:
        if equal['char']!='=' or equal['y']>=top:
            continue
        row=sorted((c for c in chars if c.get('font')!='Aloisen'
                    and equal['bbox'][2]-.2*gap<=c['x']<equal['x']+5*equal['size']
                    and abs(c['y']-equal['y'])<.25*equal['size']),key=lambda c:c['x'])
        digits=[]
        for c in row:
            if c['char'].strip()=='' or c['char']=='=':
                continue
            if c['char'] not in '0123456789' or len(c['char'])!=1:
                break
            if digits and c['x']-digits[-1]['bbox'][2]>equal['size']:
                break
            digits.append(c)
        if not digits or len(digits)>3:
            continue
        number=int(''.join(c['char'] for c in digits))
        if not 10<=number<=400:
            continue
        heads=[c for c in chars if c['char'] in HEADS
               and equal['x']-5*gap<c['x']<digits[-1]['bbox'][2]+4*gap
               and abs(c['y']-equal['y'])<1.5*gap
               and not any(_is_score_head(c,s,lines,chars) for s in staves
                           if s['left']<=c['x']<=s['right'] and s['top']-5*s['gap']<=c['y']<=s['bottom']+5*s['gap'])]
        if len(heads)!=1:
            continue
        duration,rhythm,issues=_stem_and_duration(heads[0],{'gap':heads[0]['size']/2},lines,chars)
        if duration is None or issues or rhythm.get('head')!='filled':
            continue
        results.append({'quarter_bpm':number*duration,'printed_number':number,'beat_unit_quarters':duration,
                        'note_bbox':_round_box(heads[0]['bbox']),
                        'text_bbox':_round_box([equal['bbox'][0],min(c['bbox'][1] for c in [equal]+digits),
                                               digits[-1]['bbox'][2],max(c['bbox'][3] for c in [equal]+digits)]),
                        'method':'explicit_metronome_note_equals_number'})
    return results[0] if len(results)==1 else None


def _text_octave_markers(page):
    """Octave instructions can be normal text rather than music-font glyphs."""
    letters=[c for c in page.chars(music_only=False) if c.get('font')!='Aloisen' and c['char'].strip()]
    output=[]
    for first in letters:
        if first['char'] not in ('1','8'):
            continue
        row=sorted((c for c in letters if abs(c['y']-first['y'])<.3*first['size']
                    and first['x']<=c['x']<first['x']+4*first['size']),key=lambda c:c['x'])
        match=re.match(r'(15m[ab]|8v[ab])',''.join(c['char'] for c in row),re.IGNORECASE)
        if not match:
            continue
        glyphs=row[:len(match[0])]
        if any(b['x']-a['bbox'][2]>.8*first['size'] for a,b in zip(glyphs,glyphs[1:])):
            continue
        label=match[0].lower()
        output.append(dict(char='text:'+label,x=first['x'],y=first['y'],size=first['size'],
            bbox=[min(c['bbox'][0] for c in glyphs),min(c['bbox'][1] for c in glyphs),
                  max(c['bbox'][2] for c in glyphs),max(c['bbox'][3] for c in glyphs)],
            octave_semitones=(24 if label.startswith('15') else 12)*(1 if label.endswith('a') else -1)))
    return output


def _geometry(page):
    return page.geometry()


def _staves(lines, page_width):
    # PDF coordinates are not a fixed paper size: the same engraved page can
    # be exported several times larger. Keep the original coordinates for
    # preview overlays, but scale geometric tolerances with the page canvas.
    unit = max(1.0, page_width / 612.0)
    horizontal = sorted((min(x1, x2), y1, max(x1, x2))
                        for x1, y1, x2, y2, width in lines
                        if abs(y1 - y2) < 0.15 * unit and abs(x2 - x1) > page_width * .4
                        and width < 1.5 * unit)
    unique = []
    for line in horizontal:
        if not any(abs(line[1] - u[1]) < .2 * unit and abs(line[0] - u[0]) < 2 * unit for u in unique):
            unique.append(line)
    unique.sort(key=lambda x: x[1])
    output, consumed = [], set()
    for i, first in enumerate(unique):
        if i in consumed:
            continue
        for j in range(i + 1, min(i + 5, len(unique))):
            gap = unique[j][1] - first[1]
            if not 2 <= gap <= 15 * unit:
                continue
            candidates = []
            for k in range(5):
                match = next((n for n, u in enumerate(unique) if n not in consumed
                              and abs(u[1] - first[1] - k * gap) < .25 * unit
                              and abs(u[0] - first[0]) < 2 * unit and abs(u[2] - first[2]) < 2 * unit), None)
                if match is None:
                    break
                candidates.append(match)
            if len(candidates) == 5:
                consumed.update(candidates)
                output.append({"top": first[1], "bottom": first[1] + 4 * gap,
                               "left": first[0], "right": first[2], "gap": gap})
                break
    return sorted(output, key=lambda s: s["top"])


def _nearest_staff(char, staves):
    eligible = [s for s in staves if s["left"] - 2 <= char["x"] <= s["right"] + 2
                and s["top"] - 5*s["gap"] <= char["y"] <= s["bottom"] + 5*s["gap"]]
    return min(eligible, key=lambda s: abs(char["y"] - (s["top"]+s["bottom"])/2), default=None)


def _displaced_second_ledger_evidence(head, staff, lines, chars, staves=None):
    """A displaced second borrows only its actual shaft mate's ledger chain.

    Tight glyph bounds, rather than the font origin, can touch the outside
    ledger of a second. A complete chain on the adjacent head and a physical
    common shaft are both required; proximity to a floating label is not enough.
    """
    gap=staff['gap'];box=head.get('bbox');size=head.get('size',0)
    if (head.get('char') not in ('Ŵ','ż') or head.get('font')!='Aloisen'
            or not box or not 1.6*gap<=size<=2.4*gap):
        return None
    if head['y']<staff['top']-.75*gap:
        edge=staff['top'];direction=-1
    elif head['y']>staff['bottom']+.75*gap:
        edge=staff['bottom'];direction=1
    else:
        return None
    distance=direction*(head['y']-edge)
    count=math.floor((distance+.2*gap)/gap)
    if not 1<=count<=12 or abs(2*distance/gap-round(2*distance/gap))>.2:
        return None
    # This fallback must not move ink belonging inside another printed staff.
    if any(other is not staff and other['left']<=head['x']<=other['right']
           and other['top']-.75*other['gap']<=head['y']<=other['bottom']+.75*other['gap']
           for other in (staves or ())):
        return None
    candidates=[]
    for peer in chars:
        pbox=peer.get('bbox')
        if (peer is head or peer.get('char')!=head['char'] or peer.get('font')!=head['font']
                or not pbox or abs(peer.get('size',0)-size)>.08*size
                or abs(abs(peer['y']-head['y'])-.5*gap)>.1*gap
                or direction*(peer['y']-edge)<=.75*gap):
            continue
        left,right=(head,peer) if box[0]<pbox[0] else (peer,head)
        if (abs(left['bbox'][2]-right['bbox'][0])>.15*gap
                or not .65*gap<=right['bbox'][0]-left['bbox'][0]<=1.6*gap):
            continue
        owner,evidence=_head_staff(peer,staves or [staff],lines)
        if owner is not staff or not evidence or evidence.get('method')!='complete_ledger_chain':
            continue
        # The outermost ledger this pitch requires must contact its tight ink
        # bounds. Intermediate rows are proved by the mate's complete chain.
        ledger_y=edge+direction*count*gap
        contact=[line for line in lines if abs(line[1]-line[3])<.02*gap
                 and abs(line[1]-ledger_y)<.15*gap and gap<abs(line[2]-line[0])<5*gap
                 and min(box[2],max(line[0],line[2]))-max(box[0],min(line[0],line[2]))>.05*gap
                 and box[1]-line[4]/2-.03*gap<=line[1]<=box[3]+line[4]/2+.03*gap]
        if not contact:
            continue
        shafts=[]
        for x1,y1,x2,y2,width in lines:
            lo,hi=sorted((y1,y2));tolerance=width/2+.03*gap
            if (abs(x1-x2)>.02*gap or not 0<width<=.2*gap or not 2*gap<=hi-lo<26*gap
                    or not all(c['bbox'][0]-tolerance<=x1<=c['bbox'][2]+tolerance
                               and lo-.15*gap<=c['y']<=hi+.15*gap for c in (head,peer))
                    or min(abs(end-c['y']) for end in (lo,hi) for c in (head,peer))>.35*gap):
                continue
            shafts.append((x1,lo,hi))
        # Multiple distinct shafts cannot prove a shared chord stem.
        unique=[]
        for shaft in shafts:
            if not any(max(abs(a-b) for a,b in zip(shaft,other))<.05*gap for other in unique):
                unique.append(shaft)
        if len(unique)!=1:
            continue
        candidates.append({'method':'displaced_second_shared_stem_ledger_chain',
                           'ledger_lines':count,'peer_ledger_lines':evidence['ledger_lines'],
                           'peer_origin':_round_box([peer['x'],peer['y']]),
                           'peer_bbox':_round_box(pbox),'stem':_round_box(unique[0]),
                           'contact_ledger':_round_box(contact[0][:4])})
    return candidates[0] if len(candidates)==1 else None


def _head_staff(head, staves, lines, chars=()):
    """A complete ledger chain identifies printed staff even beside its neighbor."""
    nearest=_nearest_staff(head,staves)
    supported=[]
    for staff in staves:
        gap=staff["gap"];x=head["x"];y=head["y"]
        if not staff["left"]-2<=x<=staff["right"]+2:
            continue
        if y<staff["top"]-.75*gap:
            edge=staff["top"];direction=-1;distance=edge-y
        elif y>staff["bottom"]+.75*gap:
            edge=staff["bottom"];direction=1;distance=y-edge
        else:
            continue
        count=math.floor((distance+.2*gap)/gap)
        if not 1<=count<=12:
            continue
        expected=[edge+direction*k*gap for k in range(1,count+1)]
        if all(any(abs(y1-y2)<.2 and abs(y1-ledger_y)<.15*gap
                   and gap<abs(x2-x1)<5*gap and min(x1,x2)-.2*gap<=x<=max(x1,x2)+.2*gap
                   for x1,y1,x2,y2,width in lines) for ledger_y in expected):
            supported.append((staff,count))
    if len(supported)==1:
        staff,count=supported[0]
        return staff,{"method":"complete_ledger_chain","ledger_lines":count,
                      "nearest_staff_reassigned":staff is not nearest}
    if len(supported)>1:
        return nearest,{"method":"ambiguous_ledger_chains","ambiguous":True,"nearest_staff_reassigned":False,
                        "staff_tops":[round(s["top"],3) for s,_ in supported]}
    displaced=[]
    for staff in staves:
        if staff['left']-2<=head['x']<=staff['right']+2:
            evidence=_displaced_second_ledger_evidence(head,staff,lines,chars,staves)
            if evidence:
                displaced.append((staff,evidence))
    if len(displaced)==1:
        staff,evidence=displaced[0]
        return staff,dict(evidence,nearest_staff_reassigned=staff is not nearest)
    return nearest,None


def _stem_beams(stem, head_y, gap, lines, physical_only=False):
    """Count the attached parallel family, not another voice crossing the stem."""
    end=stem[1] if abs(head_y-stem[1])>abs(head_y-stem[2]) else stem[2]
    direction=1 if end<head_y else -1
    candidates=[]
    for x1,y1,x2,y2,width in lines:
        # An isolated secondary beam hook is commonly only 0.9 staff spaces
        # long. Requiring a full space drops genuine dotted-eighth/sixteenth
        # pairs; thickness and attachment to the same stem still disambiguate.
        if abs(x2-x1)<.6*gap or not .3*gap<=width<=.9*gap:
            continue
        end_tolerance=max(.2*gap,width/2+.05*gap)
        lo,hi=min(x1,x2),max(x1,x2)
        if physical_only and not lo<=stem[0]<=hi:
            # Do not extrapolate a finite segment onto a shaft. PDF line-cap
            # style is not retained by this backend; nearby ends therefore
            # remain ambiguous instead of being discarded or extended.
            endpoint_y=y1 if abs(stem[0]-x1)<=abs(stem[0]-x2) else y2
            if min(abs(stem[0]-lo),abs(stem[0]-hi))<=width and -.6*gap-width<=direction*(endpoint_y-end)<=3.2*gap+width:
                return None,[],["beam_attachment_ambiguous"]
            continue
        if lo-end_tolerance<=stem[0]<=hi+end_tolerance:
            slope=(y2-y1)/(x2-x1)
            yy=y1+slope*(stem[0]-x1)
            # In the explicit fallback, discard only strokes whose full ink
            # misses the shaft; retain intersecting candidates and ambiguity.
            near_end=-width/2*math.sqrt(1+slope*slope) if physical_only else -.6*gap
            if near_end<=direction*(yy-end)<=3.2*gap:
                candidates.append((yy,slope,abs(x2-x1)))
    attached=[item for item in candidates if abs(item[0]-end)<=.6*gap]
    if not attached:
        return 0,[],[]
    primary=min(attached,key=lambda item:abs(item[0]-end))
    competing=[item for item in attached if (physical_only or abs(item[0]-end)<=abs(primary[0]-end)+.08*gap)
               and abs(item[1]-primary[1])>.025]
    if competing:
        return None,[],["beam_attachment_ambiguous"]
    ys=[]
    for yy,slope,span in candidates:
        # A short secondary hook may have slightly rounded endpoints. Judge
        # parallelism by its vertical deviation across the actual short span,
        # while full beams still have to agree over several staff spaces.
        if (abs(slope-primary[1])*min(span,4*gap)<.12*gap
                and not any(abs(yy-value)<.25*gap for value in ys)):
            ys.append(yy)
    ordered=sorted(ys)
    if any(not .4*gap<=b-a<=gap for a,b in zip(ordered,ordered[1:])):
        return None,[],["beam_spacing_conflict"]
    return len(ys),[round(y,3) for y in sorted(ys)],[]


def _is_score_head(char, staff, lines, chars=()):
    """Reject metronome noteheads floating above the staff without ledger lines."""
    gap, y, x = staff["gap"], char["y"], char["x"]
    if staff["top"]-.75*gap <= y <= staff["bottom"]+.75*gap:
        return True
    return any(abs(y1-y2)<.2 and gap < abs(x2-x1) < 5*gap
               and min(x1,x2)-.2*gap <= x <= max(x1,x2)
               and min(y,staff["top"]) -.2*gap <= y1 <= max(y,staff["bottom"])+.2*gap
               and (y1 < staff["top"]-.5*gap or y1 > staff["bottom"]+.5*gap)
               for x1,y1,x2,y2,width in lines) or bool(_displaced_second_ledger_evidence(char,staff,lines,chars))


def _augmentation_dot_columns(symbol, gap, chars, stem=None):
    """Chord tones can share a dot column; vertical dots are not double dots."""
    def belongs_to_later_head(dot):
        for head in chars:
            if (head['char'] not in HEADS or head['x']<=symbol['x']+.35*gap
                    or not .8*gap<dot['x']-head['x']<3.4*gap or abs(head['y']-dot['y'])>.6*gap):
                continue
            if (stem and head['x']-.3*gap<=stem[0]<=head['x']+1.6*gap
                    and stem[1]-.35*gap<=head['y']<=stem[2]+.35*gap):
                continue
            return True
        return False
    def articulates_later_head(dot):
        # A dot centred over or under a following head is that head's staccato.
        for head in chars:
            if (head['char'] not in HEADS or head['x']<=symbol['x']+.35*gap
                    or abs(dot['x']+.22*gap-(head['x']+.7*gap))>.3*gap
                    or not .5*gap<abs(head['y']-dot['y'])<=3.5*gap):
                continue
            if stem and stem[1]-.35*gap<=head['y']<=stem[2]+.35*gap and head['x']-.3*gap<=stem[0]<=head['x']+1.6*gap:
                continue
            return True
        return False
    dots = sorted(c['x'] for c in chars if c['char'] == 'Ǉ'
                  and .8*gap < c['x']-symbol['x'] < 3.4*gap
                  and abs(c['y']-symbol['y']) <= .6*gap and not belongs_to_later_head(c)
                  and not articulates_later_head(c))
    columns=[]
    for x in dots:
        if not columns or x-columns[-1] > .25*gap:
            columns.append(x)
    return len(columns)


def _stem_and_duration(head, staff, lines, chars):
    x, y, gap = head["x"], head["y"], staff["gap"]
    head_gap=min(gap,head.get('size',2*gap)/2)
    if head["char"] == "Ł":
        dots = _augmentation_dot_columns(head, gap, chars)
        value = 4.0 * sum(.5**i for i in range(dots+1)) if dots <= 2 else None
        return value, {"head": "whole", "beams": 0, "dots": dots}, ([] if value is not None else ["multiple_dots_require_review"])
    stems = [(x1, min(y1, y2), max(y1, y2)) for x1, y1, x2, y2, w in lines
             if abs(x1-x2) < .2 and abs(y1-y2) >= 2*head_gap and abs(y1-y2) < 26*gap
             and x-.3*gap <= x1 <= x+1.6*gap
             and min(y1,y2)-.35*gap <= y <= max(y1,y2)+.35*gap]
    # Long cross-staff stems must terminate on this head and attach to a real
    # beam at their tip; a spanning barline alone cannot establish a duration.
    stems=[s for s in stems if s[2]-s[1]<10*gap or
           (min(abs(y-s[1]),abs(y-s[2]))<.35*gap and (_stem_beams(s,y,gap,lines)[0] or 0)>0)]
    if not stems:
        return None, {"head": HEADS[head["char"]]}, ["stem_not_resolved"]
    stem = min(stems, key=lambda v: min(abs(y-v[1]), abs(y-v[2])))
    # A chord's upper head can lie near the middle of its long upward stem.
    # The head farthest from an endpoint does not by itself identify the tip.
    # Use all heads physically touching this shaft to find its free extension.
    shaft_heads=[c['y'] for c in chars if c['char'] in ('Ŵ','ż')
                 and c['x']-.3*gap<=stem[0]<=c['x']+1.6*gap
                 and stem[1]-.35*gap<=c['y']<=stem[2]+.35*gap]+[y]
    up_extension=min(shaft_heads)-stem[1];down_extension=stem[2]-max(shaft_heads)
    if up_extension>.6*gap and down_extension<.5*gap:
        anchor=max(shaft_heads)
    elif down_extension>.6*gap and up_extension<.5*gap:
        anchor=min(shaft_heads)
    else:
        anchor=y
    end = stem[1] if abs(anchor-stem[1]) > abs(anchor-stem[2]) else stem[2]
    beam_count,beam_ys,beam_issues=_stem_beams(stem,anchor,gap,lines)
    physical_recovery=False
    if beam_count is None and head.get('size',0)>=1.7*gap:
        exact,exact_ys,exact_issues=_stem_beams(stem,anchor,gap,lines,physical_only=True)
        if exact is not None and exact>0:
            beam_count,beam_ys,beam_issues=exact,exact_ys,exact_issues
            physical_recovery=True
    if beam_count is None:
        return None,{"head":HEADS[head["char"]],"stem":_round_box(stem)},beam_issues
    # Aloisen isolated flag glyphs are positioned at the NOTEHEAD baseline;
    # their visible outline is offset to the stem tip inside the font.
    # A stem-tip-only comparison wrongly turned every such eighth into a quarter.
    flags = [c for c in chars if c["char"] in FLAGS and
             ((abs(c["x"]-x)<.3*gap and abs(c["y"]-y)<.3*gap)
              or (abs(c["x"]-stem[0])<.3*gap and abs(c["y"]-end)<.3*gap)
              # Font origins shift on extended stems and displaced chord heads.
              # The physical flag must meet THIS stem tip; proximity to another
              # note's origin alone is insufficient evidence.
              or (c.get("bbox") is not None
                  and c["bbox"][0]-.3*gap <= stem[0] <= c["bbox"][2]+.3*gap
                  and c["bbox"][1]-.4*gap <= end <= c["bbox"][3]+.4*gap))]
    nearby_unmatched_flags = [c for c in chars if c["char"] in FLAGS and c not in flags
                             and abs(c["x"]-x)<.65*gap and abs(c["y"]-y)<1.2*gap]
    if nearby_unmatched_flags and not flags:
        return None, {"head":HEADS[head["char"]],"beams":len(beam_ys)}, ["flag_anchor_unresolved"]
    beams = max(len(beam_ys), max((FLAGS[c["char"]] for c in flags), default=0))
    issues = []
    if beams > 4 or (head["char"] == "ż" and beams):
        return None, {"head": HEADS[head["char"]], "beams": beams}, ["rhythm_geometry_conflict"]
    value = 2.0 if head["char"] == "ż" else 1.0/(2**beams)
    # A dot must sit beyond the physical notehead, not merely its font advance.
    dots = _augmentation_dot_columns(head, gap, chars, stem)
    if dots:
        if dots <= 2:
            value *= sum(.5**i for i in range(dots+1))
        else:
            issues.append("multiple_dots_require_review")
            value = None
    evidence={"head": HEADS[head["char"]], "beams": beams,
              "dots": dots, "stem": _round_box(stem),
              "stem_direction":"up" if end<y else "down",
              "flag_bboxes": [_round_box(c["bbox"]) for c in flags if c.get("bbox")]}
    if physical_recovery:
        evidence['beam_recovery']={'method':'unique_intersecting_strokes_at_stem_tip'}
    return value,evidence,issues


def _recover_shared_beamed_chord_heads(staves, head_rhythms, lines, chars):
    """A verified original beam/shaft can serve interior heads of a tall chord.

    The individual stem decoder intentionally rejects an unanchored long line.
    Do not relax that rule: recover only a unique existing shaft with a direct
    decoded beam anchor, physically touching equal-font/equal-size filled heads
    whose printed dot count agrees. Arpeggio labels and x proximity play no role.
    """
    recovered=0
    for staff in staves:
        gap=staff['gap'];heads=staff.get('heads',[]);anchors=[]
        for head in heads:
            value,rhythm,issues=head_rhythms[id(head)];stem=rhythm.get('stem');count=rhythm.get('beams')
            if (value is None or issues or not head.get('font') or rhythm.get('head')!='filled' or head.get('size',0)<1.7*gap
                or not isinstance(stem,(list,tuple)) or len(stem)!=3 or type(count) is not int or not 1<=count<=4
                or rhythm.get('stem_direction') not in ('up','down') or rhythm.get('beam_recovery')
                or rhythm.get('dots',0)>2 or _has_grace_slash(rhythm,lines,gap)):
                continue
            dots=rhythm.get('dots',0);expected=1/(2**count)*sum(.5**i for i in range(dots+1))
            if abs(value-expected)>1e-6:continue
            # Both the same continuous physical shaft and the same actual
            # beamed tip are required; a decoded nominal flag alone is not it.
            x,lo,hi=stem
            physical=[line for line in lines if abs(line[0]-line[2])<.04*gap and
                abs(line[0]-x)<.05*gap and abs(min(line[1],line[3])-lo)<.05*gap and
                abs(max(line[1],line[3])-hi)<.05*gap and 0<line[4]<.25*gap]
            beams,_,beam_issues=_stem_beams(stem,head['y'],gap,lines,physical_only=True)
            if len(physical)!=1 or beam_issues or beams!=count:continue
            anchors.append((head,value,rhythm,tuple(stem)))
        plans=[]
        for target in heads:
            old,rhythm,issues=head_rhythms[id(target)]
            if (old is not None or set(issues)!={'stem_not_resolved'} or rhythm.get('head')!='filled'
                or target.get('size',0)<1.7*gap):continue
            box=target.get('bbox')
            if not box or len(box)!=4:continue
            hypotheses={}
            for head,value,proof,shaft in anchors:
                if target.get('font')!=head.get('font') or abs(target.get('size',0)-head.get('size',0))>.02*gap:continue
                x,lo,hi=shaft
                if not box[0]-.15*gap<=x<=box[2]+.15*gap or not lo-.1*gap<=target['y']<=hi+.1*gap:continue
                if not target['x']-.3*gap<=x<=target['x']+1.6*gap:continue
                dots=_augmentation_dot_columns(target,gap,chars,shaft)
                if dots!=proof.get('dots',0):continue
                own_flags=[FLAGS[c['char']] for c in chars if c.get('char') in FLAGS and abs(c['x']-target['x'])<.3*gap and abs(c['y']-target['y'])<.3*gap]
                if own_flags and max(own_flags)>proof['beams']:continue
                hypotheses.setdefault(shaft,[]).append((head,value,proof))
            if len(hypotheses)!=1:continue
            shaft,peers=next(iter(hypotheses.items()))
            if len({(p[1],p[2]['beams'],p[2].get('dots',0),p[2]['stem_direction']) for p in peers})!=1:continue
            # A second physical shaft touching this head is another voice,
            # even if its neighboring head did not decode completely.
            other_shafts={round(line[0],4) for line in lines if abs(line[0]-line[2])<.04*gap and 0<line[4]<.25*gap
                and box[0]-.15*gap<=line[0]<=box[2]+.15*gap and min(line[1],line[3])-.1*gap<=target['y']<=max(line[1],line[3])+.1*gap
                and abs(line[3]-line[1])>=2*gap and abs(line[0]-shaft[0])>.1*gap}
            if other_shafts:continue
            head,value,proof=peers[0]
            recovered_rhythm=dict(proof,beam_recovery=dict(method='unique_direct_shared_beamed_chord_shaft',
                anchor_origins=[_round_box((p[0]['x'],p[0]['y'])) for p in peers],physical_stem=list(shaft)))
            plans.append((target,value,recovered_rhythm))
        for target,value,rhythm in plans:
            head_rhythms[id(target)]=(value,rhythm,[]);recovered+=1
    return recovered


def _physical_shaft_heads(stem, head, chars, gap):
    x,lo,hi=stem
    return [c for c in chars if c.get('char') in ('Ŵ','ż') and c.get('font')==head.get('font')
            and abs(c.get('size',0)-head.get('size',0))<=.02*gap and c.get('bbox')
            and c['bbox'][0]-.15*gap<=x<=c['bbox'][2]+.15*gap
            and lo-.35*gap<=c['y']<=hi+.35*gap]


def _physical_shaft_anchor(stem, head, chars, gap):
    heads=_physical_shaft_heads(stem,head,chars,gap)
    if not heads:return None
    up=min(c['y'] for c in heads)-stem[1];down=stem[2]-max(c['y'] for c in heads)
    if up>.6*gap and down<.5*gap:return max(c['y'] for c in heads),stem[1],'up'
    if down>.6*gap and up<.5*gap:return min(c['y'] for c in heads),stem[2],'down'
    return None


def _flag_meets_tip(flag, stem, end, gap):
    box=flag.get('bbox')
    return bool(box and box[0]-.3*gap<=stem[0]<=box[2]+.3*gap and box[1]-.4*gap<=end<=box[3]+.4*gap)


def _explicit_flag_shaft_tip(flag,stem,head,width,gap):
    """An actual flag glyph anchors its own shaft despite another tip head.

    The flag's ToUnicode origin identifies its head; its entire visible ink
    must be on the appropriate side. Require the real shaft at the correct
    head edge, and its opposite endpoint inside the actual flag ink bounds.
    """
    box=flag.get('bbox');ink=head.get('bbox')
    if not box or not ink:return None
    if (box[1]>head['y'] and abs(stem[1]-head['y'])<.35*gap
            and abs(stem[0]-ink[0])<=width and _flag_meets_tip(flag,stem,stem[2],gap)):
        return stem[2]
    if (box[3]<head['y'] and abs(stem[2]-head['y'])<.35*gap
            and abs(stem[0]-ink[2])<=width and _flag_meets_tip(flag,stem,stem[1],gap)):
        return stem[1]
    return None


def _other_voice_owns_flag(flag, own_stem, head, chars, lines, gap):
    """The nearby flag must have another actual notehead and physical shaft."""
    owners=set()
    for other in chars:
        if (other is head or other.get('char') not in ('Ŵ','ż') or other.get('font')!=head.get('font')
                or abs(other.get('size',0)-head.get('size',0))>.02*gap
                or abs(flag['x']-other['x'])>=.3*gap or abs(flag['y']-other['y'])>=.3*gap):continue
        box=other.get('bbox')
        if not box:continue
        for x1,y1,x2,y2,width in lines:
            if abs(x1-x2)>=.2 or not 0<width<.25*gap or not gap<abs(y2-y1)<26*gap:continue
            stem=(x1,min(y1,y2),max(y1,y2))
            if (not box[0]-.15*gap<=x1<=box[2]+.15*gap or not stem[1]-.35*gap<=other['y']<=stem[2]+.35*gap
                    or abs(x1-own_stem[0])<=.1*gap and abs(stem[1]-own_stem[1])<=.1*gap and abs(stem[2]-own_stem[2])<=.1*gap):continue
            proof=_physical_shaft_anchor(stem,other,chars,gap)
            if (proof and _flag_meets_tip(flag,stem,proof[1],gap) or _explicit_flag_shaft_tip(flag,stem,other,width,gap) is not None):owners.add(stem)
    return len(owners)==1


def _opposed_beam_crossings(stem,anchor,end,direction,head,chars,lines,gap):
    """Remove only a crossing whose two real endpoint voices oppose this shaft.

    A beam ending on the target shaft is retained. A nearby crossing beam is
    unrelated only when BOTH of its own endpoints have real, opposed shafts
    and noteheads. Unowned crossing strokes remain ambiguous.
    """
    endpoint_beams=[];candidates=[]
    for line in lines:
        x1,y1,x2,y2,width=line
        if abs(x2-x1)<.6*gap or not .3*gap<=width<=.9*gap:continue
        lo,hi=sorted((x1,x2))
        if not lo<=stem[0]<=hi:continue
        yy=y1+(y2-y1)*(stem[0]-x1)/(x2-x1)
        if abs(yy-end)>.6*gap:continue
        candidates.append(line)
        if min(abs(stem[0]-x1),abs(stem[0]-x2))<=.1*gap:endpoint_beams.append(line)
    if not endpoint_beams:return lines,[]
    ignored=[]
    for line in candidates:
        if line in endpoint_beams:continue
        x1,y1,x2,y2,width=line
        endpoint_proofs=[]
        for bx,by in ((x1,y1),(x2,y2)):
            proofs=[]
            for sx,sy,tx,ty,sw in lines:
                if abs(sx-tx)>=.2 or not 0<sw<.25*gap or not gap<abs(ty-sy)<26*gap or abs(sx-bx)>.1*gap:continue
                other=(sx,min(sy,ty),max(sy,ty))
                for c in chars:
                    if (c.get('char')!='Ŵ' or c.get('font')!=head.get('font') or c.get('size',0)<1.7*gap
                            or not c.get('bbox') or not c['bbox'][0]-.15*gap<=sx<=c['bbox'][2]+.15*gap
                            or not other[1]-.35*gap<=c['y']<=other[2]+.35*gap):continue
                    proof=_physical_shaft_anchor(other,c,chars,gap)
                    if proof and proof[2]!=direction and abs(proof[1]-by)<=.6*gap:proofs.append(other)
            endpoint_proofs.append(set(proofs))
        if all(len(proofs)==1 for proofs in endpoint_proofs) and endpoint_proofs[0]!=endpoint_proofs[1]:ignored.append(line)
    return [line for line in lines if line not in ignored],ignored


def _recover_explicit_physical_rhythms(staves,head_rhythms,lines,chars):
    """Recover unresolved written values from a unique actual shaft/voice.

    This does not change a known duration, use next-onset spacing, infer grace
    duration, or treat an open head with a beam as an ordinary beamed half note.
    """
    recovered=0
    allowed={'stem_not_resolved','flag_anchor_unresolved','rhythm_geometry_conflict','beam_attachment_ambiguous'}
    for staff in staves:
        gap=staff['gap']
        for head in staff.get('heads',[]):
            old,old_rhythm,issues=head_rhythms[id(head)]
            if (old is not None or not issues or not set(issues)<=allowed or not head.get('font')
                    or head.get('char') not in ('Ŵ','ż') or head.get('size',0)<1.7*gap or not head.get('bbox')):continue
            box=head['bbox'];hypotheses={};foreign_flag_shafts={};tip_beams={}
            for x1,y1,x2,y2,width in lines:
                if (abs(x1-x2)>=.2 or not 0<width<.25*gap or not gap<abs(y2-y1)<26*gap
                        or not box[0]-.15*gap<=x1<=box[2]+.15*gap):continue
                stem=(x1,min(y1,y2),max(y1,y2))
                if not stem[1]-.35*gap<=head['y']<=stem[2]+.35*gap:continue
                proof=_physical_shaft_anchor(stem,head,chars,gap)
                if proof is None:continue
                anchor,end,direction=proof
                # Physical slash/cue context remains governed by grace logic.
                if _has_grace_slash({'stem':stem},lines,gap):continue
                working,ignored=_opposed_beam_crossings(stem,anchor,end,direction,head,chars,lines,gap)
                beam_count,beam_ys,beam_issues=_stem_beams(stem,anchor,gap,working)
                if beam_count is None or beam_issues or not 0<=beam_count<=4:continue
                flags=[c for c in chars if c.get('char') in FLAGS and c.get('font')==head.get('font')
                       and abs(c.get('size',0)-head.get('size',0))<=.02*gap and _flag_meets_tip(c,stem,end,gap)]
                nearby=[c for c in chars if c.get('char') in FLAGS and c not in flags
                        and abs(c['x']-head['x'])<.65*gap and abs(c['y']-head['y'])<1.2*gap]
                if any(not _other_voice_owns_flag(c,stem,head,chars,lines,gap) for c in nearby):continue
                flag_count=max((FLAGS[c['char']] for c in flags),default=0)
                if beam_count and flag_count and beam_count!=flag_count:continue
                count=max(beam_count,flag_count)
                if head['char']=='ż':
                    if count:continue
                    # A separate beamed shaft may share the open notehead, but
                    # this chosen shaft must independently show the half value.
                    if len([s for s in lines if abs(s[0]-s[2])<.2 and abs(s[0]-x1)<.1*gap
                            and abs(min(s[1],s[3])-stem[1])<.1*gap and abs(max(s[1],s[3])-stem[2])<.1*gap])!=1:continue
                    value=2.
                else:
                    if not count and not nearby:continue
                    if stem[2]-stem[1]<2*gap and not beam_count:continue
                    value=1/(2**count)
                dots=_augmentation_dot_columns(head,gap,chars,stem)
                if dots>2:continue
                value*=sum(.5**i for i in range(dots+1))
                evidence=dict(head=HEADS[head['char']],beams=count,dots=dots,stem=_round_box(stem),stem_direction=direction,
                    flag_bboxes=[_round_box(c['bbox']) for c in flags],
                    beam_recovery=dict(method='unique_physical_shaft_and_voice_ownership',
                        discarded_other_voice_flags=[_round_box(c['bbox']) for c in nearby],
                        discarded_opposed_beams=[_round_box(c) for c in ignored],
                        original_issues=list(issues)))
                key=tuple(round(v,4) for v in stem)
                hypotheses.setdefault(key,[]).append((value,evidence));tip_beams[key]=beam_count
                head_end=stem[2] if direction=='up' else stem[1]
                if flags and not beam_count and abs(head['y']-head_end)>.35*gap:
                    owners=[]
                    for flag in flags:
                        matches=[other for other in _physical_shaft_heads(stem,head,chars,gap) if other is not head
                            and abs(flag['x']-other['x'])<.3*gap and abs(flag['y']-other['y'])<.3*gap
                            and abs(other['y']-head_end)<.35*gap
                            and _explicit_flag_shaft_tip(flag,stem,other,width,gap) is not None]
                        if len(matches)!=1:break
                        owners.append(_round_box((matches[0]['x'],matches[0]['y'])))
                    else:foreign_flag_shafts[key]=dict(stem=_round_box(stem),owner_origins=owners,flag_bboxes=evidence['flag_bboxes'])
            if len(hypotheses)>1:
                # A shaft can cross another voice's head at its side. Only a
                # unique beamed shaft ending on this head can defeat a crossing
                # flagged shaft whose flag and head-end explicitly name another
                # head. Do not resolve competing terminal or beamed shafts.
                terminal=[key for key,rows in hypotheses.items() if tip_beams[key]>0 and
                    all(abs(head['y']-(key[2] if r['stem_direction']=='up' else key[1]))<.35*gap for _,r in rows)]
                if len(terminal)==1 and all(key in foreign_flag_shafts for key in hypotheses if key!=terminal[0]):
                    key=terminal[0];rows=hypotheses[key]
                    for _,r in rows:r['beam_recovery']['discarded_crossing_flag_shafts']=[foreign_flag_shafts[k] for k in hypotheses if k!=key]
                    hypotheses={key:rows}
            if len(hypotheses)!=1:continue
            candidates=next(iter(hypotheses.values()))
            if len({(v,r['beams'],r['dots'],r['stem_direction']) for v,r in candidates})!=1:continue
            value,evidence=candidates[0];head_rhythms[id(head)]=(value,evidence,[]);recovered+=1
    return recovered


def _recover_secondary_beam_voice_ownership(staves,head_rhythms,lines,chars):
    """A short hook belongs to one actual primary beam, not both voices.

    Only an independently decoded other shaft may disambiguate the hook.
    Parent beams must be long, physically printed and uniquely at their own
    tips. Recoveries never become new anchors, and known values never change.
    """
    def primary(stem,end,gap):
        choices=[]
        for line in lines:
            x1,y1,x2,y2,width=line
            if abs(x2-x1)<3*gap or not .3*gap<=width<=.9*gap:continue
            if not min(x1,x2)<=stem[0]<=max(x1,x2):continue
            slope=(y2-y1)/(x2-x1);yy=y1+slope*(stem[0]-x1)
            if abs(yy-end)<=.6*gap:choices.append((abs(yy-end),slope,line))
        choices.sort(key=lambda row:row[0])
        if not choices or any(c[0]<=choices[0][0]+.08*gap and abs(c[1]-choices[0][1])>.025 for c in choices[1:]):return None
        return choices[0]
    def physical(stem,gap):
        return any(abs(l[0]-l[2])<.04*gap and 0<l[4]<.25*gap and abs(l[0]-stem[0])<.05*gap
                   and abs(min(l[1],l[3])-stem[1])<.05*gap and abs(max(l[1],l[3])-stem[2])<.05*gap for l in lines)
    recovered=0
    for staff in staves:
        gap=staff['gap'];heads=staff.get('heads',[]);anchors=[]
        for h in heads:
            value,r,issues=head_rhythms[id(h)];stem=r.get('stem')
            if (value is None or issues or r.get('beam_recovery') or r.get('head')!='filled' or r.get('dots')
                    or r.get('flag_bboxes') or not stem or not isinstance(r.get('beams'),int) or not 1<=r['beams']<=4
                    or abs(value-1/(2**r['beams']))>1e-6 or h.get('size',0)<1.7*gap or not physical(stem,gap)):continue
            p=_physical_shaft_anchor(stem,h,chars,gap)
            if not p:continue
            beam=primary(stem,p[1],gap)
            direct,_,errors=_stem_beams(stem,p[0],gap,lines)
            if beam and not errors and direct==r['beams']:anchors.append((h,stem,p,beam))
        plans=[]
        for h in heads:
            old,r,issues=head_rhythms[id(h)];stem=r.get('stem')
            if (old is not None or set(issues)!={'beam_spacing_conflict'} or r.get('head')!='filled' or not stem
                    or h.get('size',0)<1.7*gap or not physical(stem,gap)):continue
            p=_physical_shaft_anchor(stem,h,chars,gap)
            if not p or _has_grace_slash({'stem':stem},lines,gap):continue
            own=primary(stem,p[1],gap)
            if not own:continue
            other=[a for a in anchors if a[0] is not h and a[0].get('font')==h.get('font')
                   and abs(a[1][0]-stem[0])<.1*gap and a[2][2]==p[2]
                   and abs(a[2][1]-p[1])>.08*gap and abs(a[3][1]-own[1])>.025]
            if not other:continue
            removed=[]
            for line in lines:
                x1,y1,x2,y2,width=line;span=abs(x2-x1)
                if not .6*gap<=span<2.5*gap or not .3*gap<=width<=.9*gap:continue
                if min(abs(stem[0]-x1),abs(stem[0]-x2))>max(.2*gap,width/2+.05*gap):continue
                slope=(y2-y1)/(x2-x1);own_error=abs(slope-own[1])
                matches=[a for a in other if abs(slope-a[3][1])*span<.12*gap and abs(slope-a[3][1])+.025<own_error
                         and min(a[3][2][0],a[3][2][2])-.2*gap<=min(x1,x2) and max(x1,x2)<=max(a[3][2][0],a[3][2][2])+.2*gap]
                if len({tuple(a[1]) for a in matches})==1:removed.append(line)
            if not removed:continue
            filtered=[line for line in lines if line not in removed];count,_,errors=_stem_beams(stem,p[0],gap,filtered)
            if errors or count is None or not 1<=count<=4:continue
            dots=_augmentation_dot_columns(h,gap,chars,stem)
            if dots>2:continue
            value=1/(2**count)*sum(.5**i for i in range(dots+1))
            proof=dict(head='filled',beams=count,dots=dots,stem=list(stem),stem_direction=p[2],flag_bboxes=[],
                       beam_recovery=dict(method='short_secondary_hook_owned_by_independent_overlapping_voice',
                           other_anchor_origins=[_round_box((a[0]['x'],a[0]['y'])) for a in other],discarded_foreign_hooks=[_round_box(line) for line in removed]))
            plans.append((h,value,proof))
        for h,value,proof in plans:head_rhythms[id(h)]=(value,proof,[]);recovered+=1
    return recovered


def _recover_explicit_short_quarters(staves,head_rhythms,lines,chars):
    """A separately drawn normal-size short shaft is still a written quarter.

    Require a unique thin path at the correct head attachment edge, starting
    on that head and spanning several actual stroke widths. No grace, beam,
    flag, shared-head shaft, slash or geometric uncertainty is converted.
    """
    recovered=0
    for staff in staves:
        gap=staff['gap']
        for head in staff.get('heads',[]):
            old,rhythm,issues=head_rhythms[id(head)]
            if (old is not None or set(issues)!={'stem_not_resolved'} or head.get('char')!='Ŵ'
                    or not head.get('font') or head.get('size',0)<1.7*gap or not head.get('bbox')):continue
            box=head['bbox'];hypotheses={}
            for x1,y1,x2,y2,width in lines:
                if abs(x1-x2)>=.2 or not 0<width<.25*gap or not 3*width<abs(y2-y1)<2*gap:continue
                stem=(x1,min(y1,y2),max(y1,y2))
                if abs(stem[1]-head['y'])<.35*gap and abs(x1-box[0])<=width:
                    direction='down';anchor=stem[1];end=stem[2]
                elif abs(stem[2]-head['y'])<.35*gap and abs(x1-box[2])<=width:
                    direction='up';anchor=stem[2];end=stem[1]
                else:continue
                if len(_physical_shaft_heads(stem,head,chars,gap))!=1 or _has_grace_slash({'stem':stem},lines,gap):continue
                beams,_,beam_issues=_stem_beams(stem,anchor,gap,lines)
                if beams!=0 or beam_issues:continue
                flags=[c for c in chars if c.get('char') in FLAGS and c.get('font')==head.get('font')
                       and ((abs(c['x']-head['x'])<.3*gap and abs(c['y']-head['y'])<.3*gap)
                            or _flag_meets_tip(c,stem,end,gap))]
                if flags:continue
                dots=_augmentation_dot_columns(head,gap,chars,stem)
                if dots>2:continue
                value=sum(.5**i for i in range(dots+1))
                proof=dict(head='filled',beams=0,dots=dots,stem=_round_box(stem),stem_direction=direction,flag_bboxes=[],
                    short_stem_recovery=dict(method='normal_head_unique_explicit_short_shaft_without_flag_or_beam',stroke_width=round(width,6)))
                hypotheses[tuple(round(v,4) for v in stem)]=(value,proof)
            if len(hypotheses)==1:
                value,proof=next(iter(hypotheses.values()));head_rhythms[id(head)]=(value,proof,[]);recovered+=1
    return recovered


def _grace_slash_evidence(rhythm, lines, gap):
    """Return the actual diagonal stroke crossing this note's stem."""
    stem=rhythm.get('stem')
    if not stem:
        return None
    for x1,y1,x2,y2,width in lines:
        if (.4*gap<abs(x2-x1)<2.5*gap and .3*gap<abs(y2-y1)<2.5*gap
                and 0<width<.25*gap and min(x1,x2)<stem[0]<max(x1,x2)):
            y=y1+(y2-y1)*(stem[0]-x1)/(x2-x1)
            if stem[1]+.3*gap<y<stem[2]-.3*gap:
                return {'method':'diagonal_stroke_crosses_note_stem','stroke':_round_box((x1,y1,x2,y2,width))}
    return None


def _has_grace_slash(rhythm, lines, gap):
    return _grace_slash_evidence(rhythm,lines,gap) is not None


def _rest_duration(rest, gap, chars, meter, solitary=False):
    if rest["char"] == MEASURE_REST:
        # A whole rest alone denotes a whole measure even in 2/4 or 3/4.
        return (meter if solitary else 4.0), {"glyph":rest["char"], "whole_measure":solitary}
    duration = RESTS.get(rest["char"])
    dots = [c for c in chars if c["char"] == "Ǉ"
            and .8*gap < c["x"]-rest["x"] < 3.4*gap
            and abs(c["y"]-rest["y"]) <= .6*gap]
    if duration is not None and len(dots) <= 2:
        duration *= sum(.5**i for i in range(len(dots)+1))
    elif dots:
        duration = None
    return duration, {"glyph":rest["char"], "dots":len(dots)}


def _opening_key_signature(staff, events, previous_staves=()):
    """Read the clef/header prefix, independent of the first note's spacing.

    Key signs precede the printed meter and follow standard ordered staff
    positions. A first-note accidental after the meter remains local.
    """
    if not events:
        return [], {}
    gap=staff['gap']
    first_x=min(event['x'] for event in events)
    clefs=sorted((c for c in staff['clefs'] if c['x']<first_x),key=lambda c:c['x'])
    if not clefs:
        return [], {}
    clef=clefs[0]
    clef_name=CLEFS[clef['char']]
    clef_right=clef.get('bbox',[clef['x'],0,clef['x'],0])[2]
    meters=[change['x'] for change in _meter_changes(staff,staff['chars']) if change['x']<first_x]
    boundary=min([first_x]+meters)
    prefix=sorted((c for c in staff['chars'] if c['char'] in ('ġ','Ģ')
                   and clef_right<=c['x']<boundary),key=lambda c:c['x'])
    if not prefix or prefix[0]['x']-clef_right>2.5*gap:
        return [], {}
    sharp=prefix[0]['char']=='ġ'
    positions={('treble',True):(8,5,9,6,3,7,4),
               ('treble',False):(4,7,3,6,2,5,1),
               ('bass',True):(6,3,7,4,1,5,2),
               ('bass',False):(2,5,1,4,0,3,-1)}[clef_name,sharp]
    keys=[]
    for sign in prefix:
        if (len(keys)==7 or sign['char']!=prefix[0]['char']
                or keys and sign['x']-keys[-1]['x']>1.75*gap
                or abs(sign['y']-(staff['bottom']-positions[len(keys)]*gap/2))>.3*gap):
            break
        keys.append(sign)
    if not keys:
        return [], {}
    order='FCGDAEB' if sharp else 'BEADGCF'
    key_map={letter:(1 if sharp else -1) for letter in order[:len(keys)]}
    # A canonical sign can still be a first-note accidental in a header
    # without a time signature. Reuse the ordinary local-accidental geometry
    # rather than globalizing it just because it follows the clef. Repeated
    # signatures have the previously verified same-hand header as evidence.
    local_tail=any(event['char'] in HEADS
                   and .15*gap<event['x']-keys[-1]['x']<2.3*gap
                   and abs(event['y']-keys[-1]['y'])<.3*gap
                   for event in events if abs(event['x']-first_x)<.15*gap)
    previous=next((s for s in reversed(previous_staves)
                   if s.get('hand')==staff.get('hand') and s.get('hand') is not None),None)
    cancelled=any(c['char']=='ģ' and clef_right<=c['x']<keys[0]['x'] for c in staff['chars'])
    if local_tail and not meters and (cancelled or previous is None or previous.get('key_signature')!=key_map):
        keys=keys[:-1]
        key_map={letter:(1 if sharp else -1) for letter in order[:len(keys)]}
    return keys,key_map


def _meter_signature(staff, digits):
    """Read complete aligned numeral rows, including 12/8 and 16 denominators."""
    gap=staff["gap"]
    rows=[]
    for baseline in (staff["top"]+gap,staff["top"]+3*gap):
        row=sorted((c for c in digits if abs(c["y"]-baseline)<.5*gap),key=lambda c:c["x"])
        if not row or any(b["x"]-a["x"]>2*gap for a,b in zip(row,row[1:])):
            return None,None
        rows.append(row)
    centers=[(row[0]["x"]+row[-1].get("bbox",[0,0,row[-1]["x"]+gap,0])[2])/2 for row in rows]
    if abs(centers[0]-centers[1])>1.5*gap:
        return None,None
    numerator,denominator=(int(''.join(str(METER_DIGITS[c["char"]]) for c in row)) for row in rows)
    if not 1<=numerator<=32 or denominator not in (1,2,4,8,16,32,64):
        return None,None
    return 4*numerator/denominator,{"numerator":numerator,"denominator":denominator,
                                   "digit_bboxes":[_round_box(c["bbox"]) for row in rows for c in row if c.get("bbox")]}


def _meter_changes(staff, chars):
    """Read printed time signatures throughout a staff, not just its header."""
    gap=staff['gap']
    digits=sorted((c for c in chars if c['char'] in METER_DIGITS and c['size']>1.5*gap
                   and min(abs(c['y']-staff['top']-gap),abs(c['y']-staff['top']-3*gap))<.5*gap),
                  key=lambda c:c['x'])
    groups=[]
    for c in digits:
        if not groups or c['x']-groups[-1][-1]['x']>2*gap:
            groups.append([])
        groups[-1].append(c)
    changes=[]
    for group in groups:
        value,evidence=_meter_signature(staff,group)
        if value is not None:
            changes.append({'x':min(c['x'] for c in group),'beats':value,'evidence':evidence})
    changes.extend({'x':c['x'],'beats':4.0,'evidence':{'symbol':'common_time'}}
                   for c in chars if c['char']=='Ɗ')
    changes.extend({'x':c['x'],'beats':4.0,'evidence':{'symbol':'cut_time'}}
                   for c in chars if c['char']=='Ƌ')
    return sorted(changes,key=lambda c:c['x'])


def _explicit_lower_octave(marker):
    """Only a decoded bassa label establishes downward octave semantics."""
    return (marker.get('char')=='Ƶ' or (marker.get('char')=='text:8vb' and marker.get('octave_semitones')==-12)
            or (marker.get('char')=='text:15mb' and marker.get('octave_semitones')==-24))


def _octave_marker_staff(marker, staves):
    """A bassa below the upper staff must not attach to the next lower staff."""
    if not _explicit_lower_octave(marker):
        return min(staves,key=lambda s:abs(marker['y']-(s['top']+s['bottom'])/2))
    # The semantic label is not sufficient if its placement is inside a staff.
    # Select the nearest lower edge above a genuine below-staff label instead
    # of the nearest staff centre, which changes ownership between two staves.
    if any(s['left']-.3*s['gap']<=marker['x']<=s['right']+.3*s['gap']
           and s['top']-.5*s['gap']<=marker['y']<=s['bottom']+.5*s['gap']
           for s in staves):
        return None
    choices=[s for s in staves
             if s['left']-.3*s['gap']<=marker['x']<=s['right']+.3*s['gap']
             and .5*s['gap']<marker['y']-s['bottom']<10*s['gap']]
    if not choices:
        return None
    distances=sorted(((marker['y']-s['bottom'])/s['gap'],i,s)
                     for i,s in enumerate(choices))
    if len(distances)>1 and distances[1][0]-distances[0][0]<.3:
        return None
    return distances[0][2]


def _octave_regions(staff, markers, lines):
    """Resolve bounded octave lines or a lone final note explicitly marked."""
    gap=staff["gap"]
    regions=[]
    for marker in markers:
        region={"start_x":marker["x"],"end_x":staff["right"],"shift":None,
                "marker_bbox":_round_box(marker["bbox"]),"glyph":marker["char"]}
        preceding=sorted({h['x'] for h in staff.get('heads',[]) if h['x']<=marker['x']})
        if len(preceding)==1 and marker['x']-preceding[0]<3*gap:
            region.update(start_x=preceding[0],start_evidence='marker_over_first_staff_column')
        # The above-staff ƴ glyph was visually verified as 8va. A lower octave
        # additionally needs an explicit bassa label and below-staff placement.
        # Unknown music-font glyphs retain the existing review boundary.
        shift=12 if marker['char']=='ƴ' else -12 if marker['char']=='Ƶ' else marker.get('octave_semitones')
        lower=_explicit_lower_octave(marker)
        if (shift is None or (shift<0 and not lower)
                or (lower and marker['y']<=staff['bottom']+.5*gap)
                or (not lower and marker['y']>=staff['top']-.5*gap)):
            regions.append(region);continue
        cap_edge=max if lower else min
        # A compact octave bracket may finish before the text label's right
        # bearing. Engravers then draw its short horizontal stroke backwards.
        # The connected terminal hook still bounds the marked column; a label
        # without that physical L-shaped endpoint remains unresolved.
        compact=[]
        for x1,y1,x2,y2,width in lines:
            if (abs(x1-x2)>.2 or not .25*gap<abs(y1-y2)<1.5*gap
                    or width>=.2*gap or not region['start_x']-.15*gap<=x1<=marker['bbox'][2]+1.5*gap):
                continue
            y=cap_edge(y1,y2)
            if not marker['bbox'][1]-.3*gap<y<marker['bbox'][3]+.3*gap:
                continue
            connected=[]
            for a,b,c,d,w in lines:
                if abs(b-d)>=.15 or w>=.2*gap or not .05*gap<abs(a-c)<3*gap:
                    continue
                if abs(b-y)>.2*gap:
                    continue
                for endpoint,other in ((a,c),(c,a)):
                    if abs(endpoint-x1)<.15*gap and abs(other-marker['bbox'][2])<.8*gap:
                        connected.append((other,y))
            if connected and not any(abs(x1-old)<.1*gap for old in compact):
                compact.append(x1)
        if len(compact)==1:
            region.update(end_x=compact[0],shift=shift,line_type='compact',endpoint='cap')
            regions.append(region);continue
        # Some engravers use one continuous hairline with the same terminal
        # hook as a dashed ottava. The explicit marker, start and hook establish
        # its extent; an arbitrary horizontal rule alone does not.
        solid=[]
        for x1,y1,x2,y2,width in lines:
            lo,hi=sorted((x1,x2))
            if (abs(y1-y2)<.15 and hi-lo>.3*gap and width<.2*gap
                and marker["bbox"][1]-.3*gap<y1<marker["bbox"][3]+.3*gap
                and abs(lo-marker["bbox"][2])<1.5*gap and hi<=staff["right"]+gap):
                caps=[x for x,a,z,b,w in lines if abs(x-z)<.2
                      and abs(cap_edge(a,b)-y1)<.3*gap and .1*gap<abs(a-b)<3*gap
                      and abs(x-hi)<.3*gap]
                if caps:
                    solid.append((hi,y1))
        if len(solid)==1:
            region.update(end_x=solid[0][0],shift=shift,line_type="continuous",endpoint="cap")
            regions.append(region);continue
        horizontal=[]
        for x1,y1,x2,y2,width in lines:
            lo,hi=sorted((x1,x2))
            if (abs(y1-y2)<.15 and .25*gap<hi-lo<1.5*gap and width<.2*gap
                and marker["bbox"][1]-.3*gap<y1<marker["bbox"][3]+.3*gap
                and lo>=marker["bbox"][2]-.3*gap and hi<=staff["right"]+gap):
                if not any(abs(lo-a)<.1*gap and abs(hi-b)<.1*gap and abs(y1-y)<.2*gap for a,b,y in horizontal):
                    horizontal.append((lo,hi,y1))
        horizontal.sort()
        first=next((item for item in horizontal if abs(item[0]-marker["bbox"][2])<1.5*gap),None)
        if first is None:
            remaining=[h for h in staff.get('heads',[]) if h['x']>=marker['x']-.3*gap]
            if marker.get('octave_semitones') and len(remaining)==1 and abs(remaining[0]['x']-marker['x'])<2*gap:
                region.update(shift=shift,endpoint='single_remaining_note')
            regions.append(region);continue
        chain=[first]
        for item in horizontal:
            if item[0]<=first[0] or abs(item[2]-first[2])>.2*gap:
                continue
            if item[0]-chain[-1][1]>1.8*gap:
                break
            chain.append(item)
        if len(chain)<3:
            regions.append(region);continue
        right=chain[-1][1];y=median(item[2] for item in chain)
        caps=[x1 for x1,y1,x2,y2,w in lines if abs(x1-x2)<.2
              and abs(cap_edge(y1,y2)-y)<.3*gap and .3*gap<abs(y1-y2)<3*gap
              and 0<=x1-right<1.5*gap]
        endpoint=min(caps) if caps else staff["right"] if abs(right-staff["right"])<gap else None
        if endpoint is not None:
            region.update(end_x=endpoint,shift=shift,dash_count=len(chain),dash_y=round(y,3),
                          endpoint="cap" if caps else "system_edge")
        regions.append(region)
    return regions


def _octave_at(x, regions, gap):
    matching=[r for r in regions if r["start_x"]-.3*gap<=x<=r["end_x"]+.15*gap]
    if not matching:
        return 0,None
    if len(matching)!=1:
        return None,{"overlapping_regions":matching}
    return matching[0]["shift"],matching[0]


def _event_groups(events, gap):
    """Shared stems, including displaced seconds, establish chord simultaneity."""
    groups = []
    for event in events:
        stem = event["rhythm_evidence"].get("stem")
        whole_second=lambda other: (
            event["rhythm_evidence"].get("head")==other["rhythm_evidence"].get("head")=="whole"
            and not stem and not other["rhythm_evidence"].get("stem")
            and .35*gap<abs(event["origin"][1]-other["origin"][1])<.65*gap
            and .9*gap<abs(event["origin"][0]-other["origin"][0])<1.8*gap
            and event.get("glyph_bbox") is not None and other.get("glyph_bbox") is not None
            and max(event["glyph_bbox"][0],other["glyph_bbox"][0])<=min(event["glyph_bbox"][2],other["glyph_bbox"][2])+.15*gap)
        group = next((g for g in groups if g[0]["measure"] == event["measure"] and
                      (abs(g[0]["origin"][0]-event["origin"][0]) < .35*gap
                       or (stem and g[0]["rhythm_evidence"].get("stem") == stem)
                       or any(whole_second(other) for other in g))), None)
        if group is None:
            groups.append([event])
        else:
            group.append(event)
    return groups


def _apply_printed_tuplets(events, staff, lines, text_chars):
    """Read a numeral adjacent to an exact beamed group; never infer from sums."""
    gap=staff['gap'];used=set()
    ratios={3:2,5:4,6:4,7:4,9:8}
    for marker in text_chars:
        if marker.get('font')=='Aloisen' or marker['char'] not in ('3','5','6','7','9'):
            continue
        actual=int(marker['char']);normal=ratios[actual]
        center=(marker['bbox'][0]+marker['bbox'][2])/2
        cy=(marker['bbox'][1]+marker['bbox'][3])/2
        candidates={}
        for x1,y1,x2,y2,width in lines:
            if not .3*gap<=width<=.9*gap or abs(x2-x1)<gap:
                continue
            lo,hi=sorted((x1,x2))
            if not lo-.5*gap<=center<=hi+.5*gap:
                continue
            slope=(y2-y1)/(x2-x1);line_y=y1+slope*(center-x1)
            if not .15*gap<abs(cy-line_y)<2.5*gap:
                continue
            stems={}
            for note in events:
                stem=note['rhythm_evidence'].get('stem')
                if (not stem or note['duration'] is None or note['id'] in used
                        or 'grace_or_cue_note_requires_review' in note['issues']
                        or not lo-max(.2*gap,width/2+.05*gap)<=stem[0]<=hi+max(.2*gap,width/2+.05*gap)):
                    continue
                y=y1+slope*(stem[0]-x1)
                if stem[1]-.2*gap<=y<=stem[2]+.2*gap:
                    stems.setdefault(tuple(stem),[]).append(note)
            groups=sorted(stems.values(),key=lambda g:g[0]['rhythm_evidence']['stem'][0])
            if len(groups)!=actual:
                continue
            notes=[note for group in groups for note in group]
            directions={n['rhythm_evidence'].get('stem_direction') for n in notes}
            if len(directions)!=1 or len({n['duration'] for n in notes})!=1 or len({n['measure'] for n in notes})!=1:
                continue
            direction=next(iter(directions))
            if (direction=='up' and cy>=line_y) or (direction=='down' and cy<=line_y):
                continue
            midpoint=(groups[0][0]['rhythm_evidence']['stem'][0]+groups[-1][0]['rhythm_evidence']['stem'][0])/2
            if abs(center-midpoint)>1.1*gap:
                continue
            candidates[tuple(n['id'] for n in notes)]=notes
        if len(candidates)!=1:
            continue
        notes=next(iter(candidates.values()))
        for note in notes:
            value=note['duration']*normal/actual
            evidence={'actual':actual,'normal':normal,'marker_bbox':_round_box(marker['bbox']),
                      'nominal_duration_beats':note['duration'],'method':'printed_number_and_exact_beamed_group'}
            note['duration']=note['beats']=value
            note['rhythm_evidence']={**note['rhythm_evidence'],'tuplet':evidence}
            used.add(note['id'])
    subdivided_beam_tuplets(events,staff,lines,text_chars)


def _apply_bracketed_tuplets(notes, rests, staff, lines, text_chars):
    """An explicit capped bracket also defines mixed-value tuplet groups."""
    gap=staff['gap']
    for marker in text_chars:
        if marker.get('font')=='Aloisen' or marker['char'] not in ('3','5','6','7','9'):
            continue
        actual=int(marker['char']);normal={3:2,5:4,6:4,7:4,9:8}[actual]
        box=marker['bbox'];segments=[]
        for x1,y1,x2,y2,width in lines:
            if (abs(y1-y2)<.15 and .7*gap<abs(x2-x1) and 0<width<.25*gap
                    and box[1]-.3*gap<=y1<=box[3]+.3*gap):
                segments.append((min(x1,x2),max(x1,x2),y1))
        left=[s for s in segments if 0<=box[0]-s[1]<gap]
        right=[s for s in segments if 0<=s[0]-box[2]<gap]
        spans=[]
        for a in left:
            for b in right:
                if abs(a[2]-b[2])>.2*gap:
                    continue
                y=(a[2]+b[2])/2
                cap=lambda x:any(abs(x1-x2)<.2 and abs(x1-x)<.2*gap and .2*gap<abs(y1-y2)<2*gap
                    and min(abs(y1-y),abs(y2-y))<.2*gap for x1,y1,x2,y2,width in lines)
                if cap(a[0]) and cap(b[1]):
                    spans.append((a[0],b[1],y))
        if len(spans)!=1:
            continue
        lo,hi,y=spans[0]
        inside=[n for n in notes if lo-.2*gap<=n['origin'][0]<=hi+.2*gap]
        if not inside or any(n['duration'] is None or n['rhythm_evidence'].get('tuplet') for n in inside):
            continue
        direction='down' if y>median(n['origin'][1] for n in inside) else 'up'
        primary=[n for n in inside if n['rhythm_evidence'].get('stem_direction')==direction]
        groups=_event_groups(primary,gap)
        inside_rests=[r for r in rests if lo-.2*gap<=(r['bbox'][0]+r['bbox'][2])/2<=hi+.2*gap]
        rest_group=(bool(inside_rests) and len(groups)+len(inside_rests)==actual
                    and len(primary)==len(inside)
                    and len({e.get('measure') for e in primary+inside_rests})==1
                    and len({e.get('duration') for e in primary+inside_rests})==1
                    and all(r.get('duration') is not None and not r.get('rhythm_evidence',{}).get('tuplet') for r in inside_rests))
        if (len(groups)!=actual and not rest_group) or any(len({n['duration'] for n in g})!=1 for g in groups):
            continue
        # Each primary group must be visibly beamed toward this bracket.
        if any(not all(n['rhythm_evidence'].get('beams',0)>0 for n in g) for g in groups):
            continue
        if any(not n['rhythm_evidence'].get('stem')
               or not 0<((y-n['rhythm_evidence']['stem'][2]) if direction=='down'
                         else (n['rhythm_evidence']['stem'][1]-y))<5*gap for n in primary):
            continue
        primary_total=sum(g[0]['duration'] for g in groups)
        targets=list(primary)
        others=[n for n in inside if n not in primary]
        if rest_group:targets.extend(inside_rests)
        auxiliary=_event_groups(others,gap)
        if not rest_group and all(len({n['duration'] for n in g})==1 for g in auxiliary) and all(r['duration'] is not None for r in inside_rests):
            auxiliary_total=sum(g[0]['duration'] for g in auxiliary)+sum(r['duration'] for r in inside_rests)
            last=max(groups,key=lambda g:g[0]['origin'][0])
            auxiliary_x=[n['origin'][0] for n in others]+[(r['bbox'][0]+r['bbox'][2])/2 for r in inside_rests]
            if (auxiliary_x and max(auxiliary_x)<last[0]['origin'][0]
                    and abs(auxiliary_total+last[0]['duration']-primary_total)<1e-6):
                targets.extend(others);targets.extend(inside_rests)
        for event in targets:
            original=event['duration'];event['duration']=original*normal/actual
            if 'pitch_candidate' in event:
                event['beats']=event['duration']
            else:
                event['duration_beats']=event['duration']
            event['rhythm_evidence']={**event['rhythm_evidence'],'tuplet':{
                'actual':actual,'normal':normal,'nominal_duration_beats':original,
                'marker_bbox':_round_box(box),'bracket':_round_box(spans[0]),
                'method':'explicit_capped_bracket_with_rests' if rest_group else 'explicit_capped_bracket_and_mixed_beamed_voice'}}


def _apply_omitted_tuplet_numbers(notes, rests, staff, lines, meter, meter_evidence,
                                  measure, measure_count, continuations):
    """Continue a demonstrated beam stream, with omitted numbers kept estimated.

    A complete, explicitly numbered single-note measure establishes the ratio.
    Meter sums only validate a matching physical stream; they never choose its
    ratio. Any interruption discards the seed until another printed measure.
    """
    hand=staff.get('hand');prior=continuations.pop(hand,None);gap=staff['gap']
    if (hand not in ('right','left') or staff.get('outside_piano') or not notes or rests
            or meter is None or meter<=0 or not isinstance(meter_evidence,dict)):
        return
    meter_key=((meter_evidence.get('numerator'),meter_evidence.get('denominator'))
               if 'numerator' in meter_evidence else {'common_time':(4,4),'cut_time':(2,2)}.get(meter_evidence.get('symbol')))
    if meter_key is None or None in meter_key:
        return
    blocked={'grace_or_cue_note_requires_review','small_notated_note_requires_review',
             'stem_not_resolved','rhythm_geometry_conflict','flag_anchor_unresolved',
             'beam_attachment_ambiguous','beam_spacing_conflict','ledger_staff_assignment_unresolved',
             'cross_staff_hand_unresolved','cross_staff_beam_voice_requires_review',
             'multiple_voices_require_review','excluded_non_piano_staff'}
    if any(n.get('confirmed') or n.get('reviewed') or n.get('manual_fields') or n.get('excluded')
           or n.get('hand')!=hand or n.get('staff')!=staff['id'] or n.get('measure')!=measure
           or n.get('voice') is not None or blocked.intersection(n.get('issues',[]))
           or not n.get('rhythm_evidence',{}).get('stem')
           or not isinstance(n.get('duration'),(float,int)) or not math.isfinite(n['duration']) or n['duration']<=0
           for n in notes):
        return
    notes=sorted(notes,key=lambda n:n['origin'][0])
    rhythms=[n['rhythm_evidence'] for n in notes]
    if (len({tuple(r['stem']) for r in rhythms})!=len(notes)
            or any(b['origin'][0]-a['origin'][0]<.35*gap for a,b in zip(notes,notes[1:]))
            or len({r.get('beams') for r in rhythms})!=1
            or any(r.get('dots',0) or r.get('flag_bboxes') or r.get('stem_direction') not in ('up','down') for r in rhythms)):
        return
    depth=rhythms[0].get('beams')
    if type(depth) is not int or not 1<=depth<=5:
        return
    # Retain maximal attached beams: secondary beams are subsets, while
    # overlapping independent beams cannot form one unambiguous serial voice.
    physical={}
    for x1,y1,x2,y2,width in lines:
        if not .3*gap<=width<=.9*gap or abs(x2-x1)<gap:
            continue
        lo,hi=sorted((x1,x2));tol=max(.2*gap,width/2+.05*gap)
        indexes=[]
        for index,rhythm in enumerate(rhythms):
            stem=rhythm['stem'];tip=stem[1] if rhythm['stem_direction']=='up' else stem[2]
            if lo-tol<=stem[0]<=hi+tol and abs(y1+(y2-y1)*(stem[0]-x1)/(x2-x1)-tip)<=.6*gap:
                indexes.append(index)
        if len(indexes)>1:
            physical[tuple(indexes)]=set(indexes)
    groups=sorted((key for key,own in physical.items()
                   if not any(own<other for other in physical.values())),key=lambda g:g[0])
    if (not groups or sorted(i for group in groups for i in group)!=list(range(len(notes)))
            or any(list(group)!=list(range(group[0],group[-1]+1)) for group in groups)
            or any(len({rhythms[i]['stem_direction'] for i in group})!=1 for group in groups)):
        return
    position={'page':notes[0]['page'],'system':staff['system'],'staff':staff['id'],
              'measure':measure,'measure_count':measure_count}
    tuplets=[r.get('tuplet') for r in rhythms]
    printed_methods={'printed_number_and_exact_beamed_group','unique_marked_beam_prefix_with_nominal_tail'}
    explicit=all(isinstance(t,dict) and t.get('method') in printed_methods
                 and t.get('marker_bbox') and not t.get('estimated') for t in tuplets)
    if explicit:
        signatures={(t.get('actual'),t.get('normal'),t.get('nominal_duration_beats')) for t in tuplets}
        if len(signatures)!=1:
            return
        actual,normal,nominal=next(iter(signatures))
        if (type(actual) is not int or type(normal) is not int or not 1<normal<actual
                or nominal!=2.0**(-depth) or any(len(g)%actual for g in groups)
                or any(abs(n['duration']-nominal*normal/actual)>1e-8 for n in notes)
                or abs(sum(n['duration'] for n in notes)-meter)>1e-8):
            return
        source={**position,'actual':actual,'normal':normal,'nominal_duration_beats':nominal,
                'beam_depth':depth,'beam_stem_counts':sorted({len(g) for g in groups}),
                'stem_directions':sorted({r['stem_direction'] for r in rhythms}),
                'marker_bboxes':[list(box) for box in sorted({tuple(t['marker_bbox']) for t in tuplets})],
                'printed_methods':sorted({t['method'] for t in tuplets}),
                'meter_evidence':meter_evidence}
        continuations[hand]={'actual':actual,'normal':normal,'nominal':nominal,'depth':depth,
            'meter_key':meter_key,'meter':meter,'source':source,'last':position,
            'group_counts':set(source['beam_stem_counts'])|{actual}}
        return
    # Mixed numbered/unmarked bars and bars already complete at nominal
    # values end the passage, even if some subset could be made to fit.
    if any(tuplets) or prior is None or abs(sum(n['duration'] for n in notes)-meter)<1e-8:
        return
    last=prior['last']
    adjacent=((last['staff']==position['staff'] and measure==last['measure']+1)
              or (last['measure']==last['measure_count'] and measure==1
                  and ((position['page']==last['page'] and position['system']==last['system']+1)
                       or (position['page']==last['page']+1 and position['system']==1))))
    if (not adjacent or prior['meter_key']!=meter_key or prior['meter']!=meter
            or prior['depth']!=depth or any(n['duration']!=prior['nominal'] for n in notes)
            or any(len(g) not in prior['group_counts'] for g in groups)
            or abs(sum(n['duration'] for n in notes)*prior['normal']/prior['actual']-meter)>1e-8):
        return
    sizes={i:len(group) for group in groups for i in group}
    anchor=notes[0]['id']
    for index,note in enumerate(notes):
        nominal=note['duration'];note['duration']=note['beats']=nominal*prior['normal']/prior['actual']
        note.update(duration_estimated=True,timing_estimated=True,timing_source_id=anchor)
        note['rhythm_evidence']={**note['rhythm_evidence'],'tuplet':{
            'actual':prior['actual'],'normal':prior['normal'],'nominal_duration_beats':nominal,
            'method':'prior_explicit_tuplet_matching_complete_beam_stream','estimated':True,
            'source_printed_tuplet':prior['source'],'beam_depth':depth,'beam_stem_count':sizes[index],
            'stem_direction':note['rhythm_evidence']['stem_direction'],'continuation_anchor_id':anchor}}
    prior['last']=position
    continuations[hand]=prior


def _finger_music_distance(y, head_y, rhythm):
    """Finger numbers sit beyond noteheads or their beam/stem envelope."""
    stem=rhythm.get('stem')
    low=min(head_y,stem[1]) if stem else head_y
    high=max(head_y,stem[2]) if stem else head_y
    return max(low-y,y-high,0)


def _finger_stem_attachment(digit, head_x, rhythm, gap):
    """Visible glyph distance beyond a horizontally aligned free stem end."""
    stem=rhythm.get('stem')
    if stem is None or abs(digit['x']-head_x)>=.35*gap:
        return None
    if rhythm.get('stem_direction')=='up':
        distance=stem[1]-digit['bbox'][3]
    elif rhythm.get('stem_direction')=='down':
        distance=digit['bbox'][1]-stem[2]
    else:
        return None
    return distance if 0<distance<2*gap else None


def _reconcile_complete_finger_columns(jobs, chars, used):
    """Repair a chord/single collision without taking another note's digit."""
    boxes={tuple(_round_box(c['bbox'])):i for i,c in enumerate(chars) if c['char'] in DIGITS}
    events=[event for _,group,_ in jobs for event in group]
    def owners():
        return {boxes[tuple(event['finger_bbox'])]:event for event in events
                if event.get('finger_bbox') and tuple(event['finger_bbox']) in boxes}
    def reset(group):
        for event in group:
            event.update(finger=None,finger_source=None,finger_candidates=[],confidence=.85)
            event.pop('finger_bbox',None);event.pop('finger_evidence',None)
            event['issues']=[issue for issue in event['issues'] if issue not in (
                'fingering_missing_or_ambiguous','right_fingering_below_requires_review',
                'chord_fingering_order_requires_review')]
    for staff,group,_ in jobs:
        stems={tuple(e['rhythm_evidence']['stem']) for e in group if e['rhythm_evidence'].get('stem')}
        if len(group)<2 or len(stems)!=1 or not all(e.get('finger') for e in group):
            continue
        gap=staff['gap'];x=median(e['origin'][0] for e in group);owned=owners()
        original={index for index,event in owned.items() if any(event is e for e in group)}
        column=sorted(((i,c) for i,c in enumerate(chars) if c['char'] in DIGITS and DIGITS[c['char']]<=5
                       and c['size']<1.7*gap and abs(c['x']-x)<.35*gap
                       and (i not in owned or i in original)),key=lambda item:item[1]['y'])
        runs=[]
        for item in column:
            if not runs or not .8*gap<item[1]['y']-runs[-1][-1][1]['y']<1.8*gap:
                runs.append([])
            runs[-1].append(item)
        for run in runs:
            if len(run)!=len(group) or len({DIGITS[c['char']] for _,c in run})!=len(group):
                continue
            spacings=[b[1]['y']-a[1]['y'] for a,b in zip(run,run[1:])]
            if max(spacings)-min(spacings)>.3*gap or any(a[1]['bbox'][3]>b[1]['bbox'][1] for a,b in zip(run,run[1:])):
                continue
            if not any(_finger_stem_attachment(c,x,e['rhythm_evidence'],gap) is not None for _,c in run for e in group):
                continue
            selected={i for i,_ in run};released=original-selected
            if not released or not selected-original:
                continue
            transfers=[]
            for index in released:
                digit=chars[index]
                targets=[(single_staff,single) for single_staff,single,_ in jobs
                         if len(single)==1 and not single[0].get('finger')
                         and _finger_stem_attachment(digit,single[0]['origin'][0],single[0]['rhythm_evidence'],single_staff['gap']) is not None]
                if len(targets)!=1:
                    break
                transfers.append((index,targets[0]))
            else:
                if len({target[1][0]['id'] for _,target in transfers})!=len(transfers):
                    continue
                reset(group);used.difference_update(original)
                _assign_printed_finger_group(group,run,gap,used)
                for index,(single_staff,single) in transfers:
                    reset(single)
                    _assign_printed_finger_group(single,[(index,chars[index])],single_staff['gap'],used)
                break


def _finger_glyph_music_distance(digit, head_y, rhythm, head_bbox=None):
    stem=rhythm.get('stem')
    low=head_bbox[1] if head_bbox else head_y
    high=head_bbox[3] if head_bbox else head_y
    if stem:
        low=min(low,stem[1]);high=max(high,stem[2])
    return max(low-digit['bbox'][3],digit['bbox'][1]-high,0)


def _recover_unclaimed_stem_fingers(jobs, staves, chars, used, head_rhythms):
    """Recover a visible free-stem label without taking any allocated digit."""
    # 11-05：另一行里已经有完整指法的音不再跟这个单音抢数字（它自己那列已经分好了）
    fingered=[(e['origin'][0],e['origin'][1]) for _,g,_ in jobs for e in g if type(e.get('finger')) is int]
    def settled(head):
        return any(abs(head['x']-x)<1 and abs(head['y']-y)<1 for x,y in fingered)
    for staff,group,groups in jobs:
        if len(group)!=1 or group[0].get('finger'):
            continue
        event=group[0];gap=staff['gap'];x=event['origin'][0]
        candidates=[]
        for index,digit in enumerate(chars):
            if (index in used or digit['char'] not in DIGITS or DIGITS[digit['char']]>5
                    or digit['size']>=1.7*gap
                    or _finger_stem_attachment(digit,x,event['rhythm_evidence'],gap) is None):
                continue
            if any(other is not group and other and other[0]['hand']==event['hand']
                   and abs(digit['x']-median(e['origin'][0] for e in other))+.35*gap<abs(digit['x']-x)
                   for other in groups):
                continue
            own=_finger_glyph_music_distance(digit,event['origin'][1],event['rhythm_evidence'],event.get('glyph_bbox'))
            if any(own+.5*gap>=_finger_glyph_music_distance(digit,head['y'],head_rhythms[id(head)][1],head.get('bbox'))
                   for other in staves if other is not staff for head in other['heads']
                   if abs(head['x']-digit['x'])<1.5*gap and not settled(head)):
                continue
            candidates.append((index,digit))
        if len(candidates)!=1:
            continue
        event['issues']=[issue for issue in event['issues'] if issue not in (
            'fingering_missing_or_ambiguous','right_fingering_below_requires_review',
            'chord_fingering_order_requires_review')]
        event.update(finger_candidates=[],confidence=.85)
        _assign_printed_finger_group(group,candidates,gap,used)


def _borrow_interstaff_chord_fingers(jobs, staves, chars, used, head_rhythms):
    """11-05 用户：和弦没印到的音，指法常印在高音谱下方（两行谱之间）。
    对照下面左手谱：那个位置左手的音已经有自己的指法（或没有音），
    这个数字就是右手和弦的；补完要满足“音越高手指号越大”且不重复。"""
    fingered=[(e['origin'][0],e['origin'][1]) for _,g,_ in jobs for e in g if type(e.get('finger')) is int]
    def settled(head):
        return any(abs(head['x']-x)<1 and abs(head['y']-y)<1 for x,y in fingered)
    for staff,group,groups in jobs:
        missing=[e for e in group if e.get('finger') is None]
        if not missing or group[0]['hand']!='right':
            continue
        gap=staff['gap'];x=median(e['origin'][0] for e in group)
        if 'bottom' not in staff:
            continue
        below=[o for o in staves if o is not staff and 'top' in o and o['top']>staff['bottom'] and o['top']-staff['bottom']<14*gap]
        if not below:
            continue
        lower=min(below,key=lambda o:o['top'])
        low_y=max(max(e['origin'][1] for e in group),staff['bottom'])
        def free(c):
            return c['char'] in DIGITS and 1<=DIGITS[c['char']]<=5 and c['size']<1.7*gap and abs(c['x']-x)<.45*gap
        column=sorted(((n,c) for n,c in enumerate(chars) if n not in used and free(c)
                       and low_y+.3*gap<c['y']<lower['top']-.2*gap),key=lambda nc:nc[1]['y'])
        if not column:
            continue
        # 左手那一列：附近的音都已有指法才算“这个数字不是左手的”
        left=[h for h in lower['heads'] if abs(h['x']-x)<1.2*gap]
        if any(not settled(h) for h in left):
            continue
        # 只取紧挨高音谱的那一段（连续一列）
        run=[column[0]]
        for item in column[1:]:
            if item[1]['y']-run[-1][1]['y']<1.8*gap:
                run.append(item)
        # 上面印的那一段（和弦上方，离最高的音或符干顶不远）
        top=min(e['origin'][1] for e in group)
        for e in group:
            stem=e['rhythm_evidence'].get('stem')
            if stem and e['rhythm_evidence'].get('stem_direction')=='up':
                top=min(top,*stem[1:])
        over=sorted(((n,c) for n,c in enumerate(chars) if n not in used and free(c)
                     and c['y']<min(e['origin'][1] for e in group)-.3*gap and top-c['y']<8*gap),key=lambda nc:-nc[1]['y'])
        above=[]
        for item in over:
            if (not above and top-item[1]['y']<2.6*gap) or (above and above[-1][1]['y']-item[1]['y']<1.8*gap):
                above.append(item)
            elif above:
                break
        # 11-05：只差一个数字时，最上面那个隔得稍远（≤3 倍线距）也算这一列的
        if above and len(above)+len(run)==len(missing)-1:
            rest=[item for item in over if item[1]['y']<above[-1][1]['y']]
            if rest and above[-1][1]['y']-rest[0][1]['y']<3*gap:
                above.append(rest[0])
        above=sorted(above,key=lambda nc:nc[1]['y'])
        exact=len(above)+len(run)==len(missing)  # 11-05 用户：谱上印了几个就照着给（从上到下），不因顺序怪就放弃
        if len(above)+len(run)!=len(missing):
            above=[]
            run=run[:len(missing)]
            if len(run)!=len(missing):
                continue
        trial={id(e):e['finger'] for e in group}
        pairs=list(zip(sorted(missing,key=lambda e:e['origin'][1]),above+run))
        for event,(n,c) in pairs:
            trial[id(event)]=DIGITS[c['char']]
        ordered=[trial[id(e)] for e in sorted(group,key=lambda e:-e['origin'][1])]  # 从低音到高音
        if any(f is None for f in ordered) or (not exact and any(b<=a for a,b in zip(ordered,ordered[1:]))):
            continue
        for event,(n,c) in pairs:
            event.update(finger=DIGITS[c['char']],finger_source='printed',finger_bbox=_round_box(c['bbox']),
                         finger_candidates=[],confidence=.8)
            event['finger_evidence']={'method':'interstaff_column_left_hand_settled','position':'below' if c['y']>low_y else 'above'}
            event['issues']=[i for i in event['issues'] if i not in (
                'fingering_missing_or_ambiguous','chord_fingering_order_requires_review')]
            used.add(n);fingered.append((event['origin'][0],event['origin'][1]))


def _printed_finger_candidates(group, groups, staff, staves, chars, used, head_rhythms):
    gap=staff['gap'];x=median(e['origin'][0] for e in group)
    anchored_stack=set()
    shared_stems={tuple(e['rhythm_evidence']['stem']) for e in group if e['rhythm_evidence'].get('stem')}
    if (len(group)>1 and len(shared_stems)<=1
            and (not shared_stems or all(e['rhythm_evidence'].get('stem') for e in group))):
        # A complete column may sit beside the heads, or beyond the free stem
        # end. Whole-note chords have only their head envelope to anchor it.
        extent=[e['origin'][1] for e in group]
        if shared_stems:
            extent.extend(next(iter(shared_stems))[1:])
        low,high=min(extent),max(extent)
        column=sorted(((n,c) for n,c in enumerate(chars) if n not in used and c['char'] in DIGITS
                       and DIGITS[c['char']]<=5 and c['size']<1.7*gap and abs(c['x']-x)<.35*gap),
                      key=lambda nc:nc[1]['y'])
        runs=[]
        for item in column:
            if not runs or not .8*gap<item[1]['y']-runs[-1][-1][1]['y']<1.8*gap:
                runs.append([])
            runs[-1].append(item)
        for run in runs:
            if len(run)!=len(group) or len({DIGITS[c['char']] for _,c in run})!=len(group):
                continue
            spacings=[b[1]['y']-a[1]['y'] for a,b in zip(run,run[1:])]
            # Separate hand labels can nearly touch in the inter-staff gap.
            # A cramped pair followed by normal line spacing is not one column.
            if max(spacings)-min(spacings)>.3*gap:
                continue
            if run[-1][1]['y']<low:
                anchor=run[-1][1];distance=low-anchor['y']
            elif run[0][1]['y']>high:
                anchor=run[0][1];distance=anchor['y']-high
            else:
                continue
            if not 0<distance<2*gap:
                continue
            # Establish ownership at the digit beside this music envelope first.
            # The remaining aligned digits form this chord's complete column,
            # even if its far end approaches music on the preceding system.
            if any(other is not staff and abs(h['x']-anchor['x'])<1.5*gap
                   and _finger_music_distance(anchor['y'],h['y'],head_rhythms[id(h)][1])+.5*gap<distance
                   for other in staves for h in other['heads']):
                continue
            anchored_stack.update(n for n,_ in run)
    candidates=[]
    for n,c in enumerate(chars):
        if (n in used or c['char'] not in DIGITS or DIGITS[c['char']]>5 or c['size']>=1.7*gap
                or abs(c['x']-x)>=1.5*gap):
            continue
        # The nearest printed column owns its digits. Do not consume the next
        # note's fingering just because it is vertically closer to this head.
        if any(other is not group and other and other[0]['hand']==group[0]['hand']
               and abs(c['x']-median(e['origin'][0] for e in other))+.35*gap<abs(c['x']-x)
               for other in groups):
            continue
        own=min(_finger_music_distance(c['y'],e['origin'][1],e['rhythm_evidence']) for e in group)
        if own>=9*gap:
            continue
        beam_anchored=any(e['rhythm_evidence'].get('beams',0)>0
            and abs(c['x']-e['origin'][0])<.35*gap
            and e['rhythm_evidence'].get('stem')
            # 11-05：量数字靠近符干那一边（向下符干量数字上沿），不量底边——幻想圆舞曲的“2”差 0.2 像素没算上
            and ((e['rhythm_evidence'].get('stem_direction')=='up'
                  and 0<e['rhythm_evidence']['stem'][1]-c.get('bbox',(0,0,0,c['y']))[3]<2*gap)
                 or (e['rhythm_evidence'].get('stem_direction')=='down'
                     and 0<c.get('bbox',(0,c['y']))[1]-e['rhythm_evidence']['stem'][2]<2*gap)) for e in group)
        # Use the complete printed stem envelope: low bass notes can have
        # long upward stems, with their own fingering well above the heads.
        if n not in anchored_stack and any(other is not staff and abs(h['x']-c['x'])<1.5*gap
               and (_finger_music_distance(c['y'],h['y'],head_rhythms[id(h)][1])+.5*gap<own
                    or (abs(h['y']-c['y'])+.5*gap<min(abs(e['origin'][1]-c['y']) for e in group)
                        # A digit directly above/below this column's free beam
                        # belongs to it when the other music is farther away;
                        # a low head must not lose its own long-stem label to
                        # an unrelated head on the preceding printed system.
                        and not (beam_anchored and own+.5*gap<
                                 _finger_music_distance(c['y'],h['y'],head_rhythms[id(h)][1]))))
               for other in staves for h in other['heads']):
            continue
        candidates.append((n,c))
    # 11-05：和弦下面（或上面）有一整列正好够数的数字时，只从这一列里挑；
    # 不然会把旁边另一只手单音的指法抢来（幻想圆舞曲：左手 1-2-3 抢了右手的 2，成了 1-2-2）
    if len(group)>1:
        def mine(c):
            own=min(_finger_music_distance(c['y'],e['origin'][1],e['rhythm_evidence']) for e in group)
            return not any(other is not staff and abs(h['x']-c['x'])<1.5*gap
                           and _finger_music_distance(c['y'],h['y'],head_rhythms[id(h)][1])<=own
                           for other in staves for h in other['heads'])
        column=[item for item in candidates if item[0] in anchored_stack and mine(item[1])]
        if len(column)>=len(group):
            candidates=column
    if (group[0]['hand']=='right'
            or all(e['rhythm_evidence'].get('stem_direction')=='up' for e in group)):
        above=[item for item in candidates if item[1]['y']<min(e['origin'][1] for e in group)-.3*gap]
        if len(above)>=len(group):
            candidates=above
    return sorted(candidates,key=lambda nc:(min(abs(nc[1]['y']-e['origin'][1]) for e in group),abs(nc[1]['x']-x)))


def _assign_printed_finger_group(group, candidates, gap, used):
    selected=candidates[:len(group)]
    pairs=[]
    if len(selected)==len(group):
        pairs=list(zip(sorted(group,key=lambda e:e['origin'][1]),sorted(selected,key=lambda nc:nc[1]['y'])))
    elif len(candidates)==1 and len(group)>1:
        digit=candidates[0][1]
        nearest=sorted(group,key=lambda e:abs(e['origin'][1]-digit['y']))
        distances=[abs(e['origin'][1]-digit['y']) for e in nearest]
        if distances[1]-distances[0]>.3*gap:
            pairs=[(nearest[0],candidates[0])]
    assigned=set()
    for event,(index,digit) in pairs:
        event.update(finger=DIGITS[digit['char']],finger_source='printed',finger_bbox=_round_box(digit['bbox']))
        event['finger_evidence']={'method':'printed_column_and_music_extent',
            'position':'above' if digit['y']<min(e['origin'][1] for e in group)-.3*gap else 'below'}
        if len(pairs)<len(group):
            event['finger_evidence']['partial_chord']=True
        used.add(index);assigned.add(event['id'])
        if event['hand']=='right' and digit['y']>=min(e['origin'][1] for e in group)-.3*gap:
            event['issues'].append('right_fingering_below_requires_review')
        if len(group)>1:
            event['issues'].append('chord_fingering_order_requires_review')
    for event in group:
        if event['id'] not in assigned:
            event['issues'].append('fingering_missing_or_ambiguous')
            event['finger_candidates']=[DIGITS[c['char']] for _,c in candidates]


def _source_fingering_states(jobs, staves, chars, head_rhythms, text_chars=()):
    """Describe printed-label absence separately from an unresolved assignment.

    An unallocated plausible digit is evidence of ambiguity, not evidence that
    the source omitted fingering. Digits already assigned to another head are
    not borrowed to fill this head. This annotation never changes musical data.
    """
    owned={tuple(event['finger_bbox']) for _,group,_ in jobs for event in group
           if event.get('finger_bbox') and type(event.get('finger')) is int and 1<=event['finger']<=5}
    rhythmic_numbers={tuple(_round_box(event['rhythm_evidence']['tuplet']['marker_bbox']))
                      for _,group,_ in jobs for event in group
                      if isinstance(event.get('rhythm_evidence',{}).get('tuplet'),dict)
                      and event['rhythm_evidence']['tuplet'].get('marker_bbox')}
    assigned_or_rhythmic=owned|rhythmic_numbers
    other_digits=[c for c in text_chars if c['char'] in '123456789' and c.get('font')!='Aloisen']
    other_digits += [c for c in chars if c['char'] in DIGITS and DIGITS[c['char']]>5]
    other_digits=[c for c in other_digits if tuple(_round_box(c['bbox'])) not in rhythmic_numbers]
    for staff,group,groups in jobs:
        missing=[event for event in group if not (type(event.get('finger')) is int and 1<=event['finger']<=5)]
        if missing:
            candidates=_printed_finger_candidates(group,groups,staff,staves,chars,set(),head_rhythms)
            unclaimed=[digit for _,digit in candidates
                       if tuple(_round_box(digit['bbox'])) not in assigned_or_rhythmic]
        else:
            unclaimed=[]
        for event in group:
            if type(event.get('finger')) is int and 1<=event['finger']<=5:
                event['source_fingering_state']='printed'
                event['source_fingering_evidence']={'method':'assigned_original_digit','bbox':event.get('finger_bbox')}
                continue
            gap=staff['gap'];x=event['origin'][0]
            # A small plain-text digit, or an invalid finger number, may be a
            # visible label that this music-font recognizer cannot yet assign.
            # Keep it for review rather than declaring that no label was printed.
            nearby=[c for c in other_digits if c['size']<1.7*gap and abs(c['x']-x)<.35*gap
                    and _finger_glyph_music_distance(c,event['origin'][1],event['rhythm_evidence'],event.get('glyph_bbox'))<2*gap]
            uncertain=unclaimed+nearby
            event['source_fingering_state']='unresolved' if uncertain else 'unmarked'
            event['source_fingering_evidence']={'method':'unassigned_visible_digit' if uncertain else 'no_unassigned_digit_in_column',
                'candidate_bboxes':[_round_box(c['bbox']) for c in uncertain]}


def _protect_unowned_partial_chord_finger_evidence(jobs,chars):
    """An unowned label beside a chord is uncertainty, never proven absence.

    A different staff's stem envelope can reject a digit for assignment while
    still not prove that the digit belongs to that staff. When that other
    note already has its own printed finger, retain a nearby chord-head label
    as a visible unresolved candidate. No finger value is assigned or moved.
    """
    events=[e for _,group,_ in jobs for e in group]
    owned={tuple(_round_box(e['finger_bbox'])) for e in events if e.get('finger_bbox')
           and type(e.get('finger')) is int and 1<=e['finger']<=5}
    rhythmic={tuple(_round_box(e['rhythm_evidence']['tuplet']['marker_bbox'])) for e in events
              if isinstance(e.get('rhythm_evidence',{}).get('tuplet'),dict)
              and e['rhythm_evidence']['tuplet'].get('marker_bbox')}
    digits=[c for c in chars if c.get('char') in DIGITS and 1<=DIGITS[c['char']]<=5 and c.get('bbox')
            and tuple(_round_box(c['bbox'])) not in owned|rhythmic]
    marked=0
    for staff,group,_ in jobs:
        if len(group)<2:continue
        gap=staff['gap'];stems={tuple(e['rhythm_evidence']['stem']) for e in group if e.get('rhythm_evidence',{}).get('stem')}
        if len(stems)!=1 or not all(e.get('rhythm_evidence',{}).get('stem') for e in group):continue
        candidates={}
        for digit in digits:
            if digit.get('size',0)>=1.7*gap:continue
            distances=[]
            for event in group:
                box=event.get('glyph_bbox') or event.get('bbox')
                if not box or abs(digit['x']-event['origin'][0])>=.35*gap:continue
                distance=max(box[1]-digit['bbox'][3],digit['bbox'][1]-box[3],0)
                distances.append((distance,event))
            distances.sort(key=lambda row:row[0])
            if (len(distances)<2 or not 0<distances[0][0]<2*gap
                    or distances[1][0]-distances[0][0]<=.3*gap):continue
            own,event=distances[0]
            if (event.get('excluded') or event.get('confirmed') or 'finger' in event.get('manual_fields',[])
                    or event.get('finger') is not None or event.get('source_fingering_state')!='unmarked'):continue
            competing=[other for other in events if other.get('staff')!=event.get('staff') and other.get('page')==event.get('page')
                and other.get('system')==event.get('system') and not other.get('excluded')
                and other.get('finger_source')=='printed' and type(other.get('finger')) is int and 1<=other['finger']<=5
                and other.get('finger_bbox') and abs(other['origin'][0]-digit['x'])<1.5*gap
                and _finger_glyph_music_distance(digit,other['origin'][1],other['rhythm_evidence'],other.get('glyph_bbox'))<=own]
            if not competing:continue
            proof=candidates.setdefault(event['id'],dict(event=event,digits=[],competing_ids=[]))
            if digit not in proof['digits']:proof['digits'].append(digit)
            proof['competing_ids'].extend(other['id'] for other in competing)
        for proof in candidates.values():
            event=proof['event'];digits=proof['digits']
            event['source_fingering_state']='unresolved'
            event['source_fingering_evidence']=dict(method='unowned_partial_chord_digit_with_cross_staff_music_competition',
                candidate_bboxes=[_round_box(c['bbox']) for c in digits],candidate_values=sorted({DIGITS[c['char']] for c in digits}),
                competing_event_ids=list(dict.fromkeys(proof['competing_ids'])))
            event['finger_candidates']=sorted(set(event.get('finger_candidates',[]))|{DIGITS[c['char']] for c in digits})
            if 'fingering_missing_or_ambiguous' not in event.get('issues',[]):event.setdefault('issues',[]).append('fingering_missing_or_ambiguous')
            marked+=1
    return marked


def _disambiguate_foreign_free_stem_digits(jobs,chars,lines):
    """A digit inside this beam may be a label outside another staff's stem.

    This only resolves the source absence/uncertainty state. It never assigns
    the digit to the other hand or changes any printed/manual finger value.
    """
    from recognizer_geometry import digit_overlaps_attached_beam
    events=[e for _,group,_ in jobs for e in group];changes=0
    for staff,group,_ in jobs:
        gap=staff['gap']
        for event in group:
            evidence=event.get('source_fingering_evidence',{})
            if (event.get('finger') is not None or event.get('confirmed') or event.get('excluded') or 'finger' in event.get('manual_fields',[])
                    or event.get('source_fingering_state')!='unresolved' or evidence.get('method')!='digit_overlaps_attached_music_beam'):continue
            candidates=evidence.get('candidate_bboxes',[]);kept=[];removed=[];removed_values=set()
            for bbox in candidates:
                matches=[c for c in chars if c.get('char') in DIGITS and 1<=DIGITS[c['char']]<=5 and c.get('bbox')
                         and _round_box(c['bbox'])==list(bbox) and c.get('size',0)<1.7*gap]
                if len(matches)!=1:kept.append(bbox);continue
                digit=matches[0]
                if (_finger_stem_attachment(digit,event['origin'][0],event['rhythm_evidence'],gap) is not None
                        or not digit_overlaps_attached_beam(digit,[event],gap,lines)):
                    kept.append(bbox);continue
                owners={}
                for other in events:
                    if (other.get('staff')==event.get('staff') or other.get('page')!=event.get('page') or other.get('system')!=event.get('system')
                            or other.get('excluded') or _finger_stem_attachment(digit,other['origin'][0],other['rhythm_evidence'],gap) is None):continue
                    stem=other['rhythm_evidence'].get('stem')
                    physical=any(abs(l[0]-l[2])<.04*gap and 0<l[4]<.25*gap and abs(l[0]-stem[0])<.05*gap
                                 and abs(min(l[1],l[3])-stem[1])<.05*gap and abs(max(l[1],l[3])-stem[2])<.05*gap for l in lines)
                    if physical:owners.setdefault((other['staff'],tuple(stem)),[]).append(other['id'])
                if len(owners)!=1:kept.append(bbox);continue
                owner,ids=next(iter(owners.items()));removed_values.add(DIGITS[digit['char']])
                removed.append(dict(bbox=list(bbox),value=DIGITS[digit['char']],owner_staff=owner[0],physical_stem=list(owner[1]),owner_note_ids=ids))
            if not removed:continue
            event['source_fingering_state']='unresolved' if kept else 'unmarked'
            event['source_fingering_evidence']=dict(method='visible_digit_proved_other_staff_free_stem_label',candidate_bboxes=kept,
                                                  foreign_free_stem_digit_evidence=removed)
            event['finger_candidates']=[v for v in event.get('finger_candidates',[]) if v not in removed_values]
            changes+=1
    return changes


def _assign_page_fingerings(jobs, staves, chars, head_rhythms, text_chars=()):
    """Reserve complete printed chord columns before nearby single notes."""
    used=set();pending=[]
    # All staff geometry is present before any digit is consumed. A complete
    # vertical chord column must not lose its top digit to the previous system.
    for staff,group,groups in sorted(jobs,key=lambda job:-len(job[1])):
        candidates=_printed_finger_candidates(group,groups,staff,staves,chars,used,head_rhythms)
        if len(group)>1 and len(candidates)>=len(group):
            _assign_printed_finger_group(group,candidates,staff['gap'],used)
        else:
            pending.append((staff,group,groups))
    for staff,group,groups in pending:
        candidates=_printed_finger_candidates(group,groups,staff,staves,chars,used,head_rhythms)
        _assign_printed_finger_group(group,candidates,staff['gap'],used)
    _reconcile_complete_finger_columns(jobs,chars,used)
    _recover_unclaimed_stem_fingers(jobs,staves,chars,used,head_rhythms)
    _borrow_interstaff_chord_fingers(jobs,staves,chars,used,head_rhythms)
    _source_fingering_states(jobs,staves,chars,head_rhythms,text_chars)
    for _,group,_ in jobs:
        for event in group:
            if event['issues']:
                event['confidence']=.55 if event['finger'] else .35


def _apply_printed_hand_labels(events, staff, text_chars):
    """A local L.H./R.H. instruction overrides staff ownership for its chord."""
    gap=staff['gap'];groups=_event_groups(events,gap)
    for first in text_chars:
        if first.get('font')=='Aloisen' or first['char'].upper() not in ('L','R'):
            continue
        row=sorted((c for c in text_chars if c.get('font')!='Aloisen'
                    and first['x']<=c['x']<first['x']+4*first['size']
                    and abs(c['y']-first['y'])<.3*first['size']),key=lambda c:c['x'])
        text=''.join(c['char'] for c in row)
        match=re.match(r'([LR])\s*\.\s*H\s*\.?',text,re.IGNORECASE)
        if match is None:
            continue
        glyphs=row[:len(match[0])]
        center=(glyphs[0]['bbox'][0]+glyphs[-1]['bbox'][2])/2
        candidates=[g for g in groups if abs(median(n['origin'][0] for n in g)-center)<1.5*gap
                    and 0<min(n['origin'][1] for n in g)-first['y']<6*gap]
        if not candidates:
            continue
        group=min(candidates,key=lambda g:abs(median(n['origin'][0] for n in g)-center)
                  +.2*abs(min(n['origin'][1] for n in g)-first['y']))
        # In opposed voices at the same column the upper chord bears the label.
        directions={n['rhythm_evidence'].get('stem_direction') for n in group}
        if directions=={'up','down'}:
            group=[n for n in group if n['rhythm_evidence'].get('stem_direction')=='up']
        hand='left' if match[1].upper()=='L' else 'right'
        box=_round_box([min(c['bbox'][0] for c in glyphs),min(c['bbox'][1] for c in glyphs),
                        max(c['bbox'][2] for c in glyphs),max(c['bbox'][3] for c in glyphs)])
        for note in group:
            note['hand']=hand
            note['hand_evidence']={'method':'explicit_printed_hand_label','label':match[0],'bbox':box}


def _shared_staff_hands(events, gap, other_heads=()):
    """Separate two explicit voices where the paired staff is vacant.

    Used only when the other piano staff has no rests. Each selected column has
    an upper, upward-stem voice and a lower, downward-stem voice, and no note on
    the paired staff. A melody changing stem direction does not establish hands.
    """
    groups=[]
    for group in _event_groups(events,gap):
        if len(group)!=2:
            continue
        upper,lower=sorted(group,key=lambda e:e['origin'][1])
        if (upper['rhythm_evidence'].get('stem_direction')!='up'
                or lower['rhythm_evidence'].get('stem_direction')!='down'
                or lower['origin'][1]-upper['origin'][1]<.5*gap
                or any(abs(h['x']-upper['origin'][0])<.7*gap for h in other_heads)):
            continue
        groups.append(group)
    if len(groups)<2:
        return False
    for group in groups:
        for event,hand in zip(sorted(group,key=lambda e:e['origin'][1]),('right','left')):
            event['hand']=hand
            event['hand_evidence']={'method':'vacant_paired_staff_explicit_opposed_voices',
                                    'voice':event['rhythm_evidence']['stem_direction']}
            event['issues']=[issue for issue in event['issues'] if issue!='cross_staff_hand_unresolved']
            event['issues'].append('shared_staff_hand_assignment_requires_review')
    return True


def _align_shared_staff_onsets(staves, events):
    """Use a complete paired voice to anchor physically aligned note columns."""
    by_id={staff['id']:staff for staff in staves}
    for staff in staves:
        gap=staff['gap']
        for event in events:
            if (event['staff']!=staff['id'] or event['measure_beat'] is not None or event['duration'] is None
                    or 'grace_or_cue_note_requires_review' in event['issues'] or event.get('excluded')):
                continue
            def same_boundaries(other):
                other_staff=by_id.get(other['staff'])
                if not other_staff or other.get('excluded'):
                    return False
                lo=event['measure']-1
                a=staff.get('bars',[])[lo:lo+2];b=other_staff.get('bars',[])[lo:lo+2]
                return len(a)==len(b)==2 and all(abs(x-y)<.3*gap for x,y in zip(a,b))
            anchors=[other for other in events if other['staff']!=event['staff']
                and other['measure']==event['measure'] and other['measure_beat'] is not None
                and abs(other['origin'][0]-event['origin'][0])<.35*gap
                and same_boundaries(other)
                and any(s['id']==other['staff'] and any(m['measure']==other['measure'] and m['timing_resolved']
                    for m in s.get('measures',[])) for s in staves)]
            positions={a['measure_beat'] for a in anchors}
            if len(positions)!=1:
                continue
            event['measure_beat']=next(iter(positions))
            event['onset_evidence']={'method':'aligned_to_paired_complete_voice','anchor_ids':[a['id'] for a in anchors]}
            event['issues']=[i for i in event['issues'] if i!='measure_timing_unresolved']
            event['issues'].append('paired_staff_onset_requires_review')


def _propagate_beamed_onsets(staves, events, lines):
    """Intervening attacks on the same printed beam follow known durations."""
    for staff in staves:
        gap=staff['gap']
        notes=[n for n in events if n['staff']==staff['id'] and 'pitch_candidate' in n
               and n['duration'] is not None and n['rhythm_evidence'].get('stem')
               and n['rhythm_evidence'].get('beams',0)>0
               and 'grace_or_cue_note_requires_review' not in n['issues']]
        stems={}
        for note in notes:
            stems.setdefault((note['measure'],tuple(note['rhythm_evidence']['stem'])),[]).append(note)
        edges=[]
        for x1,y1,x2,y2,width in lines:
            if not .3*gap<=width<=.9*gap or abs(x2-x1)<gap:
                continue
            slope=(y2-y1)/(x2-x1)
            attached=[]
            for (measure,stem),group in stems.items():
                end_tolerance=max(.2*gap,width/2+.05*gap)
                if not min(x1,x2)-end_tolerance<=stem[0]<=max(x1,x2)+end_tolerance:
                    continue
                y=y1+slope*(stem[0]-x1)
                head_y=median(n['origin'][1] for n in group)
                tip=stem[1] if abs(head_y-stem[1])>abs(head_y-stem[2]) else stem[2]
                if abs(y-tip)<.6*gap:
                    attached.append((measure,stem[0],group))
            attached.sort(key=lambda item:(item[0],item[1]))
            for left,right in zip(attached,attached[1:]):
                if left[0]!=right[0] or right[1]-left[1]<.35*gap:
                    continue
                durations={n['duration'] for n in left[2]}
                if len(durations)==1:
                    edges.append((left[2],right[2],next(iter(durations))))
        groups={};graph={}
        for left,right,duration in edges:
            a=tuple(n['id'] for n in left);b=tuple(n['id'] for n in right)
            groups[a]=left;groups[b]=right
            graph.setdefault(a,[]).append((b,duration));graph.setdefault(b,[]).append((a,-duration))
        visited=set()
        for start in graph:
            if start in visited:
                continue
            relative={start:0.0};queue=[start];consistent=True
            while queue:
                key=queue.pop();visited.add(key)
                for neighbor,difference in graph[key]:
                    proposed=relative[key]+difference
                    if neighbor in relative:
                        consistent &= abs(relative[neighbor]-proposed)<1e-5
                    else:
                        relative[neighbor]=proposed;queue.append(neighbor)
            anchors=[(n['id'],n['measure_beat']-relative[key]) for key in relative for n in groups[key]
                     if n['measure_beat'] is not None]
            if not consistent or not anchors or max(v for _,v in anchors)-min(v for _,v in anchors)>1e-5:
                continue
            base=anchors[0][1]
            meter=next((m.get('meter_beats') for m in staff.get('measures',[]) if m['measure']==groups[start][0]['measure']),None)
            if any(base+offset<-.00001 or (meter is not None and base+offset>=meter-.00001) for offset in relative.values()):
                continue
            for key,offset in relative.items():
                for note in groups[key]:
                    if note['measure_beat'] is not None:
                        continue
                    note['measure_beat']=round(base+offset,6)
                    note['onset_evidence']={'method':'adjacent_attacks_on_same_printed_beam','anchor_ids':[n for n,_ in anchors]}
                    note['issues']=[i for i in note['issues'] if i!='measure_timing_unresolved']


def _recover_grace_principal_timing(staves, events, lines):
    """Separate proven unmeasured ornaments from a complete principal rhythm.

    Written grace duration stays unknown. The principal note and its verified
    anchor are exposed for review/exclusion; no playback duration is invented.
    """
    for staff in staves:
        gap=staff['gap']
        for record in staff.get('measures',[]):
            meter=record.get('meter_beats')
            if meter is None:
                continue
            members=[e for e in events if e['staff']==staff['id'] and e['measure']==record['measure']]
            notes=[e for e in members if 'pitch_candidate' in e]
            rests=[e for e in members if 'pitch_candidate' not in e]
            groups=sorted(_event_groups(notes,gap),key=lambda g:g[0]['origin'][0])
            if not groups:
                continue
            grace_groups=[]
            for group in groups:
                if all('grace_or_cue_note_requires_review' in e['issues'] for e in group):
                    grace_groups.append((group,'slashed'))
            regular=next((g for g in groups if all('small_notated_note_requires_review' not in e['issues']
                          and 'grace_or_cue_note_requires_review' not in e['issues'] for e in g)),None)
            if regular is not None:
                prefix=[g for g in groups if g[0]['origin'][0]<regular[0]['origin'][0]]
                prefix_notes=[e for g in prefix for e in g]
                if (prefix_notes and not grace_groups and len(prefix)<=4
                        and regular[0]['origin'][0]-prefix[-1][0]['origin'][0]<3*gap
                        and all('small_notated_note_requires_review' in e['issues']
                                and not e['rhythm_evidence'].get('tuplet')
                                and e['rhythm_evidence'].get('beams',0)>0 for e in prefix_notes)):
                    stems=[e['rhythm_evidence'].get('stem') for e in prefix_notes]
                    connected=False
                    if all(stems):
                        for x1,y1,x2,y2,width in lines:
                            if abs(x2-x1)<gap or not .3*gap<=width<=.9*gap:
                                continue
                            tolerance=max(.2*gap,width/2+.05*gap)
                            if all(min(x1,x2)-tolerance<=stem[0]<=max(x1,x2)+tolerance
                                   and min(abs(y1+(y2-y1)*(stem[0]-x1)/(x2-x1)-stem[1]),
                                           abs(y1+(y2-y1)*(stem[0]-x1)/(x2-x1)-stem[2]))<.6*gap
                                   for stem in stems):
                                connected=True;break
                    if connected:
                        grace_groups=[(prefix_notes,'unmeasured_prefix')]
            # An internal small ornament has the same font/stem evidence as a
            # prefix. The complete principal rhythm and independent paired
            # voice below must both agree before it can be unmeasured.
            known={e['id'] for g,_ in grace_groups for e in g}
            for group in groups:
                if any(e['id'] in known for e in group):continue
                if not all('small_notated_note_requires_review' in e['issues']
                           and e.get('rhythm_evidence',{}).get('beams',0)>0
                           and not e['rhythm_evidence'].get('tuplet') for e in group):continue
                grace_groups.append((group,'unmeasured'))
            if not grace_groups:
                continue
            grace_ids={e['id'] for group,_ in grace_groups for e in group}
            principal_groups=[g for g in groups if not any(e['id'] in grace_ids for e in g)]
            timeline=[(g[0]['origin'][0],g,{e['duration'] for e in g}) for g in principal_groups]
            timeline.extend((r['origin'][0],[r],{r['duration']}) for r in rests)
            timeline.sort(key=lambda item:item[0])
            if (not timeline or any(len(values)!=1 or None in values for _,_,values in timeline)
                    or abs(sum(next(iter(values)) for _,_,values in timeline)-meter)>1e-6):
                continue
            paired=[e for e in events if e['staff']!=staff['id'] and e['measure']==record['measure']
                    and e['measure_beat'] is not None and not e.get('excluded')
                    and any(s['id']==e['staff'] and any(m['measure']==record['measure'] and m['timing_resolved']
                        for m in s.get('measures',[])) for s in staves)]
            def aligned(x,group,other):
                if len(group)==1 and 'pitch_candidate' not in group[0]:
                    box=group[0]['bbox'];other_box=other.get('glyph_bbox',other.get('bbox'))
                    center=(other_box[0]+other_box[2])/2 if other_box else other['origin'][0]
                    return box[0]-.1*gap<=center<=box[2]+.1*gap
                return abs(other['origin'][0]-x)<.35*gap
            if not any(aligned(timeline[0][0],timeline[0][1],e) and e['measure_beat']==0 for e in paired):
                continue
            planned={};beat=0.0;contradiction=False
            for x,group,values in timeline:
                if any(aligned(x,group,e) and abs(e['measure_beat']-beat)>1e-5 for e in paired):
                    contradiction=True;break
                for e in group:
                    planned[e['id']]=round(beat,6)
                beat+=next(iter(values))
            if contradiction:
                continue
            anchors=[]
            for group,kind in grace_groups:
                main=next((g for g in principal_groups if g[0]['origin'][0]>max(e['origin'][0] for e in group)),None)
                if main is None:
                    break
                between=[r for r in rests if max(e['origin'][0] for e in group)<r['origin'][0]<main[0]['origin'][0]]
                if between:
                    # Engravers can place a slashed ornament before/above the
                    # rest preceding its principal. This strong path already
                    # proves a full principal meter and independent paired
                    # onsets. A horizontal rest is not an anchor boundary
                    # when the actual slash and one complete voice agree.
                    hands={e.get('hand') for e in members}
                    one_voice=all(e.get('voice')==members[0].get('voice') for e in members)
                    unique_stems=all(len({tuple(e.get('rhythm_evidence',{}).get('stem') or ()) for e in g})==1
                                     for g in principal_groups)
                    protected=any(e.get('confirmed') or any(f in e.get('manual_fields',[]) for f in
                        ('duration','duration_beats','beats','measure_beat','local_beat','beat','start_beat','written_beat')) for e in members)
                    if (kind!='slashed' or None in hands or len(hands)!=1 or not one_voice or not unique_stems or protected
                            or any('multiple_voices_require_review' in e.get('issues',[]) for e in members)
                            or not all(_grace_slash_evidence(e.get('rhythm_evidence',{}),lines,gap) for e in group)):
                        break
                anchors.append((group,kind,main))
            if len(anchors)!=len(grace_groups):
                continue
            for event in members:
                if event['id'] in planned:
                    event['measure_beat']=planned[event['id']]
                    event['issues']=[i for i in event['issues'] if i!='measure_timing_unresolved']
                    event['onset_evidence']={'method':'complete_principal_rhythm_with_paired_voice_anchor'}
            for group,kind,main in anchors:
                for order,event in enumerate(sorted(group,key=lambda e:e['origin'][0])):
                    event.update(grace_group=group[0]['id']+'-grace',grace_kind=kind,grace_order=order,
                        grace_nominal_duration_beats=event['duration'],duration=None,beats=None,measure_beat=None,
                        main_anchor_id=main[0]['id'],main_anchor_ids=[e['id'] for e in main],
                        main_anchor_measure_beat=planned[main[0]['id']])
                    event['issues'].append('unmeasured_grace_requires_review')
            record.update(total_beats=meter,timing_resolved=True,length_beats=meter,
                          timing_method='complete_principal_rhythm_with_unmeasured_grace')


def _mark_unresolved_slashed_graces(staves, events, lines=()):
    """Keep an observed slashed grace independent of whole-bar resolution."""
    for staff in staves:
        gap=staff['gap']
        members=[e for e in events if e.get('staff')==staff['id']]
        for measure in sorted({e['measure'] for e in members}):
            notes=[e for e in members if e['measure']==measure and 'pitch_candidate' in e]
            rests=[e for e in members if e['measure']==measure and 'pitch_candidate' not in e]
            groups=sorted(_event_groups(notes,gap),key=lambda group:min(e['origin'][0] for e in group))
            i=0
            while i<len(groups):
                def unresolved_grace(group):
                    return all('grace_or_cue_note_requires_review' in e.get('issues',[])
                               and not e.get('grace_kind') for e in group)
                if not unresolved_grace(groups[i]):
                    i+=1;continue
                start=i
                while i<len(groups) and unresolved_grace(groups[i]):
                    i+=1
                prior=groups[start:i]
                if i>=len(groups):
                    continue
                main=groups[i]
                if (any('small_notated_note_requires_review' in e.get('issues',[])
                        or 'grace_or_cue_note_requires_review' in e.get('issues',[]) for e in main)
                        or len({e.get('hand') for g in prior+[main] for e in g})!=1):
                    continue
                last_x=max(e['origin'][0] for e in prior[-1])
                main_x=min(e['origin'][0] for e in main)
                first_x=min(e['origin'][0] for e in prior[0])
                verified_slashes={e['id']:_grace_slash_evidence(e.get('rhythm_evidence',{}),lines,gap)
                                  for group in prior for e in group}
                # A review issue alone can mean cue notation. Preserve the
                # original nearby-anchor limit unless every grace stem has
                # an independently observed slash in the current PDF geometry.
                if main_x-last_x>3*gap and not all(verified_slashes.values()):
                    continue
                if (not 0<main_x-last_x
                        or any(min(e['origin'][0] for e in b)-max(e['origin'][0] for e in a)>3*gap
                               for a,b in zip(prior,prior[1:]))
                        or any(first_x<r['origin'][0]<main_x for r in rests)):
                    continue
                ordered=sorted((e for group in prior for e in group),key=lambda e:e['origin'][0])
                anchor_ids=[e['id'] for e in main]
                for order,event in enumerate(ordered):
                    event.update(grace_group=ordered[0]['id']+'-grace',grace_kind='slashed',grace_order=order,
                        grace_nominal_duration_beats=event.get('duration'),duration=None,beats=None,measure_beat=None,
                        main_anchor_id=anchor_ids[0],main_anchor_ids=anchor_ids)
                    if main[0].get('measure_beat') is not None:
                        event['main_anchor_measure_beat']=main[0]['measure_beat']
                    if 'unmeasured_grace_requires_review' not in event['issues']:
                        event['issues'].append('unmeasured_grace_requires_review')


def _continuous_beam_family(stems, count, direction, gap, lines, monitored_stems=None):
    """Find one parallel family that continuously spans all bounded stems.

    A printed beam can be exported as several adjacent vector segments. A
    short hook crossing a middle stem is not enough to establish a full beam;
    a parallel partial extra level touching a middle stem keeps it ambiguous.
    """
    stems=sorted(set(tuple(s) for s in stems),key=lambda s:s[0])
    if len(stems)<(2 if monitored_stems is not None else 3):
        return None
    monitored=stems[1:-1] if monitored_stems is None else [tuple(s) for s in monitored_stems]
    left,right=stems[0][0],stems[-1][0]
    reference=(left+right)/2
    tips=[s[1] if direction=='up' else s[2] for s in stems]
    candidates=[]
    for index,(x1,y1,x2,y2,width) in enumerate(lines):
        lo,hi=sorted((x1,x2));span=hi-lo
        if (span<.6*gap or not .3*gap<=width<=.9*gap
                or hi<left-.2*gap or lo>right+.2*gap):
            continue
        slope=(y2-y1)/(x2-x1)
        # Avoid unrelated very remote vector strokes before clustering.
        yref=y1+slope*(reference-x1)
        if not min(tips)-5*gap<=yref<=max(tips)+5*gap:
            continue
        candidates.append(dict(index=index,lo=lo,hi=hi,slope=slope,y1=y1,x1=x1,width=width,span=span))
    families={}
    for seed in candidates:
        slope=seed['slope']
        parallel=[s for s in candidates if abs(s['slope']-slope)*min(s['span'],4*gap)<.12*gap]
        levels=[]
        for s in sorted(parallel,key=lambda s:s['y1']+slope*(reference-s['x1'])):
            yref=s['y1']+slope*(reference-s['x1'])
            level=next((v for v in levels if abs(yref-v['reference_y'])<.25*gap),None)
            if level is None:
                level=dict(reference_y=yref,segments=[]);levels.append(level)
            level['segments'].append(s)
        full=[];partial_middle=False
        for level in levels:
            segments=sorted(level['segments'],key=lambda s:s['lo'])
            merged=[]
            for segment in segments:
                tolerance=max(.2*gap,segment['width']/2+.05*gap)
                if merged and segment['lo']<=merged[-1][1]+tolerance:
                    merged[-1][1]=max(merged[-1][1],segment['hi'])
                    merged[-1][2]=max(merged[-1][2],tolerance)
                else:
                    merged.append([segment['lo'],segment['hi'],tolerance])
            complete=any(lo-tol<=left and hi+tol>=right for lo,hi,tol in merged)
            if complete:
                full.append(level)
            elif any(lo-tol<=stem[0]<=hi+tol for lo,hi,tol in merged for stem in monitored):
                partial_middle=True
        full.sort(key=lambda level:level['reference_y'])
        if (partial_middle or len(full)!=count
                or any(not .4*gap<=b['reference_y']-a['reference_y']<=gap for a,b in zip(full,full[1:]))):
            continue
        sign=1 if direction=='up' else -1
        values=[[level['reference_y']+slope*(stem[0]-reference) for stem in stems] for level in full]
        if (any(not -.6*gap<=sign*(ys[i]-tips[i])<=3.2*gap
                for ys in values for i in range(len(stems)))
                or any(not any(abs(ys[i]-tips[i])<=.6*gap for ys in values) for i in range(len(stems)))):
            continue
        key=tuple(tuple(sorted(s['index'] for s in level['segments'])) for level in full)
        families[key]=dict(slope=slope,levels=len(full),segment_count=sum(len(v['segments']) for v in full))
    return next(iter(families.values())) if len(families)==1 else None


def _recover_clear_beam_family(staves, events, lines, chars, text_chars=None):
    """Recover a bounded run only from one continuous shared beam family.

    The two outer shafts must have original, independently recognized beam
    counts and direction. New recoveries are never reused as outer anchors.
    """
    recovered=0
    for staff in staves:
        gap=staff['gap']
        notes=[n for n in events if n.get('staff')==staff['id'] and 'pitch_candidate' in n]
        anchors_snapshot=[n for n in notes if n.get('duration') is not None
                          and not n.get('rhythm_evidence',{}).get('beam_recovery')]
        for target in notes:
            rhythm=target.get('rhythm_evidence',{});stem=rhythm.get('stem');issues=target.get('issues',[])
            if (target.get('duration') is not None or not isinstance(stem,(list,tuple)) or len(stem)!=3
                    or rhythm.get('head')!='filled'
                    or not {'beam_attachment_ambiguous','beam_spacing_conflict'}.intersection(issues)
                    or 'grace_or_cue_note_requires_review' in issues
                    or 'small_notated_note_requires_review' in issues):
                continue
            neighbours={}
            for note in anchors_snapshot:
                evidence=note.get('rhythm_evidence',{});other=evidence.get('stem');beams=evidence.get('beams')
                if (note is target or note.get('measure')!=target.get('measure')
                        or note.get('hand')!=target.get('hand') or not isinstance(other,(list,tuple)) or len(other)!=3
                        or not isinstance(beams,int) or not 2<=beams<=4 or evidence.get('dots',0)
                        or evidence.get('tuplet') or evidence.get('stem_direction') not in ('up','down')
                        or note.get('duration')!=1/(2**beams)):
                    continue
                neighbours.setdefault(tuple(other),[]).append(note)
            left=[key for key in neighbours if key[0]<stem[0]-.35*gap]
            right=[key for key in neighbours if key[0]>stem[0]+.35*gap]
            if not left or not right:
                continue
            l=max(left,key=lambda key:key[0]);r=min(right,key=lambda key:key[0])
            if r[0]-l[0]>30*gap:
                continue
            anchors=neighbours[l]+neighbours[r]
            counts={n['rhythm_evidence']['beams'] for n in anchors}
            directions={n['rhythm_evidence']['stem_direction'] for n in anchors}
            if len(counts)!=1 or len(directions)!=1:
                continue
            count=next(iter(counts));direction=next(iter(directions))
            if any(e.get('staff')==staff['id'] and e.get('measure')==target.get('measure')
                   and 'pitch_candidate' not in e and l[0]<e['origin'][0]<r[0] for e in events):
                continue
            between=[]
            for note in notes:
                if note.get('measure')!=target.get('measure'):
                    continue
                value=note.get('rhythm_evidence',{}).get('stem')
                xpos=value[0] if isinstance(value,(list,tuple)) and len(value)==3 else note['origin'][0]
                if l[0]-.15*gap<=xpos<=r[0]+.15*gap:
                    between.append(note)
            voices={n.get('voice') for n in between if n.get('voice') is not None}
            if (any(n.get('hand')!=target.get('hand') for n in between) or len(voices)>1
                    or (voices and any(n.get('voice') is None for n in between))):
                continue
            targets=[];stems=[];invalid=False
            for note in between:
                evidence=note.get('rhythm_evidence',{});other=evidence.get('stem');problems=note.get('issues',[])
                if not isinstance(other,(list,tuple)) or len(other)!=3:
                    invalid=True;break
                shaft_notes=[n for n in between if n.get('rhythm_evidence',{}).get('stem')==other]
                ymin=min(n['origin'][1] for n in shaft_notes);ymax=max(n['origin'][1] for n in shaft_notes)
                up=ymin-other[1];down=other[2]-ymax
                measured='up' if up>.6*gap and down<.5*gap else 'down' if down>.6*gap and up<.5*gap else None
                if measured!=direction:
                    invalid=True;break
                stems.append(other)
                if note.get('duration') is None:
                    if (evidence.get('head')!='filled'
                            or not {'beam_attachment_ambiguous','beam_spacing_conflict'}.intersection(problems)
                            or 'grace_or_cue_note_requires_review' in problems
                            or 'small_notated_note_requires_review' in problems):
                        invalid=True;break
                    heads=[c for c in chars if c.get('char') in HEADS
                           and abs(c.get('x',math.inf)-note['origin'][0])<.03*gap
                           and abs(c.get('y',math.inf)-note['origin'][1])<.03*gap]
                    if len(heads)!=1:
                        invalid=True;break
                    dots=_augmentation_dot_columns(heads[0],gap,chars,other)
                    if dots>2:
                        invalid=True;break
                    targets.append((note,dots))
                elif note not in anchors_snapshot or evidence.get('beams')!=count:
                    invalid=True;break
            if invalid or not targets:
                continue
            family=_continuous_beam_family(stems,count,direction,gap,lines)
            if family is None:
                continue
            # A printed tuplet mark may apply a ratio to the entire group, but
            # the earlier tuplet reader cannot finish while any value is None.
            # Keep it unresolved instead of silently claiming the nominal beam
            # duration when such a nearby numeric mark is present.
            tip=stem[1] if direction=='up' else stem[2]
            possible_tuplet=False
            for marker in (text_chars if text_chars is not None else chars):
                box=marker.get('bbox')
                if (marker.get('font')=='Aloisen' or marker.get('char') not in ('3','5','6','7','9')
                        or not box or len(box)!=4):
                    continue
                cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
                separation=(tip-cy) if direction=='up' else (cy-tip)
                if l[0]-.5*gap<=cx<=r[0]+.5*gap and 0<separation<5*gap:
                    possible_tuplet=True;break
            if possible_tuplet:
                continue
            for note,dots in targets:
                value=(1/(2**count))*sum(.5**i for i in range(dots+1))
                note['duration']=note['beats']=value
                note['rhythm_evidence']=dict(note['rhythm_evidence'],beams=count,dots=dots,stem_direction=direction,
                    beam_recovery={'method':'unique_continuous_parallel_family_with_original_anchors',
                                   'anchor_ids':[n['id'] for n in anchors],**family})
                note['issues']=[issue for issue in note['issues'] if issue not in ('beam_attachment_ambiguous','beam_spacing_conflict')]
                recovered+=1
    return recovered


def _recover_beam_from_physical_stems(staves, events, lines, chars, text_chars=None):
    """Resolve a shaft from independent shaft/beam ink, not a score-specific pattern.

    Short isolated extra strokes on the unresolved endpoint remain ambiguous.
    A small head is only usable when its actual font and size agree with a
    decoded, non-small peer.  Its original small-note warning is retained.
    """
    recovered=0
    for staff in staves:
        gap=staff['gap']
        notes=[n for n in events if n.get('staff')==staff['id'] and 'pitch_candidate' in n]
        anchors=[]
        for n in notes:
            rhythm=n.get('rhythm_evidence',{});stem=rhythm.get('stem');count=rhythm.get('beams')
            if (n.get('hand')!='right' or n.get('excluded') or not isinstance(stem,(list,tuple)) or len(stem)!=3
                    or type(count) is not int or not 1<=count<=4 or rhythm.get('head')!='filled'
                    or rhythm.get('stem_direction') not in ('up','down') or rhythm.get('dots',0)
                    or rhythm.get('tuplet') or rhythm.get('beam_recovery')
                    or n.get('grace_kind') or 'grace_or_cue_note_requires_review' in n.get('issues',[])
                    or n.get('duration')!=1/(2**count)):
                continue
            anchors.append(n)

        def head_for(note):
            matches=[c for c in chars if c.get('char') in HEADS
                     and abs(c.get('x',math.inf)-note['origin'][0])<.03*gap
                     and abs(c.get('y',math.inf)-note['origin'][1])<.03*gap]
            return matches[0] if len(matches)==1 else None

        def compatible_size(target,anchor,head):
            target_small='small_notated_note_requires_review' in target.get('issues',[])
            anchor_small='small_notated_note_requires_review' in anchor.get('issues',[])
            if not target_small:return not anchor_small
            if _has_grace_slash(anchor.get('rhythm_evidence',{}),lines,gap):return False
            peer=head_for(anchor)
            if not peer or not isinstance(head.get('size'),(int,float)) or not isinstance(peer.get('size'),(int,float)):
                return False
            return bool(head.get('font') and head['font']==peer.get('font') and
                        abs(head['size']-peer['size'])<=.02*gap)

        def possible_tuplet(left,right,tip,direction):
            for marker in (text_chars if text_chars is not None else chars):
                box=marker.get('bbox')
                if (marker.get('font')=='Aloisen' or marker.get('char') not in ('3','5','6','7','9')
                        or not box or len(box)!=4):
                    continue
                cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
                separation=(tip-cy) if direction=='up' else (cy-tip)
                # A tuplet mark can be centered above the entire connected
                # group, not the short neighbour pair used as local evidence.
                if left-5*gap<=cx<=right+5*gap and 0<separation<5*gap:return True
            return False

        for target in notes:
            rhythm=target.get('rhythm_evidence',{});stem=rhythm.get('stem');issues=target.get('issues',[])
            if (target.get('hand')!='right' or target.get('excluded') or target.get('duration') is not None
                    or not isinstance(stem,(list,tuple)) or len(stem)!=3 or rhythm.get('head')!='filled'
                    or not {'beam_attachment_ambiguous','beam_spacing_conflict'}.intersection(issues)
                    or 'grace_or_cue_note_requires_review' in issues or target.get('grace_kind')
                    or _has_grace_slash(rhythm,lines,gap)):
                continue
            head=head_for(target)
            if head is None:continue
            dots=_augmentation_dot_columns(head,gap,chars,stem)
            if dots>2:continue
            same_staff=[n for n in notes if n.get('measure')==target.get('measure')]
            same_shaft=[n for n in same_staff if n.get('rhythm_evidence',{}).get('stem')==stem]
            yvalues=[n['origin'][1] for n in same_shaft]
            up=min(yvalues)-stem[1];down=stem[2]-max(yvalues)
            direction='up' if up>.6*gap and down<.5*gap else 'down' if down>.6*gap and up<.5*gap else None
            if direction is None:continue
            local=[a for a in anchors if a.get('measure')==target.get('measure')
                   and a['rhythm_evidence']['stem_direction']==direction
                   and compatible_size(target,a,head)]
            if not local:continue
            hypotheses=[]
            # All heads on one physical shaft share its beam structure.  If a
            # printed cue is smaller than its peer it remains unresolved.
            same=[a for a in local if a['rhythm_evidence']['stem']==stem]
            if same:
                counts={a['rhythm_evidence']['beams'] for a in same}
                voices={n.get('voice') for n in same_shaft if n.get('voice') is not None}
                tip=stem[1] if direction=='up' else stem[2]
                if (len(counts)==1 and len(voices)<=1 and
                        all(a['rhythm_evidence'].get('dots',0)==dots for a in same) and
                        all(n.get('hand')==target.get('hand') and not n.get('grace_kind') for n in same_shaft)
                        and not possible_tuplet(stem[0],stem[0],tip,direction)):
                    hypotheses.append((next(iter(counts)),same,'shared_original_stem',None))
            else:
                by_stem={tuple(a['rhythm_evidence']['stem']):[] for a in local
                         if .35*gap<abs(a['rhythm_evidence']['stem'][0]-stem[0])<=30*gap}
                for a in local:
                    key=tuple(a['rhythm_evidence']['stem'])
                    if key in by_stem:by_stem[key].append(a)
                # Only the closest independently decoded shaft on each side is
                # eligible; a distant match could jump over a distinct beam.
                left=[s for s in by_stem if s[0]<stem[0]];right=[s for s in by_stem if s[0]>stem[0]]
                for other in ([max(left,key=lambda s:s[0])] if left else [])+([min(right,key=lambda s:s[0])] if right else []):
                    peers=by_stem[other];counts={a['rhythm_evidence']['beams'] for a in peers}
                    voices={n.get('voice') for n in same_shaft+peers if n.get('voice') is not None}
                    if (len(counts)!=1 or len(voices)>1 or
                            (voices and any(n.get('voice') is None for n in same_shaft+peers))):
                        continue
                    lo,hi=sorted((stem[0],other[0]));tip=stem[1] if direction=='up' else stem[2]
                    if possible_tuplet(lo,hi,tip,direction):continue
                    if any(e.get('staff')==staff['id'] and e.get('measure')==target.get('measure')
                           and 'pitch_candidate' not in e and lo<e['origin'][0]<hi for e in events):
                        continue
                    between=[]
                    for n in same_staff:
                        shaft=n.get('rhythm_evidence',{}).get('stem')
                        x=shaft[0] if isinstance(shaft,(list,tuple)) and len(shaft)==3 else n['origin'][0]
                        if lo-.15*gap<=x<=hi+.15*gap and shaft not in (list(stem),list(other),tuple(stem),tuple(other)):
                            between.append(n)
                    if between:continue
                    family=_continuous_beam_family([stem,other],next(iter(counts)),direction,gap,lines,[stem])
                    if family is None:continue
                    count=next(iter(counts));conflict=False
                    for n in same_staff:
                        shaft=n.get('rhythm_evidence',{}).get('stem')
                        if (n is target or n in peers or n.get('excluded')
                                or not isinstance(shaft,(list,tuple)) or len(shaft)!=3
                                or tuple(shaft) in (tuple(stem),tuple(other))
                                or abs(shaft[0]-stem[0])>30*gap):
                            continue
                        same=[e for e in same_staff if e.get('rhythm_evidence',{}).get('stem')==shaft]
                        ymin=min(e['origin'][1] for e in same);ymax=max(e['origin'][1] for e in same)
                        upward=ymin-shaft[1];downward=shaft[2]-ymax
                        other_direction=('up' if upward>.6*gap and downward<.5*gap else
                                         'down' if downward>.6*gap and upward<.5*gap else None)
                        other_count=n.get('rhythm_evidence',{}).get('beams')
                        voices_pair={v for v in (target.get('voice'),n.get('voice')) if v is not None}
                        problematic=(n.get('hand')!=target.get('hand') or other_direction!=direction
                                     or len(voices_pair)>1 or (voices_pair and (target.get('voice') is None or n.get('voice') is None))
                                     or (n.get('duration') is not None and other_count!=count)
                                     or n.get('grace_kind') or 'grace_or_cue_note_requires_review' in n.get('issues',[]))
                        if problematic and _continuous_beam_family([stem,shaft],count,direction,gap,lines,[stem]) is not None:
                            conflict=True;break
                    if not conflict:
                        hypotheses.append((count,peers,'unique_adjacent_shaft_beam_family',family))
            if not hypotheses or len({item[0] for item in hypotheses})!=1:continue
            count=hypotheses[0][0]
            value=(1/(2**count))*sum(.5**i for i in range(dots+1))
            method=hypotheses[0][2];evidence=dict(method=method,anchor_ids=sorted({a['id'] for _,peers,_,_ in hypotheses for a in peers}))
            if hypotheses[0][3] is not None:evidence.update(hypotheses[0][3])
            target['duration']=target['beats']=value
            target['rhythm_evidence']=dict(rhythm,beams=count,dots=dots,stem_direction=direction,beam_recovery=evidence)
            target['issues']=[issue for issue in issues if issue not in ('beam_attachment_ambiguous','beam_spacing_conflict')]
            recovered+=1
    return recovered


def _repeat_marks(staff, lines, bars):
    """Recognize repeat dot pairs beside a thick bar, not ordinary final bars."""
    gap = staff["gap"]
    heavy = [x1 for x1,y1,x2,y2,width in lines if abs(x1-x2)<.2
             and width>=.3*gap and min(y1,y2)<=staff["top"]+.2*gap
             and max(y1,y2)>=staff["bottom"]-.2*gap]
    dots = [(x1,y1) for x1,y1,x2,y2,width in lines
            if abs(x1-x2)<.15*gap and abs(y1-y2)<.15*gap and .2*gap<=width<=.7*gap]
    dots.extend((c['x'],c['y']) for c in staff.get('chars',[]) if c['char']=='Ǉ')
    result = []
    for x in heavy:
        for side,kind in ((1,"start"),(-1,"end")):
            pair = [(dx,dy) for dx,dy in dots if .2*gap < side*(dx-x) < 2*gap]
            top = [(dx,dy) for dx,dy in pair if abs(dy-staff["top"]-1.5*gap)<.2*gap]
            bottom = [(dx,dy) for dx,dy in pair if abs(dy-staff["top"]-2.5*gap)<.2*gap]
            if any(abs(a[0]-b[0])<.2*gap for a in top for b in bottom):
                boundary = min(range(len(bars)), key=lambda i:abs(bars[i]-x))
                if abs(bars[boundary]-x)<2*gap:
                    marker = {"kind":kind,"boundary":boundary,"x":round(x,3)}
                    if not any(m["kind"]==kind and m["boundary"]==boundary for m in result):
                        result.append(marker)
    return sorted(result,key=lambda m:(m["boundary"],m["kind"]))


def _trim_opening_repeat_prefix(staff, lines, bars, musical_events):
    """A clef/key header before an opening repeat is not an empty measure."""
    if len(bars)>2 and musical_events and not any(c["x"]<bars[1] for c in musical_events):
        if any(mark["kind"]=="start" and mark["boundary"]==1 for mark in _repeat_marks(staff,lines,bars)):
            return bars[1:]
    return bars


def _ending_brackets(staff, lines, bars):
    """Expose volta bracket spans; the printed ending numbers still need review."""
    gap=staff["gap"]
    result=[]
    for x1,y1,x2,y2,width in lines:
        if abs(y1-y2)>.15 or abs(x2-x1)<4*gap or not staff["top"]-8*gap<y1<staff["top"]-gap:
            continue
        left,right=sorted((x1,x2))
        down=lambda x:any(abs(a-x)<.2*gap and abs(a-c)<.2*gap and min(b,d)<=y1+.2*gap
            and .5*gap<max(b,d)-y1<2.5*gap for a,b,c,d,w in lines)
        if not down(left) or not down(right):
            continue
        start=min(range(len(bars)),key=lambda i:abs(bars[i]-left))
        end=min(range(len(bars)),key=lambda i:abs(bars[i]-right))
        if end>start and abs(bars[start]-left)<2*gap and abs(bars[end]-right)<2*gap:
            bracket={"start_boundary":start,"end_boundary":end,"bbox":_round_box([left,y1,right,y1+1.5*gap]),
                     "start_beat":None,"end_beat":None,"confirmed":False}
            if not any(b["start_boundary"]==start and b["end_boundary"]==end for b in result):
                result.append(bracket)
    return sorted(result,key=lambda b:b["start_boundary"])


def _annotate_ties(events, curves, gap):
    """Suggest adjacent equal-pitch endpoints; keep slurs and uncertain arcs for review."""
    groups = _event_groups(events,gap)
    for left,right in zip(groups,groups[1:]):
        for source in left:
            matches = [target for target in right if source.get("pitch") is not None
                       and source["pitch"]==target.get("pitch")]
            if len(matches)!=1:
                continue
            target=matches[0]
            sx,sy=source["origin"];tx,ty=target["origin"]
            arcs=[box for box in curves if tx-sx>gap
                  and abs(box[0]-(sx+.7*gap))<1.1*gap and abs(box[2]-(tx+.7*gap))<1.1*gap
                  and box[3]-box[1]<3.5*gap
                  and min(abs(box[1]-sy),abs(box[3]-sy))<2*gap
                  and abs(sy-ty)<.2*gap]
            if arcs:
                source["tie_to_candidate"]=target["id"]
                source["tie_evidence"]={"method":"adjacent_equal_pitch_curve","bbox":list(arcs[0])}
                target["tie_from_candidate"]=source["id"]
                for event in (source,target):
                    if "tie_candidate_requires_review" not in event["issues"]:
                        event["issues"].append("tie_candidate_requires_review")


def _resolve_pickup(staves, events, meter):
    """A short opening is supported only by matching complete paired voices."""
    if meter is None or len(staves)!=2:
        return None
    openings=[next((m for m in s.get("measures",[]) if m["measure"]==1),None) for s in staves]
    if any(m is None or m["total_beats"] is None for m in openings):
        return None
    length=openings[0]["total_beats"]
    if not 0<length<meter or any(abs(m["total_beats"]-length)>1e-6 for m in openings):
        return None
    first=[e for e in events if e["measure"]==1]
    if any("grace_or_cue_note_requires_review" in e["issues"] or e["duration"] is None for e in first):
        return None
    for staff,opening in zip(staves,openings):
        members=[e for e in first if e["staff"]==staff["id"]]
        notes=[e for e in members if "pitch_candidate" in e]
        rests=[e for e in members if "pitch_candidate" not in e]
        timeline=[(g[0]["origin"][0],g,g[0]["duration"]) for g in _event_groups(notes,staff["gap"])]
        timeline.extend((r["origin"][0],[r],r["duration"]) for r in rests)
        beat=0.0
        for _,group,duration in sorted(timeline,key=lambda item:item[0]):
            for event in group:
                event["measure_beat"]=round(beat,6)
                event["issues"]=[issue for issue in event["issues"] if issue!="measure_timing_unresolved"]
                event["issues"].append("pickup_measure_requires_review")
            beat+=duration
        opening.update(timing_resolved=True,length_beats=length,pickup=True)
    return length


def _resolve_explicit_voices(notes, rests, staff, meter):
    """Resolve supported parallel voices; never serialize mixed chord durations."""
    if meter is None:
        return None
    gap=staff["gap"]
    def voice(event):
        rhythm=event["rhythm_evidence"]
        if rhythm.get("head")=="whole" and not rhythm.get("stem"):
            return "whole"
        return rhythm.get("stem_direction")
    by_voice={}
    for note in notes:
        key=voice(note)
        if key:
            by_voice.setdefault(key,[]).append(note)
    # Different stem layers must be explicitly simultaneous somewhere. A
    # monophonic melody changing stem direction is not evidence of two voices.
    opposed=any(voice(a)!=voice(b) and abs(a["origin"][0]-b["origin"][0])<.35*gap
                for key,items in by_voice.items() for a in items
                for other,others in by_voice.items() if other!=key for b in others)
    opposed |= any(abs(rest['origin'][0]-note['origin'][0])<.35*gap
                   for rest in rests for note in notes)
    whole=by_voice.get('whole',[])
    sustained_whole=(bool(whole) and all(n['duration']==meter for n in whole)
                     and len(_event_groups(whole,gap))==1
                     and min(n['origin'][0] for n in whole)<=min(n['origin'][0] for n in notes)+.35*gap)
    if len(by_voice)<2 or not (opposed or sustained_whole):
        return None
    timelines={}
    for key,items in by_voice.items():
        timelines[key]=[(g[0]["origin"][0],g,{e["duration"] for e in g}) for g in _event_groups(items,gap)]
    unassigned_rests=[]
    for rest in rests:
        y=rest["origin"][1]
        key="up" if y<staff["top"]+gap else "down" if y>staff["top"]+3*gap else None
        if key is None and sustained_whole and len(timelines)==2:
            key=next(key for key in timelines if key!='whole')
        if key in timelines:
            timelines[key].append((rest["origin"][0],[rest],{rest["duration"]}))
        else:
            unassigned_rests.append(rest)
    def shared_terminal_completion(totals, chosen=()):
        full=[key for key,value in totals.items() if abs(value-meter)<1e-6]
        completions={}
        for key,total in totals.items():
            if abs(total-meter)<1e-6:
                continue
            last_x=max([x for x,_,_ in timelines[key]]+
                       [r['origin'][0] for r,target in zip(unassigned_rests,chosen) if target==key],default=-math.inf)
            tails={}
            for other in full:
                x,group,values=max(timelines[other],key=lambda item:item[0])
                if (x>last_x+.35*gap and len(values)==1 and None not in values
                        and all('pitch_candidate' in e for e in group)
                        and abs(total+next(iter(values))-meter)<1e-6):
                    tails[tuple(e['id'] for e in group)]=(x,group,values)
            if len(tails)!=1:
                return None
            completions[key]=next(iter(tails.values()))
        return completions
    # Mid-staff rest glyphs do not by themselves say which opposed voice is
    # silent. Assign them only when exactly one allocation completes all
    # explicit voices. Simultaneity columns are checked again below.
    if unassigned_rests and all(r['duration'] is not None for r in unassigned_rests):
        totals={key:sum(next(iter(values)) for _,_,values in timeline)
                for key,timeline in timelines.items()
                if all(len(values)==1 and None not in values for _,_,values in timeline)}
        allocations=[]
        def allocate(index,chosen):
            if len(allocations)>1:
                return
            if index==len(unassigned_rests):
                completion=shared_terminal_completion(totals,chosen)
                if completion is not None:
                    allocations.append((list(chosen),completion))
                return
            duration=unassigned_rests[index]['duration']
            for key in totals:
                if totals[key]+duration<=meter+1e-6:
                    totals[key]+=duration;chosen.append(key)
                    allocate(index+1,chosen)
                    chosen.pop();totals[key]-=duration
        if len(totals)==len(timelines):
            allocate(0,[])
        if len(allocations)==1:
            for rest,key in zip(unassigned_rests,allocations[0][0]):
                timelines[key].append((rest['origin'][0],[rest],{rest['duration']}))
            for key,tail in allocations[0][1].items():
                timelines[key].append(tail)
    elif not unassigned_rests:
        totals={key:sum(next(iter(values)) for _,_,values in timeline)
                for key,timeline in timelines.items()
                if all(len(values)==1 and None not in values for _,_,values in timeline)}
        if len(totals)==len(timelines):
            completion=shared_terminal_completion(totals)
            if completion:
                for key,tail in completion.items():
                    timelines[key].append(tail)
    summaries=[];anchors=[];resolved=set();plans=[]
    for key,timeline in timelines.items():
        timeline.sort(key=lambda item:item[0])
        complete=all(len(values)==1 and None not in values for _,_,values in timeline)
        total=sum(next(iter(values)) for _,_,values in timeline) if complete else None
        complete &= total is not None and abs(total-meter)<1e-6
        complete &= not any("grace_or_cue_note_requires_review" in event["issues"] for _,group,_ in timeline for event in group)
        summaries.append({"voice":key,"total_beats":total,"complete":complete})
        if not complete:
            continue
        beat=0.0
        for x,group,values in timeline:
            plans.append((key,group,round(beat,6),total))
            beat+=next(iter(values))
    if not plans:
        return None
    # Complete voices must agree at physical simultaneity columns. Duration
    # sums alone cannot validate a mistaken voice/rest assignment.
    if any(abs(a["origin"][0]-b["origin"][0])<.3*gap and abs(t-u)>1e-6
           for key,group,t,_ in plans for other,others,u,_ in plans if key!=other
           for a in group for b in others):
        return None
    for key,group,beat,total in plans:
        for event in group:
            event["measure_beat"]=round(beat,6)
            event["voice"]=key
            event["onset_evidence"]={"method":"explicit_complete_voice","voice":key,"voice_total_beats":total}
            event["issues"]=[i for i in event["issues"] if i!="measure_timing_unresolved"]
            event["issues"].append("multiple_voices_require_review")
            resolved.add(event["id"])
            anchors.append((event["origin"][0],round(beat,6)))
    if not resolved:
        return None
    # A shorter/unknown layer can get an onset only from a unique physical
    # alignment with the already complete voice, not a guessed cumulative sum.
    for key,timeline in timelines.items():
        for _,group,_ in timeline:
            if all(event["id"] in resolved for event in group):
                continue
            candidates={beat for x,beat in anchors if any(abs(x-e["origin"][0])<.3*gap for e in group)}
            if len(candidates)!=1:
                continue
            for event in group:
                event["measure_beat"]=next(iter(candidates))
                event["voice"]=key
                event["onset_evidence"]={"method":"aligned_to_complete_voice","voice":key}
                event["issues"]=[i for i in event["issues"] if i!="measure_timing_unresolved"]
                event["issues"].append("multiple_voices_require_review")
    # A voice can branch off after an initial shared note: its own visible
    # sequence is shorter than the measure, but a physical column supplies the
    # offset. Continue that explicit voice from its verified anchor, retaining
    # all printed rests and rejecting any contradictory second anchor.
    for key,timeline in timelines.items():
        ordered=sorted(timeline,key=lambda item:item[0])
        if any(len(values)!=1 or None in values for _,_,values in ordered):
            continue
        positions=[];elapsed=0.0;offsets=[];anchor_ids=[]
        for x,group,values in ordered:
            positions.append((x,group,elapsed))
            for event in group:
                if event['measure_beat'] is not None:
                    offsets.append(event['measure_beat']-elapsed);anchor_ids.append(event['id'])
            elapsed+=next(iter(values))
        if (not offsets or max(offsets)-min(offsets)>1e-5 or min(offsets)<-1e-5
                or offsets[0]+elapsed>meter+1e-5):
            continue
        offset=offsets[0]
        if any(abs(x-ax)<.3*gap and abs(offset+relative-beat)>1e-5
               for x,_,relative in positions for ax,beat in anchors):
            continue
        if any(same_time and min(abs(x-ax) for ax in same_time)>1.5*gap
               for x,_,relative in positions
               for same_time in [[ax for ax,beat in anchors if abs(beat-offset-relative)<1e-5]]):
            continue
        for _,group,relative in positions:
            for event in group:
                if event['measure_beat'] is not None:
                    continue
                event['measure_beat']=round(offset+relative,6)
                event['voice']=key
                event['onset_evidence']={'method':'anchored_partial_explicit_voice','anchor_ids':anchor_ids,
                                         'voice':key,'offset_beats':round(offset,6)}
                event['issues']=[i for i in event['issues'] if i!='measure_timing_unresolved']
                event['issues'].append('multiple_voices_require_review')
    return summaries


def _resolve_two_note_tremolo(notes, rests, staff, meter, lines):
    """A measured two-chord tremolo occupies one notated span, not two."""
    if rests or meter is None or not notes:
        return None
    gap=staff['gap']
    groups=sorted(_event_groups(notes,gap),key=lambda g:g[0]['origin'][0])
    if (len(groups)!=2 or any(n['duration']!=meter for n in notes)
            or any(n['rhythm_evidence'].get('head')!='whole' for n in notes)):
        return None
    left=max(n['origin'][0] for n in groups[0]);right=min(n['origin'][0] for n in groups[1])
    low=min(n['origin'][1] for n in notes)-gap;high=max(n['origin'][1] for n in notes)+gap
    strokes=[]
    for x1,y1,x2,y2,width in lines:
        lo,hi=sorted((x1,x2))
        if (abs(y1-y2)<.15*gap and .3*gap<=width<=.9*gap and hi-lo>gap
                and left+1.4*gap<lo<hi<right-.3*gap and low<=y1<=high):
            strokes.append((lo,hi,(y1+y2)/2))
    strokes=sorted(set(strokes),key=lambda line:line[2])
    if len(strokes) not in (2,3):
        return None
    if (any(abs(a-b)>.3*gap for a,b in zip(strokes[0][:2],strokes[-1][:2]))
            or any(not .4*gap<=b[2]-a[2]<=gap for a,b in zip(strokes,strokes[1:]))):
        return None
    group_id=groups[0][0]['id']+'-tremolo'
    evidence={'method':'two_whole_note_groups_between_parallel_tremolo_strokes',
              'strokes':[_round_box(stroke) for stroke in strokes],'stroke_count':len(strokes)}
    for side,group in enumerate(groups):
        for note in group:
            note.update(measure_beat=0.0,tremolo_group=group_id,tremolo_side=side,
                        tremolo_step_beats=1/(2**len(strokes)),tremolo_span_beats=meter,
                        tremolo_evidence=evidence)
            note['issues']=[i for i in note['issues'] if i!='measure_timing_unresolved']
            note['issues'].append('measured_tremolo_requires_realization')
    return evidence


def _resolve_mixed_tremolo_measure(notes, rests, staff, meter, lines):
    """Resolve detached, parallel two-note tremolos within a complete bar.

    Each pair occupies one printed span. Other attacks and rests retain their
    normal positions. Ambiguous candidates or an incomplete bar remain for
    review rather than having a tremolo inferred from duration sums alone.
    """
    if not notes or meter is None:
        return None
    gap=staff['gap']
    groups=sorted(_event_groups(notes,gap),key=lambda group:min(n['origin'][0] for n in group))
    candidates=[]
    for index,(left,right) in enumerate(zip(groups,groups[1:])):
        values={n.get('duration') for n in left+right}
        if (len(values)!=1 or None in values or next(iter(values))<1
                or len({n.get('hand') for n in left+right})>1
                or any(n.get('rhythm_evidence',{}).get('beams',0) for n in left+right)
                or any(n.get('grace_kind') or 'grace_or_cue_note_requires_review' in n.get('issues',[])
                       for n in left+right)):
            continue
        lx=max(n['origin'][0] for n in left);rx=min(n['origin'][0] for n in right)
        if rx-lx<=2*gap or any(lx<r['origin'][0]<rx for r in rests):
            continue
        low=min(n['origin'][1] for n in left+right)-2*gap
        high=max(n['origin'][1] for n in left+right)+2*gap
        strokes=[]
        for x1,y1,x2,y2,width in lines:
            lo,hi=sorted((x1,x2))
            if (hi-lo<=gap or not .3*gap<=width<=.9*gap
                    or lo<lx+.35*gap or hi>rx+.15*gap):
                continue
            slope=(y2-y1)/(x2-x1)
            mid=(lx+rx)/2
            yy=y1+slope*(mid-x1)
            if abs(slope)<=1 and low<=yy<=high:
                strokes.append((lo,hi,yy,slope))
        strokes=sorted(set(strokes),key=lambda stroke:stroke[2])
        if len(strokes) not in (2,3):
            continue
        if (any(abs(s[0]-strokes[0][0])>.3*gap or abs(s[1]-strokes[0][1])>.3*gap
                or abs(s[3]-strokes[0][3])*min(s[1]-s[0],4*gap)>.12*gap for s in strokes)
                or any(not .4*gap<=b[2]-a[2]<=gap for a,b in zip(strokes,strokes[1:]))):
            continue
        span=next(iter(values));step=1/(2**len(strokes))
        if abs(span/step-round(span/step))>1e-6:
            continue
        candidates.append((index,left,right,span,step,strokes))
    if not candidates:
        return None
    # A note belonging to two possible pairs is ambiguous.
    indices=[i for candidate in candidates for i in (candidate[0],candidate[0]+1)]
    if len(indices)!=len(set(indices)):
        return None
    paired={c[0]:c for c in candidates};consumed={c[0]+1 for c in candidates}
    timeline=[]
    for index,group in enumerate(groups):
        if index in consumed:
            continue
        if index in paired:
            _,left,right,span,step,strokes=paired[index]
            timeline.append((min(n['origin'][0] for n in left),left+right,span,paired[index]))
        else:
            values={n.get('duration') for n in group}
            if len(values)!=1 or None in values:
                return None
            timeline.append((min(n['origin'][0] for n in group),group,next(iter(values)),None))
    for rest in rests:
        if rest.get('duration') is None:
            return None
        timeline.append((rest['origin'][0],[rest],rest['duration'],None))
    timeline.sort(key=lambda item:item[0])
    if abs(sum(item[2] for item in timeline)-meter)>1e-6:
        return None
    offset=0.0;evidence=[]
    for _,members,duration,pair in timeline:
        for event in members:
            event['measure_beat']=round(offset,6)
            event['issues']=[issue for issue in event.get('issues',[]) if issue!='measure_timing_unresolved']
        if pair is not None:
            _,left,right,span,step,strokes=pair
            group_id=str(left[0]['id'])+'-tremolo'
            proof=dict(method='detached_parallel_strokes_and_complete_right_voice',
                       stroke_count=len(strokes),span_beats=span,
                       strokes=[_round_box((s[0],s[1],s[2],s[3])) for s in strokes])
            for side,group in enumerate((left,right)):
                for note in group:
                    note.update(tremolo_group=group_id,tremolo_side=side,
                                tremolo_step_beats=step,tremolo_span_beats=span,
                                tremolo_evidence=proof)
                    note['issues'].append('measured_tremolo_requires_realization')
            evidence.append(proof)
        offset+=duration
    return dict(method='mixed_measured_tremolo',groups=evidence,total_beats=round(offset,6))


def _ordinary_metric_extent(staves, lines, measure, meter, excluded=False):
    """The extent of an ordinary metered bar is independent of parsed voices."""
    if excluded or meter is None or len(staves)!=2:
        return None
    gap=median(s["gap"] for s in staves)
    if any(len(s.get("bars",[]))<=measure for s in staves):
        return None
    boundaries=[s["bars"][measure-1:measure+1] for s in staves]
    if any(abs(a-b)>.3*gap for a,b in zip(*boundaries)):
        return None
    records=[next((m for m in s.get("measures",[]) if m["measure"]==measure),None) for s in staves]
    if any(s.get('later_meter_change') and (not record or record.get('meter_beats')!=meter)
           for s,record in zip(staves,records)):
        return None
    totals=[m.get("total_beats") if m else None for m in records]
    # A coherent paired short/irregular bar is positive evidence against the
    # ordinary full-bar rule. A recognizer's isolated voice-sum conflict is not
    # evidence that the printed meter changed.
    if (all(t is not None for t in totals) and abs(totals[0]-totals[1])<1e-6
        and abs(totals[0]-meter)>.01):
        return None
    for boundary in boundaries[0]:
        for staff in staves:
            if not any(abs(x1-x2)<.2 and abs(x1-boundary)<.2*gap and 0<width<.25*gap
                       and min(y1,y2)<=staff['top']+.2*gap and max(y1,y2)>=staff['bottom']-.2*gap
                       for x1,y1,x2,y2,width in lines):
                return None
    return {"method":"explicit_meter_shared_ordinary_barlines","quarter_beats":meter,
            "boundary_x":boundaries[0],"local_note_onsets_verified":False}


def _braced_piano_layout(staves, chars):
    """Use the printed grand-staff brace, not row parity, to identify piano hands.

    Other staves preceding a brace belong to the same printed system but are
    kept outside the piano selection. Incomplete brace coverage leaves the
    existing review-required fallback in place.
    """
    pairs = set()
    for char in chars:
        if char['char'] != 'ğ':
            continue
        box = char['bbox']
        members = [i for i, staff in enumerate(staves)
                   if box[1] - .6*staff['gap'] <= staff['top']
                   and staff['bottom'] <= box[3] + .6*staff['gap']
                   and abs(box[2] - staff['left']) < 2*staff['gap']]
        if len(members) == 2 and members[1] == members[0] + 1:
            pairs.add(tuple(members))
    if not pairs:
        return None
    layout = []
    cursor = 0
    for system, (right, left) in enumerate(sorted(pairs), 1):
        if right < cursor:
            return None
        for index in range(cursor, left+1):
            layout.append(dict(system=system, hand='right' if index==right else 'left' if index==left else None,
                               upper_partner=right if index==left else None,
                               outside_piano=index not in (right,left)))
        cursor = left+1
    return layout if cursor == len(staves) else None


def recognize(path):
    """Return a JSON-safe review project. Unknown values are None, never guessed."""
    path = Path(path)
    project = {"schema_version": 1, "recognizer": "aloisen-vector-review-v25",
               "pdf_backend": "pdfium-vector-v1",
               "source_name": path.name, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "coordinate_system": "PDF points, top-left; bbox=[x0,y0,x1,y1]; page is 1-based",
               "timing_unit": "quarter-note beats", "timing_mode":"written",
               "pages": [], "notes": [], "rests": [], "staves": [], "repeat_markers": [], "repeat_sections": [],
               "repeat_review_issues": [], "ending_brackets": [], "octave_regions": [],
               "issues": ["All recognized notes require manual confirmation.",
                          "Beat fields follow written score order; reviewed repeat expansion is separate.",
                          "Ties, slurs, octave lines and multiple voices require review.",
                          "Hand assignment follows paired piano staves; cross-staff/hand changes are not inferred."],
               "playback_ready": False}
    global_measure_base = 0.0
    global_measure_index = 0
    global_timing_open = True
    tuplet_continuations = {}
    with open_document(path) as document:
        underlying=getattr(document,"document",None)
        page_count=len(underlying) if underlying is not None else None
        _notify_conversion_progress("recognizing",label="识别原谱",page_done=0,page_total=page_count)
        for page_index, page in enumerate(document):
            chars = _chars(page)
            text_chars=page.chars(music_only=False)
            text_octaves=_text_octave_markers(page)
            lines, curves = _geometry(page)
            staves = _staves(lines, page.rect.width)
            if page_index==0:
                tempo=_initial_printed_tempo(text_chars,staves,lines)
                if tempo is not None:
                    project['source_tempo_bpm']=tempo['quarter_bpm']
                    project['source_tempo_evidence']=tempo
            head_owners={id(c):_head_staff(c,staves,lines,chars) for c in chars if c["char"] in HEADS}
            owners={id(c):(head_owners[id(c)][0] if c["char"] in HEADS else _nearest_staff(c,staves)) for c in chars}
            for symbol in chars:
                if symbol['char'] not in RESTS.keys()|{MEASURE_REST} or owners.get(id(symbol)) is not None:
                    continue
                adjacent=[]
                for head in chars:
                    if head['char'] not in HEADS:
                        continue
                    owner,evidence=head_owners[id(head)]
                    if (owner is None or not evidence or evidence.get('method')!='complete_ledger_chain'
                            or abs(head['x']-symbol['x'])>1.5*owner['gap']
                            or abs(head['y']-symbol['y'])>3.5*owner['gap']):
                        continue
                    adjacent.append(((abs(head['y']-symbol['y'])+2*abs(head['x']-symbol['x']))/owner['gap'],owner))
                adjacent.sort(key=lambda item:item[0])
                if adjacent and not any(other is not adjacent[0][1] and distance<adjacent[0][0]+.5
                                        for distance,other in adjacent[1:]):
                    owners[id(symbol)]=adjacent[0][1]
            for char in chars:
                if char["char"] not in ACCIDENTALS:
                    continue
                local_heads=[h for h in chars if h["char"] in HEADS and owners.get(id(h)) is not None
                             and .15*owners[id(h)]["gap"]<h["x"]-char["x"]<2.3*owners[id(h)]["gap"]
                             and abs(h["y"]-char["y"])<.3*owners[id(h)]["gap"]]
                if local_heads:
                    owners[id(char)]=owners[id(min(local_heads,key=lambda h:h["x"]-char["x"]))]
            text_available=False;page_text=""
            if getattr(page,"page",None) is not None:
                with closing(page.page.get_textpage()) as text_page:
                    page_text=text_page.get_text_range()
                    text_available=True
            nonmetric_or_navigation=not text_available or bool(re.search(
                r"cadenza|cadenz[ae]|senza\s+misura|free[\s-]+(?:time|meter)|ad[\s.]*lib|"
                r"D[\s.]*[SC]\s*\.|da\s+capo|dal\s+segno|segno|coda|\bfine\b|散板|华彩|自由节奏",
                page_text,re.IGNORECASE))
            nonmetric_or_navigation |= any(c["char"] in ("ư","Ʊ") for c in chars)
            project["pages"].append({"page": page_index+1, "width": page.rect.width,
                                     "height": page.rect.height, "staff_count": len(staves)})
            if not staves or not chars:
                project["issues"].append(f"page_{page_index+1}: unsupported or scanned page; no verified Aloisen vector staff")
                global_timing_open = False
                _notify_conversion_progress("recognizing",label="识别原谱",page_done=page_index+1,page_total=page_count)
                continue
            system = -1
            previous = None
            piano_layout = _braced_piano_layout(staves, chars)
            for i, staff in enumerate(staves):
                gap = staff["gap"]
                if piano_layout:
                    assignment = piano_layout[i]
                    system = assignment['system']-1
                    hand = assignment['hand']
                    staff.update(assignment)
                elif previous is None or i % 2 == 0 or staff["top"]-previous["top"] > 22*gap:
                    system += 1
                    hand = "right"
                else:
                    hand = "left"
                if not piano_layout:
                    staff['upper_partner'] = i-1 if hand=='left' else None
                staff.update(id=f"p{page_index+1}-s{i+1}", hand=hand, system=system+1)
                staff["chars"] = [c for c in chars if owners[id(c)] is staff]
                staff["heads"] = [c for c in staff["chars"] if c["char"] in HEADS
                                  and _is_score_head(c,staff,lines,staff['chars'])]
                clefs = [c for c in staff["chars"] if c["char"] in CLEFS]
                staff["clef"] = CLEFS[clefs[0]["char"]] if clefs else None
                staff["clefs"] = clefs
                previous = staff
            for i, staff in enumerate(staves):
                upper = staff['upper_partner']
                if (upper is not None and not staves[upper]["heads"] and staff["heads"]
                        and not any(c['char'] in RESTS.keys()|UNKNOWN_RESTS|{MEASURE_REST}
                                    for c in staves[upper]['chars'])):
                    staff["hand"] = None  # Common piano cross-staff notation; don't invent hands.
            finger_jobs=[]
            head_rhythms={id(head):_stem_and_duration(head,staff,lines,chars)
                          for staff in staves for head in staff['heads']}
            _recover_secondary_beam_voice_ownership(staves,head_rhythms,lines,chars)
            _recover_explicit_physical_rhythms(staves,head_rhythms,lines,chars)
            _recover_shared_beamed_chord_heads(staves,head_rhythms,lines,chars)
            _recover_explicit_short_quarters(staves,head_rhythms,lines,chars)
            hand_overrides=cross_staff_beam_hands(staves,head_rhythms,lines)
            for staff_index,staff in enumerate(staves):
                gap = staff["gap"]
                notes = staff["heads"]
                staff_rests = [c for c in staff["chars"] if c["char"] in RESTS.keys()|UNKNOWN_RESTS|{MEASURE_REST}]
                if not notes and not staff_rests:
                    tuplet_continuations.pop(staff.get('hand'),None)
                    continue
                first_x = min(c["x"] for c in notes+staff_rests)
                keys, key_map = _opening_key_signature(staff, notes+staff_rests, project["staves"])
                meter_changes=_meter_changes(staff,staff['chars'])
                opening_meters=[change for change in meter_changes if change['x']<first_x]
                meter=opening_meters[-1]['beats'] if opening_meters else None
                meter_evidence=opening_meters[-1]['evidence'] if opening_meters else None
                # Meter normally appears only at the first system; inherit verified value.
                if meter is None:
                    for previous_staff in reversed(project['staves']):
                        same_system=(previous_staff['page']==page_index+1 and previous_staff['system']==staff['system'])
                        meter=previous_staff.get('meter_beats') if same_system else previous_staff.get('ending_meter_beats',previous_staff.get('meter_beats'))
                        if meter is not None:
                            break
                staff["meter_beats"] = meter
                inherited_meter_evidence=meter_evidence
                if inherited_meter_evidence is None:
                    previous_meter=next((s for s in reversed(project['staves']) if s.get('hand')==staff.get('hand')),None)
                    if previous_meter is not None:
                        inherited_meter_evidence=previous_meter.get('ending_meter_evidence',previous_meter.get('meter_evidence'))
                later_digits=[c for c in staff["chars"] if c["char"] in METER_DIGITS
                              and c["size"]>1.5*gap and c["x"]>first_x]
                staff["later_meter_change"]=any(abs(a["y"]-staff["top"]-gap)<.5*gap
                    and abs(b["y"]-staff["top"]-3*gap)<.5*gap and abs(a["x"]-b["x"])<2*gap
                    for a in later_digits for b in later_digits) or any(c["char"] in "ƊƋ" and c["x"]>first_x for c in staff["chars"])
                bars = sorted({round(x1, 1) for x1,y1,x2,y2,w in lines
                               if abs(x1-x2)<.2 and min(y1,y2)<=staff["top"]+.2*gap
                               and max(y1,y2)>=staff["bottom"]-.2*gap
                               and staff["left"]-.3*gap<=x1<=staff["right"]+.3*gap
                               # Long stems can span all five lines, but touch a head.
                               and not any(-.35*gap < x1-h["x"] < 1.65*gap
                                           and min(y1,y2)-.35*gap<h["y"]<max(y1,y2)+.35*gap
                                           for other in staves for h in other['heads'])})
                bars = [b for n,b in enumerate(bars) if n == 0 or b-bars[n-1] > gap]
                if not bars or bars[0]>first_x:
                    bars.insert(0, staff["left"])
                if bars[-1]<staff["right"]-gap:
                    bars.append(staff["right"])
                bars=_trim_opening_repeat_prefix(staff,lines,bars,notes+staff_rests)
                measure_meters=[]
                measure_meter_evidences=[]
                current_meter=meter
                current_meter_evidence=inherited_meter_evidence
                for measure in range(len(bars)-1):
                    changes=[c for c in meter_changes if bars[measure]-.3*gap<=c['x']<bars[measure+1]]
                    if changes:
                        current_meter=changes[-1]['beats']
                        current_meter_evidence=changes[-1]['evidence']
                    measure_meters.append(current_meter)
                    measure_meter_evidences.append(current_meter_evidence)
                staff['ending_meter_beats']=current_meter
                octaves = [c for c in chars+text_octaves if c["char"] in ("ƴ", "Ƶ") or c in text_octaves]
                octaves = [c for c in octaves
                           if staff["top"]-10*gap<c["y"]<staff["bottom"]+(10 if _explicit_lower_octave(c) else 3)*gap
                           and _octave_marker_staff(c,staves) is staff]
                octave_regions=_octave_regions(staff,octaves,lines)
                project["octave_regions"].extend({**region,"staff":staff["id"],"page":page_index+1,"system":staff["system"]}
                                                 for region in octave_regions)
                staff_events = []
                accidental_state = {}
                last_measure = -1
                for head in sorted(notes, key=lambda n:(n["x"],n["y"])):
                    measure = max(0, sum(head["x"] >= b+.15*gap for b in bars)-1)
                    if measure != last_measure:
                        accidental_state = {}
                        last_measure = measure
                    issues = []
                    if staff.get('outside_piano'):
                        issues.append('excluded_non_piano_staff')
                    elif staff["hand"] is None:
                        issues.append("cross_staff_hand_unresolved")
                    staff_evidence=head_owners[id(head)][1]
                    if staff_evidence and staff_evidence["nearest_staff_reassigned"]:
                        issues.append("ledger_staff_assignment_requires_review")
                    ambiguous_staff=bool(staff_evidence and staff_evidence.get("ambiguous"))
                    if ambiguous_staff:
                        issues.append("ledger_staff_assignment_unresolved")
                    clefs = [c for c in staff["clefs"] if c["x"] <= head["x"]]
                    clef = CLEFS[clefs[-1]["char"]] if clefs else staff["clef"]
                    step_float = (staff["bottom"]-head["y"])/(gap/2)
                    step = round(step_float)
                    pitch = midi = None
                    if clef and abs(step-step_float) < .18:
                        diatonic = (30 if clef == "treble" else 18)+step  # E4 / G2 bottom line
                        octave, letter_index = divmod(diatonic, 7)
                        letter = LETTERS[letter_index]
                        local = [c for c in staff["chars"] if c["char"] in ACCIDENTALS
                                 and .15*gap < head["x"]-c["x"] < 2.3*gap
                                 and abs(c["y"]-head["y"]) < .3*gap and c not in keys]
                        if local:
                            accidental_state[(letter,octave)] = ACCIDENTALS[max(local,key=lambda c:c["x"])["char"]]
                        alter = accidental_state.get((letter,octave), key_map.get(letter,0))
                        midi = 12*(octave+1)+SEMITONES[letter_index]+alter
                        pitch = letter+({-2:"bb",-1:"b",0:"",1:"#",2:"##"}[alter])+str(octave)
                    else:
                        issues.append("clef_or_staff_position_unresolved")
                    duration, rhythm, rhythm_issues = head_rhythms[id(head)]
                    issues.extend(rhythm_issues)
                    if head['size']<1.7*gap:
                        issues.append('grace_or_cue_note_requires_review' if _has_grace_slash(rhythm,lines,gap)
                                      else 'small_notated_note_requires_review')
                    if any(c["char"] in ARPEGGIOS and .3*gap<head["x"]-c["x"]<3*gap
                           and abs(c["y"]-head["y"])<5*gap for c in staff["chars"]):
                        issues.append("arpeggio_requires_review")
                    written_pitch=pitch
                    octave_shift,octave_evidence=_octave_at(head["x"],octave_regions,gap)
                    if octave_shift is None:
                        issues.append("octave_line_extent_unresolved")
                    elif octave_shift and pitch is not None:
                        midi+=octave_shift
                        pitch=letter+({-2:"bb",-1:"b",0:"",1:"#",2:"##"}[alter])+str(octave+octave_shift//12)
                        issues.append("octave_line_requires_review")
                    nearby_curves = [b for b in curves if b[2]-b[0]>2*gap and b[3]-b[1]<4*gap
                                     and b[0]-gap<head["x"]<b[2]+gap
                                     and abs((b[1]+b[3])/2-head["y"])<8*gap]
                    if nearby_curves:
                        issues.append("tie_or_slur_requires_review")
                    event = {"id": f"p{page_index+1}-n{len(project['notes'])+len(staff_events)+1}",
                             "page":page_index+1, "bbox":_round_box([head["x"]-.2*gap,head["y"]-.55*gap,
                                                                        head["x"]+1.4*gap,head["y"]+.55*gap]),
                             "glyph_bbox":_round_box(head["bbox"]), "origin":[round(head["x"],3),round(head["y"],3)],
                             "staff":staff["id"], "system":staff["system"], "measure":measure+1,
                             "staff_evidence":staff_evidence,
                             "hand":None if ambiguous_staff else staff["hand"], "clef":clef,
                             "pitch":pitch if octave_shift is not None and not ambiguous_staff else None,
                             "pitch_candidate":pitch,"written_pitch":written_pitch,"octave_shift":octave_shift,
                             "octave_evidence":octave_evidence,"midi":midi if octave_shift is not None and not ambiguous_staff else None,
                             "duration":duration, "beats":duration, "measure_beat":None,
                             "beat":None, "start_beat":None, "written_beat":None,
                             "finger":None, "finger_source":None, "finger_candidates":[], "rhythm_evidence":rhythm,
                             "confidence":.85, "issues":issues, "confirmed":False}
                    if id(head) in hand_overrides and not ambiguous_staff:
                        evidence=hand_overrides[id(head)]
                        event.update(hand=evidence['hand'],voice_staff=evidence['voice_staff'],
                                     hand_evidence={k:v for k,v in evidence.items() if k not in ('hand','voice_staff')})
                        event['issues'].append('cross_staff_beam_voice_requires_review')
                    if staff.get('outside_piano'):
                        event.update(excluded=True, staff_role='outside_piano')
                    staff_events.append(event)
                _apply_printed_tuplets(staff_events,staff,lines,text_chars)
                _apply_printed_hand_labels(staff_events,staff,text_chars)
                upper = staff['upper_partner']
                if upper is not None and not any(c['char'] in RESTS.keys()|UNKNOWN_RESTS|{MEASURE_REST}
                                                for c in staves[upper]['chars']):
                    staff['shared_hands_resolved']=_shared_staff_hands(staff_events,gap,staves[upper]['heads'])
                # Finger groups are attached by horizontal alignment, then vertical order.
                groups = _event_groups(staff_events,gap)
                finger_groups=[]
                for group in groups:
                    if any(e.get('hand_evidence') for e in group):
                        finger_groups.extend([e for e in group if e['hand']==hand] for hand in ('right','left'))
                    else:
                        finger_groups.append(group)
                for group in filter(None,finger_groups):
                    finger_jobs.append((staff,group,finger_groups))
                measures = []
                for measure in range(len(bars)-1):
                    measure_meter=measure_meters[measure]
                    m_groups = [g for g in groups if g[0]["measure"]==measure+1]
                    rests = [c for c in staff_rests if bars[measure]<c["x"]<bars[measure+1]]
                    rest_events=[]
                    for r in rests:
                        duration,evidence=_rest_duration(r,gap,staff["chars"],measure_meter,not m_groups and len(rests)==1)
                        rest_events.append({"id":f"p{page_index+1}-r{len(project['rests'])+len(rest_events)+1}",
                            "page":page_index+1,"system":staff["system"],"staff":staff["id"],
                            "hand":staff["hand"],"measure":measure+1,"origin":[round(r["x"],3),round(r["y"],3)],
                            "bbox":_round_box(r["bbox"]),"duration":duration,"duration_beats":duration,
                            "measure_beat":None,"beat":None,"written_beat":None,"rhythm_evidence":evidence,
                            "confirmed":False,"issues":[] if duration is not None else ["rest_duration_unresolved"]})
                    _apply_bracketed_tuplets([e for g in m_groups for e in g],rest_events,staff,lines,text_chars)
                    _apply_omitted_tuplet_numbers([e for g in m_groups for e in g],rest_events,staff,lines,
                        measure_meter,measure_meter_evidences[measure],measure+1,len(bars)-1,tuplet_continuations)
                    timeline = [(g[0]["origin"][0],g, {e["duration"] for e in g}) for g in m_groups]
                    timeline.extend((r["origin"][0],[r],{r["duration"]}) for r in rest_events)
                    timeline.sort(key=lambda t:t[0])
                    simple = bool(timeline) and all(len(d)==1 and None not in d for _,_,d in timeline)
                    total = sum(next(iter(d)) for _,_,d in timeline) if simple else None
                    tremolo=_resolve_mixed_tremolo_measure([e for g in m_groups for e in g],rest_events,
                                                           staff,measure_meter,lines)
                    if tremolo is not None:
                        total=tremolo['total_beats']
                    elif simple and measure_meter is not None and abs(total-measure_meter)<.01:
                        beat = 0.0
                        for _,group,durations in timeline:
                            for e in group:
                                e["measure_beat"] = round(beat,6)
                            beat += next(iter(durations))
                    else:
                        for group in m_groups:
                            for e in group:
                                e["issues"].append("measure_timing_unresolved")
                        for rest in rest_events:
                            rest["issues"].append("measure_timing_unresolved")
                    resolved=tremolo is not None or (simple and measure_meter is not None and abs(total-measure_meter)<.01)
                    voices=None
                    if not resolved:
                        voices=_resolve_explicit_voices([e for g in m_groups for e in g],rest_events,staff,measure_meter)
                        if voices is not None:
                            resolved=True
                    if not resolved:
                        tremolo=_resolve_two_note_tremolo([e for g in m_groups for e in g],rest_events,staff,measure_meter,lines)
                        resolved=tremolo is not None
                    measure_record={"measure":measure+1,"total_beats":total,"timing_resolved":resolved,
                                    "length_beats":measure_meter if resolved else None,"meter_beats":measure_meter}
                    if voices is not None:
                        measure_record.update(timing_method="explicit_voices",voices=voices)
                    if tremolo is not None:
                        measure_record.update(timing_method='measured_tremolo',tremolo_evidence=tremolo)
                    measures.append(measure_record)
                    project["rests"].extend(rest_events)
                staff["measures"]=measures
                staff["bars"]=bars
                if staff["hand"]=="right" or staff.get('shared_hands_resolved'):
                    project["repeat_markers"].extend({**mark,"page":page_index+1,"system":staff["system"],
                        "staff":staff["id"],"written_beat":None} for mark in _repeat_marks(staff,lines,bars)
                        if not any(m['page']==page_index+1 and m['system']==staff['system']
                            and m['kind']==mark['kind'] and m['boundary']==mark['boundary'] for m in project['repeat_markers']))
                    project["ending_brackets"].extend({**bracket,"page":page_index+1,"system":staff["system"],
                        "staff":staff["id"]} for bracket in _ending_brackets(staff,lines,bars))
                    if any(c["char"] in ("ư","Ʊ") and staff["top"]-10*gap<c["y"]<staff["bottom"]+4*gap
                           for c in chars):
                        project["repeat_review_issues"].append(f"{staff['id']}: navigation sign requires manual performance order")
                _annotate_ties(staff_events,curves,gap)
                project["notes"].extend(staff_events)
                project["staves"].append({"id":staff["id"],"page":page_index+1,"system":staff["system"],
                                          "hand":staff["hand"],"clef":staff["clef"],"meter_beats":meter,
                                          "ending_meter_beats":current_meter,"ending_meter_evidence":current_meter_evidence,"meter_changes":meter_changes,
                                          "meter_evidence":meter_evidence,
                                          "measure_count":len(bars)-1,
                                          "measures":measures,
                                          "key_signature":key_map,"lines":[round(staff["top"]+k*gap,3) for k in range(5)],
                                          "bbox":_round_box([staff["left"],staff["top"],staff["right"],staff["bottom"]]),
                                          "bars":bars})
            # Written score coordinates advance across verified complete measures.
            # A repeat bar changes performance order, not the position of printed
            # notes. Record it separately; do not erase an independently known beat.
            _assign_page_fingerings(finger_jobs,staves,chars,head_rhythms,text_chars)
            refine_fingering_evidence(finger_jobs,staves,chars,head_rhythms,text_chars,lines)
            _protect_unowned_partial_chord_finger_evidence(finger_jobs,chars)
            _disambiguate_foreign_free_stem_digits(finger_jobs,chars,lines)
            for system_number in range(1, system+2):
                system_staves = [s for s in staves if s["system"] == system_number]
                system_notes = [e for e in project["notes"] if e["page"]==page_index+1 and e["system"]==system_number]
                meters = {s.get("meter_beats") for s in system_staves if s.get("meter_beats") is not None}
                count=max((len(s.get("measures",[])) for s in system_staves),default=0)
                meter=next(iter(meters)) if len(meters)==1 else None
                events=system_notes+[r for r in project["rests"] if r["page"]==page_index+1 and r["system"]==system_number]
                _align_shared_staff_onsets(system_staves,events)
                _recover_grace_principal_timing(system_staves,events,lines)
                _mark_unresolved_slashed_graces(system_staves,events,lines)
                _recover_clear_beam_family(system_staves,events,lines,chars,text_chars)
                _recover_beam_from_physical_stems(system_staves,events,lines,chars,text_chars)
                _propagate_beamed_onsets(system_staves,events,lines)
                if page_index==0 and system_number==1 and global_measure_base==0:
                    pickup=_resolve_pickup(system_staves,events,meter)
                    if pickup is not None:
                        project["pickup_beats"]=pickup
                for measure in range(1,count+1):
                    global_measure_index += 1
                    measure_meters={m.get('meter_beats',s.get('meter_beats')) for s in system_staves
                                    for m in s.get('measures',[]) if m['measure']==measure}
                    meter=next(iter(measure_meters)) if len(measure_meters)==1 else None
                    verified=bool(meter) and any(m["measure"]==measure and m["timing_resolved"]
                        for s in system_staves for m in s.get("measures",[]))
                    metric_extent=None
                    if not verified:
                        boundary_exception=any(m["page"]==page_index+1 and m["system"]==system_number
                            and m["boundary"] in (measure-1,measure) for m in project["repeat_markers"])
                        ending_exception=any(b["page"]==page_index+1 and b["system"]==system_number
                            and b["start_boundary"]<=measure-1<b["end_boundary"] for b in project["ending_brackets"])
                        excluded=(nonmetric_or_navigation or page_count is None or boundary_exception or ending_exception
                            or (page_index==0 and system_number==1 and measure==1)
                            or (page_index+1==page_count and system_number==system+1 and measure==count))
                        metric_extent=_ordinary_metric_extent(system_staves,lines,measure,meter,excluded)
                        if metric_extent is not None:
                            for s in system_staves:
                                for record in s.get("measures",[]):
                                    if record["measure"]==measure:
                                        record["metric_extent_evidence"]=metric_extent
                    # A complete voice or a whole-measure rest establishes the
                    # bar length. Unknown/pickup bars still stop propagation.
                    markers=[m for m in project["repeat_markers"] if m["page"]==page_index+1
                             and m["system"]==system_number and m["boundary"]==measure-1]
                    for mark in markers:
                        if global_timing_open:
                            mark["written_beat"]=round(global_measure_base,6)
                    if global_timing_open:
                        for bracket in project["ending_brackets"]:
                            if bracket["page"]==page_index+1 and bracket["system"]==system_number:
                                for field in ("start","end"):
                                    if bracket[field+"_boundary"]==measure-1:
                                        bracket[field+"_beat"]=round(global_measure_base,6)
                    for event in [e for e in events if e["measure"]==measure]:
                        event['global_measure_index']=global_measure_index
                        event['measure_start_beat']=round(global_measure_base,6) if global_timing_open else None
                        event['meter_beats']=meter
                        if event.get('main_anchor_measure_beat') is not None:
                            event['main_anchor_beat']=(round(global_measure_base+event['main_anchor_measure_beat'],6)
                                                       if global_timing_open else None)
                        if global_timing_open and event["measure_beat"] is not None:
                            event["written_beat"] = round(global_measure_base+event["measure_beat"],6)
                        # A slur/fingering review does not invalidate an independently
                        # verified rhythmic position. Keep those review warnings.
                        timing_blockers = {"measure_timing_unresolved", "rest_duration_unresolved", "grace_or_cue_note_requires_review",
                                           "stem_not_resolved", "rhythm_geometry_conflict", "flag_anchor_unresolved",
                                           "beam_attachment_ambiguous", "beam_spacing_conflict", "ledger_staff_assignment_unresolved",
                                           "cross_staff_hand_unresolved"}
                        if event["written_beat"] is not None and not timing_blockers.intersection(event["issues"]):
                            event["beat"] = event["start_beat"] = event["written_beat"]
                        if event["beat"] is None:
                            event["issues"].append("global_timing_requires_review")
                            if "confidence" in event:
                                event["confidence"] = min(event["confidence"],.55)
                    if verified:
                        lengths={m["length_beats"] for s in system_staves for m in s.get("measures",[])
                                 if m["measure"]==measure and m["timing_resolved"]}
                        if len(lengths)==1:
                            global_measure_base += next(iter(lengths))
                        else:
                            global_timing_open=False
                    elif metric_extent is not None:
                        # Advance only the bar boundary. All unresolved local
                        # note/rest onsets and their review guards stay unknown.
                        global_measure_base+=metric_extent["quarter_beats"]
                    else:
                        global_timing_open=False
                for mark in project["repeat_markers"]:
                    if mark["page"]==page_index+1 and mark["system"]==system_number and mark["boundary"]==count:
                        if global_timing_open:
                            mark["written_beat"]=round(global_measure_base,6)
                if global_timing_open:
                    for bracket in project["ending_brackets"]:
                        if bracket["page"]==page_index+1 and bracket["system"]==system_number and bracket["end_boundary"]==count:
                            bracket["end_beat"]=round(global_measure_base,6)
            annotate_performance_page(project,page_index+1,staves,chars,text_chars,lines,curves)
            _notify_conversion_progress("recognizing",label="识别原谱",page_done=page_index+1,page_total=page_count)
    _notify_conversion_progress("postprocess",label="整理识别结果")
    finalize_performance_spans(project)
    pending=None
    for index,mark in enumerate(project["repeat_markers"]):
        if mark["kind"]=="start":
            if pending is not None:
                project["issues"].append("Nested or multiple repeat starts require manual repeat sections.")
                project["repeat_review_issues"].append("Nested or multiple repeat starts")
            pending=(index,mark)
        else:
            start=pending[1]["written_beat"] if pending else 0.0
            end=mark["written_beat"]
            if start is not None and end is not None and end>start:
                project["repeat_sections"].append({"start_beat":start,"end_beat":end,"count":2,
                    "confirmed":False,"marker_indices":[pending[0],index] if pending else [index]})
            pending=None
    if pending is not None:
        project["repeat_review_issues"].append("Repeat start has no resolved matching repeat end")
    assigned_brackets=set()
    for section in project["repeat_sections"]:
        first=[(i,b) for i,b in enumerate(project["ending_brackets"]) if b["end_beat"]==section["end_beat"]
               and b["start_beat"] is not None and section["start_beat"]<b["start_beat"]<section["end_beat"]]
        second=[(i,b) for i,b in enumerate(project["ending_brackets"]) if b["start_beat"]==section["end_beat"]
                and b["end_beat"] is not None and b["end_beat"]>section["end_beat"]]
        if len(first)==len(second)==1:
            section.update(first_ending_start_beat=first[0][1]["start_beat"],
                           second_ending_end_beat=second[0][1]["end_beat"],ending_numbers_require_review=True)
            assigned_brackets.update((first[0][0],second[0][0]))
    if len(assigned_brackets)!=len(project["ending_brackets"]):
        project["repeat_review_issues"].append("Unresolved ending brackets require manual performance order")
    project["written_duration_beats"] = round(global_measure_base,6) if global_timing_open else None
    project["summary"] = {"pages":len(project["pages"]),"notes":len(project["notes"]),
                          "with_finger":sum(n["finger"] is not None for n in project["notes"]),
                          "with_pitch":sum(n["pitch"] is not None for n in project["notes"]),
                          "with_duration":sum(n["duration"] is not None for n in project["notes"]),
                          "with_measure_beat":sum(n["measure_beat"] is not None for n in project["notes"]),
                          "with_global_beat":sum(n["beat"] is not None for n in project["notes"])}
    return project


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--out")
    args = parser.parse_args()
    encoded = json.dumps(recognize(args.pdf), ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        Path(args.out).write_text(encoded, encoding="utf-8")
    else:
        print(encoded)
