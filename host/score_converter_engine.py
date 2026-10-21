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

DIGITS = {chr(0x130 + n): n for n in range(1, 10)}
METER_DIGITS = {chr(0x130 + n): n for n in range(10)}
HEADS = {"Ŵ": "filled", "ż": "open", "Ł": "whole"}
CLEFS = {"ƀ": "treble", "Ɓ": "bass"}
ACCIDENTALS = {"ġ": 1, "Ģ": -1, "ģ": 0, "Ĥ": 2}
FLAGS = {"ř": 1, "ŉ": 1, "Ś": 2, "Ŋ": 2}
RESTS = {"Ţ": 2.0, "ţ": 1.0, "Ť": 0.5, "ť": 0.25}
MEASURE_REST = "š"
UNKNOWN_RESTS = set()
ARPEGGIOS = {"Ƭ"}
LETTERS = "CDEFGAB"
SEMITONES = [0, 2, 4, 5, 7, 9, 11]


def _round_box(box):
    return [round(float(x), 3) for x in box]


def _chars(page):
    return page.chars()


def _geometry(page):
    return page.geometry()


def _staves(lines, page_width):
    horizontal = sorted((min(x1, x2), y1, max(x1, x2))
                        for x1, y1, x2, y2, width in lines
                        if abs(y1 - y2) < 0.15 and abs(x2 - x1) > page_width * .4
                        and width < 1.5)
    unique = []
    for line in horizontal:
        if not any(abs(line[1] - u[1]) < .2 and abs(line[0] - u[0]) < 2 for u in unique):
            unique.append(line)
    unique.sort(key=lambda x: x[1])
    output, consumed = [], set()
    for i, first in enumerate(unique):
        if i in consumed:
            continue
        for j in range(i + 1, min(i + 5, len(unique))):
            gap = unique[j][1] - first[1]
            if not 2 <= gap <= 15:
                continue
            candidates = []
            for k in range(5):
                match = next((n for n, u in enumerate(unique) if n not in consumed
                              and abs(u[1] - first[1] - k * gap) < .25
                              and abs(u[0] - first[0]) < 2 and abs(u[2] - first[2]) < 2), None)
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


def _head_staff(head, staves, lines):
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
    return nearest,None


def _stem_beams(stem, head_y, gap, lines):
    """Count the attached parallel family, not another voice crossing the stem."""
    end=stem[1] if abs(head_y-stem[1])>abs(head_y-stem[2]) else stem[2]
    direction=1 if end<head_y else -1
    candidates=[]
    for x1,y1,x2,y2,width in lines:
        if abs(x2-x1)<gap or not .3*gap<=width<=.9*gap:
            continue
        if min(x1,x2)-.2*gap<=stem[0]<=max(x1,x2)+.2*gap:
            slope=(y2-y1)/(x2-x1)
            yy=y1+slope*(stem[0]-x1)
            if -.6*gap<=direction*(yy-end)<=2.2*gap:
                candidates.append((yy,slope))
    attached=[item for item in candidates if abs(item[0]-end)<=.6*gap]
    if not attached:
        return 0,[],[]
    primary=min(attached,key=lambda item:abs(item[0]-end))
    competing=[item for item in attached if abs(item[0]-end)<=abs(primary[0]-end)+.08*gap
               and abs(item[1]-primary[1])>.025]
    if competing:
        return None,[],["beam_attachment_ambiguous"]
    ys=[]
    for yy,slope in candidates:
        if abs(slope-primary[1])<.015 and not any(abs(yy-value)<.25*gap for value in ys):
            ys.append(yy)
    ordered=sorted(ys)
    if any(not .4*gap<=b-a<=gap for a,b in zip(ordered,ordered[1:])):
        return None,[],["beam_spacing_conflict"]
    return len(ys),[round(y,3) for y in sorted(ys)],[]


def _is_score_head(char, staff, lines):
    """Reject metronome noteheads floating above the staff without ledger lines."""
    gap, y, x = staff["gap"], char["y"], char["x"]
    if staff["top"]-.75*gap <= y <= staff["bottom"]+.75*gap:
        return True
    return any(abs(y1-y2)<.2 and gap < abs(x2-x1) < 5*gap
               and min(x1,x2)-.2*gap <= x <= max(x1,x2)
               and min(y,staff["top"]) -.2*gap <= y1 <= max(y,staff["bottom"])+.2*gap
               and (y1 < staff["top"]-.5*gap or y1 > staff["bottom"]+.5*gap)
               for x1,y1,x2,y2,width in lines)


def _stem_and_duration(head, staff, lines, chars):
    x, y, gap = head["x"], head["y"], staff["gap"]
    if head["char"] == "Ł":
        return 4.0, {"head": "whole", "beams": 0}, []
    stems = [(x1, min(y1, y2), max(y1, y2)) for x1, y1, x2, y2, w in lines
             if abs(x1-x2) < .2 and abs(y1-y2) >= 2*gap and abs(y1-y2) < 10*gap
             and x-.3*gap <= x1 <= x+1.6*gap
             and min(y1,y2)-.35*gap <= y <= max(y1,y2)+.35*gap]
    if not stems:
        return None, {"head": HEADS[head["char"]]}, ["stem_not_resolved"]
    stem = min(stems, key=lambda v: min(abs(y-v[1]), abs(y-v[2])))
    end = stem[1] if abs(y-stem[1]) > abs(y-stem[2]) else stem[2]
    beam_count,beam_ys,beam_issues=_stem_beams(stem,y,gap,lines)
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
    if beams > 3 or (head["char"] == "ż" and beams):
        return None, {"head": HEADS[head["char"]], "beams": beams}, ["rhythm_geometry_conflict"]
    value = 2.0 if head["char"] == "ż" else 1.0/(2**beams)
    # A dot must sit beyond the physical notehead, not merely its font advance.
    dots = [c for c in chars if c["char"] == "Ǉ" and .8*gap < c["x"]-x < 3.4*gap
            and abs(c["y"]-y) <= .6*gap]
    if dots:
        if len(dots) == 1:
            value *= 1.5
        else:
            issues.append("multiple_dots_require_review")
            value = None
    return value, {"head": HEADS[head["char"]], "beams": beams,
                   "dots": len(dots), "stem": _round_box(stem),
                   "stem_direction":"up" if end<y else "down",
                   "flag_bboxes": [_round_box(c["bbox"]) for c in flags if c.get("bbox")]}, issues


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


def _octave_regions(staff, markers, lines):
    """Resolve an 8va only with an attached dash chain and a bounded endpoint."""
    gap=staff["gap"]
    regions=[]
    for marker in markers:
        region={"start_x":marker["x"],"end_x":staff["right"],"shift":None,
                "marker_bbox":_round_box(marker["bbox"]),"glyph":marker["char"]}
        # The above-staff ƴ glyph was visually verified as 8va. Other octave
        # symbols/placements keep an explicit unknown rather than guessing.
        if marker["char"]!="ƴ" or marker["y"]>=staff["top"]-.5*gap:
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
              and abs(min(y1,y2)-y)<.3*gap and .3*gap<abs(y1-y2)<3*gap
              and 0<=x1-right<1.5*gap]
        endpoint=min(caps) if caps else staff["right"] if abs(right-staff["right"])<gap else None
        if endpoint is not None:
            region.update(end_x=endpoint,shift=12,dash_count=len(chain),dash_y=round(y,3),
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


def _repeat_marks(staff, lines, bars):
    """Recognize repeat dot pairs beside a thick bar, not ordinary final bars."""
    gap = staff["gap"]
    heavy = [x1 for x1,y1,x2,y2,width in lines if abs(x1-x2)<.2
             and width>=.3*gap and min(y1,y2)<=staff["top"]+.2*gap
             and max(y1,y2)>=staff["bottom"]-.2*gap]
    dots = [(x1,y1) for x1,y1,x2,y2,width in lines
            if abs(x1-x2)<.15*gap and abs(y1-y2)<.15*gap and .2*gap<=width<=.7*gap]
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
    if len(by_voice)<2 or not opposed:
        return None
    timelines={}
    for key,items in by_voice.items():
        timelines[key]=[(g[0]["origin"][0],g,{e["duration"] for e in g}) for g in _event_groups(items,gap)]
    for rest in rests:
        y=rest["origin"][1]
        key="up" if y<staff["top"]+gap else "down" if y>staff["top"]+3*gap else None
        if key in timelines:
            timelines[key].append((rest["origin"][0],[rest],{rest["duration"]}))
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
    return summaries


def _ordinary_metric_extent(staves, lines, measure, meter, excluded=False):
    """The extent of an ordinary metered bar is independent of parsed voices."""
    if excluded or meter is None or len(staves)!=2:
        return None
    gap=median(s["gap"] for s in staves)
    if any(len(s.get("bars",[]))<=measure or s.get("later_meter_change") for s in staves):
        return None
    boundaries=[s["bars"][measure-1:measure+1] for s in staves]
    if any(abs(a-b)>.3*gap for a,b in zip(*boundaries)):
        return None
    records=[next((m for m in s.get("measures",[]) if m["measure"]==measure),None) for s in staves]
    totals=[m.get("total_beats") if m else None for m in records]
    # A coherent paired short/irregular bar is positive evidence against the
    # ordinary full-bar rule. A recognizer's isolated voice-sum conflict is not
    # evidence that the printed meter changed.
    if (all(t is not None for t in totals) and abs(totals[0]-totals[1])<1e-6
        and abs(totals[0]-meter)>.01):
        return None
    top=min(s["top"] for s in staves);bottom=max(s["bottom"] for s in staves)
    for boundary in boundaries[0]:
        if not any(abs(x1-x2)<.2 and abs(x1-boundary)<.2*gap and 0<width<.25*gap
                   and min(y1,y2)<=top+.2*gap and max(y1,y2)>=bottom-.2*gap
                   for x1,y1,x2,y2,width in lines):
            return None
    return {"method":"explicit_meter_shared_ordinary_barlines","quarter_beats":meter,
            "boundary_x":boundaries[0],"local_note_onsets_verified":False}


def recognize(path):
    """Return a JSON-safe review project. Unknown values are None, never guessed."""
    path = Path(path)
    project = {"schema_version": 1, "recognizer": "aloisen-vector-review-v3",
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
    global_timing_open = True
    with open_document(path) as document:
        underlying=getattr(document,"document",None)
        page_count=len(underlying) if underlying is not None else None
        for page_index, page in enumerate(document):
            chars = _chars(page)
            lines, curves = _geometry(page)
            staves = _staves(lines, page.rect.width)
            head_owners={id(c):_head_staff(c,staves,lines) for c in chars if c["char"] in HEADS}
            owners={id(c):(head_owners[id(c)][0] if c["char"] in HEADS else _nearest_staff(c,staves)) for c in chars}
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
                continue
            system = -1
            previous = None
            for i, staff in enumerate(staves):
                gap = staff["gap"]
                if previous is None or i % 2 == 0 or staff["top"]-previous["top"] > 22*gap:
                    system += 1
                    hand = "right"
                else:
                    hand = "left"
                staff.update(id=f"p{page_index+1}-s{i+1}", hand=hand, system=system+1)
                staff["chars"] = [c for c in chars if owners[id(c)] is staff]
                staff["heads"] = [c for c in staff["chars"] if c["char"] in HEADS
                                  and _is_score_head(c,staff,lines)]
                clefs = [c for c in staff["chars"] if c["char"] in CLEFS]
                staff["clef"] = CLEFS[clefs[0]["char"]] if clefs else None
                staff["clefs"] = clefs
                previous = staff
            for i, staff in enumerate(staves):
                if i % 2 == 1 and not staves[i-1]["heads"] and staff["heads"]:
                    staff["hand"] = None  # Common piano cross-staff notation; don't invent hands.
            used_fingers = set()
            for staff in staves:
                gap = staff["gap"]
                notes = staff["heads"]
                staff_rests = [c for c in staff["chars"] if c["char"] in RESTS.keys()|UNKNOWN_RESTS|{MEASURE_REST}]
                if not notes and not staff_rests:
                    continue
                first_x = min(c["x"] for c in notes+staff_rests)
                keys = [c for c in staff["chars"] if c["char"] in ("ġ", "Ģ")
                        and c["x"] < first_x-2*gap]
                key_map = {}
                if keys and len({c["char"] for c in keys}) == 1 and len(keys) <= 7:
                    order = "FCGDAEB" if keys[0]["char"] == "ġ" else "BEADGCF"
                    key_map = {letter: ACCIDENTALS[keys[0]["char"]] for letter in order[:len(keys)]}
                digits = [c for c in staff["chars"] if c["char"] in METER_DIGITS
                          and c["size"] > gap*1.5 and c["x"] < first_x]
                meter,meter_evidence = _meter_signature(staff,digits)
                if any(c["char"] == "Ɗ" and c["x"] < first_x for c in staff["chars"]):
                    meter = 4.0  # Visually verified Aloisen common-time glyph.
                # Meter normally appears only at the first system; inherit verified value.
                if meter is None:
                    meter = next((s.get("meter_beats") for s in reversed(project["staves"])
                                  if s.get("meter_beats") is not None), None)
                staff["meter_beats"] = meter
                later_digits=[c for c in staff["chars"] if c["char"] in METER_DIGITS
                              and c["size"]>1.5*gap and c["x"]>first_x]
                staff["later_meter_change"]=any(abs(a["y"]-staff["top"]-gap)<.5*gap
                    and abs(b["y"]-staff["top"]-3*gap)<.5*gap and abs(a["x"]-b["x"])<2*gap
                    for a in later_digits for b in later_digits) or any(c["char"]=="Ɗ" and c["x"]>first_x for c in staff["chars"])
                bars = sorted({round(x1, 1) for x1,y1,x2,y2,w in lines
                               if abs(x1-x2)<.2 and min(y1,y2)<=staff["top"]+.2*gap
                               and max(y1,y2)>=staff["bottom"]-.2*gap
                               and staff["left"]-.3*gap<=x1<=staff["right"]+.3*gap
                               # Long stems can span all five lines, but touch a head.
                               and not any(-.35*gap < x1-h["x"] < 1.65*gap
                                           and min(y1,y2)-.35*gap<h["y"]<max(y1,y2)+.35*gap
                                           for h in notes)})
                bars = [b for n,b in enumerate(bars) if n == 0 or b-bars[n-1] > gap]
                if not bars or bars[0]>first_x:
                    bars.insert(0, staff["left"])
                if bars[-1]<staff["right"]-gap:
                    bars.append(staff["right"])
                bars=_trim_opening_repeat_prefix(staff,lines,bars,notes+staff_rests)
                octaves = [c for c in chars if c["char"] in ("ƴ", "Ƶ")
                           and staff["top"]-10*gap<c["y"]<staff["bottom"]+3*gap
                           and min(staves,key=lambda s:abs(c["y"]-(s["top"]+s["bottom"])/2)) is staff]
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
                    if staff["hand"] is None:
                        issues.append("cross_staff_hand_unresolved")
                    staff_evidence=head_owners[id(head)][1]
                    if staff_evidence and staff_evidence["nearest_staff_reassigned"]:
                        issues.append("ledger_staff_assignment_requires_review")
                    ambiguous_staff=bool(staff_evidence and staff_evidence.get("ambiguous"))
                    if ambiguous_staff:
                        issues.append("ledger_staff_assignment_unresolved")
                    if head["size"] < 1.7*gap:
                        issues.append("grace_or_cue_note_requires_review")
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
                        pitch = letter+({-1:"b",0:"",1:"#",2:"##"}[alter])+str(octave)
                    else:
                        issues.append("clef_or_staff_position_unresolved")
                    duration, rhythm, rhythm_issues = _stem_and_duration(head,staff,lines,chars)
                    issues.extend(rhythm_issues)
                    if any(c["char"] in ARPEGGIOS and .3*gap<head["x"]-c["x"]<3*gap
                           and abs(c["y"]-head["y"])<5*gap for c in staff["chars"]):
                        issues.append("arpeggio_requires_review")
                    written_pitch=pitch
                    octave_shift,octave_evidence=_octave_at(head["x"],octave_regions,gap)
                    if octave_shift is None:
                        issues.append("octave_line_extent_unresolved")
                    elif octave_shift and pitch is not None:
                        midi+=octave_shift
                        pitch=letter+({-1:"b",0:"",1:"#",2:"##"}[alter])+str(octave+octave_shift//12)
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
                             "finger":None, "finger_candidates":[], "rhythm_evidence":rhythm,
                             "confidence":.85, "issues":issues, "confirmed":False}
                    staff_events.append(event)
                # Finger groups are attached by horizontal alignment, then vertical order.
                groups = _event_groups(staff_events,gap)
                for group in groups:
                    x = median(e["origin"][0] for e in group)
                    yy = median(e["origin"][1] for e in group)
                    candidates = [(n,c) for n,c in enumerate(chars) if n not in used_fingers
                                  and c["char"] in DIGITS and DIGITS[c["char"]]<=5
                                  and c["size"]<1.7*gap and abs(c["x"]-x)<1.5*gap
                                  and abs(c["y"]-yy)<9*gap]
                    # A nearby bass digit is not evidence of an unprinted RH
                    # finger, including at a tied continuation. Compare actual
                    # aligned noteheads on other staves before borrowing it.
                    candidates = [(n,c) for n,c in candidates if not any(
                        other is not staff and abs(h["x"]-c["x"])<1.5*gap
                        and abs(h["y"]-c["y"])+.5*gap < min(abs(e["origin"][1]-c["y"]) for e in group)
                        for other in staves for h in other["heads"])]
                    # Prefer a complete printed group above right-hand heads;
                    # do not borrow nearer bass-staff digits between staves.
                    # Some supplied scores print right-hand fingering below:
                    # keep that candidate but require explicit visual review.
                    if staff["hand"] == "right":
                        above = [(n,c) for n,c in candidates if c["y"] < min(e["origin"][1] for e in group)-.3*gap]
                        if len(above) >= len(group):
                            candidates = above
                    candidates.sort(key=lambda nc:abs(nc[1]["y"]-yy))
                    selected = candidates[:len(group)]
                    if len(selected)==len(group):
                        for event,(n,c) in zip(sorted(group,key=lambda e:e["origin"][1]),sorted(selected,key=lambda nc:nc[1]["y"])):
                            event["finger"] = DIGITS[c["char"]]
                            event["finger_bbox"] = _round_box(c["bbox"])
                            used_fingers.add(n)
                            if staff["hand"] == "right" and c["y"] >= min(e["origin"][1] for e in group)-.3*gap:
                                event["issues"].append("right_fingering_below_requires_review")
                            if len(group)>1:
                                event["issues"].append("chord_fingering_order_requires_review")
                    else:
                        for event in group:
                            event["issues"].append("fingering_missing_or_ambiguous")
                            event["finger_candidates"] = [DIGITS[c["char"]] for _,c in candidates]
                measures = []
                for measure in range(len(bars)-1):
                    m_groups = [g for g in groups if g[0]["measure"]==measure+1]
                    rests = [c for c in staff_rests if bars[measure]<c["x"]<bars[measure+1]]
                    rest_events=[]
                    for r in rests:
                        duration,evidence=_rest_duration(r,gap,staff["chars"],meter,not m_groups and len(rests)==1)
                        rest_events.append({"id":f"p{page_index+1}-r{len(project['rests'])+len(rest_events)+1}",
                            "page":page_index+1,"system":staff["system"],"staff":staff["id"],
                            "hand":staff["hand"],"measure":measure+1,"origin":[round(r["x"],3),round(r["y"],3)],
                            "bbox":_round_box(r["bbox"]),"duration":duration,"duration_beats":duration,
                            "measure_beat":None,"beat":None,"written_beat":None,"rhythm_evidence":evidence,
                            "confirmed":False,"issues":[] if duration is not None else ["rest_duration_unresolved"]})
                    timeline = [(g[0]["origin"][0],g, {e["duration"] for e in g}) for g in m_groups]
                    timeline.extend((r["origin"][0],[r],{r["duration"]}) for r in rest_events)
                    timeline.sort(key=lambda t:t[0])
                    simple = bool(timeline) and all(len(d)==1 and None not in d for _,_,d in timeline)
                    total = sum(next(iter(d)) for _,_,d in timeline) if simple else None
                    if simple and meter is not None and abs(total-meter)<.01:
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
                    resolved=simple and meter is not None and abs(total-meter)<.01
                    voices=None
                    if not resolved:
                        voices=_resolve_explicit_voices([e for g in m_groups for e in g],rest_events,staff,meter)
                        if voices is not None:
                            resolved=True
                    measure_record={"measure":measure+1,"total_beats":total,"timing_resolved":resolved,
                                    "length_beats":meter if resolved else None}
                    if voices is not None:
                        measure_record.update(timing_method="explicit_voices",voices=voices)
                    measures.append(measure_record)
                    project["rests"].extend(rest_events)
                staff["measures"]=measures
                staff["bars"]=bars
                if staff["hand"]=="right":
                    project["repeat_markers"].extend({**mark,"page":page_index+1,"system":staff["system"],
                        "staff":staff["id"],"written_beat":None} for mark in _repeat_marks(staff,lines,bars))
                    project["ending_brackets"].extend({**bracket,"page":page_index+1,"system":staff["system"],
                        "staff":staff["id"]} for bracket in _ending_brackets(staff,lines,bars))
                    if any(c["char"] in ("ư","Ʊ") and staff["top"]-10*gap<c["y"]<staff["bottom"]+4*gap
                           for c in chars):
                        project["repeat_review_issues"].append(f"{staff['id']}: navigation sign requires manual performance order")
                _annotate_ties(staff_events,curves,gap)
                for event in staff_events:
                    if event["issues"]:
                        event["confidence"] = .55 if event["finger"] else .35
                project["notes"].extend(staff_events)
                project["staves"].append({"id":staff["id"],"page":page_index+1,"system":staff["system"],
                                          "hand":staff["hand"],"clef":staff["clef"],"meter_beats":meter,
                                          "meter_evidence":meter_evidence,
                                          "measure_count":len(bars)-1,
                                          "measures":measures,
                                          "key_signature":key_map,"lines":[round(staff["top"]+k*gap,3) for k in range(5)],
                                          "bbox":_round_box([staff["left"],staff["top"],staff["right"],staff["bottom"]]),
                                          "bars":bars})
            # Written score coordinates advance across verified complete measures.
            # A repeat bar changes performance order, not the position of printed
            # notes. Record it separately; do not erase an independently known beat.
            for system_number in range(1, system+2):
                system_staves = [s for s in staves if s["system"] == system_number]
                system_notes = [e for e in project["notes"] if e["page"]==page_index+1 and e["system"]==system_number]
                meters = {s.get("meter_beats") for s in system_staves if s.get("meter_beats") is not None}
                count=max((len(s.get("measures",[])) for s in system_staves),default=0)
                meter=next(iter(meters)) if len(meters)==1 else None
                events=system_notes+[r for r in project["rests"] if r["page"]==page_index+1 and r["system"]==system_number]
                if page_index==0 and system_number==1 and global_measure_base==0:
                    pickup=_resolve_pickup(system_staves,events,meter)
                    if pickup is not None:
                        project["pickup_beats"]=pickup
                for measure in range(1,count+1):
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
