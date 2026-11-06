"""Sparse associations between two retained, independently read ornaments.

The association proves a same-anchor printed combination, not a unique
historical execution. Performance choices belong to the practice arranger.
"""
from collections import defaultdict
import math

COMBINATION='trill_with_lower_mordent'
LONG_MORDENT='long_lower_mordent'
def _box(mark):
    value=mark.get('source',{}).get('bbox')
    if not isinstance(value,(list,tuple)) or len(value)!=4:return None
    if not all(type(v) in (float,int) and math.isfinite(v) for v in value):return None
    return value if value[2]>value[0] and value[3]>value[1] else None

def _printed_relation(trill,lower):
    """Recognize shared ink or a tight vertical stack, never side adjacency."""
    if trill.get('kind')!='trill' or lower.get('kind')!='mordent_lower':return False
    sa,sb=trill.get('source',{}),lower.get('source',{})
    if not sa.get('font') or sa.get('font')!=sb.get('font'):return False
    if sa.get('method')!='printed_music_glyph' or sb.get('method')!='printed_music_glyph':return False
    if any(sa.get(k) is not None and sb.get(k) is not None and sa[k]!=sb[k] for k in ('page','system','staff')):return False
    a,b=_box(trill),_box(lower)
    if not a or not b:return False
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    if overlap>.5*(a[2]-a[0])*(a[3]-a[1]) and overlap>.5*(b[2]-b[0])*(b[3]-b[1]):return 'overlapping_inks'
    wa,wb=a[2]-a[0],b[2]-b[0];ha,hb=a[3]-a[1],b[3]-b[1]
    horizontal=max(0,min(a[2],b[2])-max(a[0],b[0]))
    if (.5<=wa/wb<=2 and horizontal>=.6*min(wa,wb)
        and abs((a[0]+a[2]-b[0]-b[2])/2)<=.35*max(wa,wb)
        and 0<=b[1]-a[3]<=.25*min(ha,hb)):
        return 'tightly_stacked_inks'
    return None


def printed_pair(trill,lower):
    """No text aliases, cross-font pairing, or mere close bounding boxes."""
    return bool(_printed_relation(trill,lower))

def annotate_combinations(notes,gaps):
    """Add sparse relation evidence; never remove or replace either mark.

    One actual component must have exactly one source-head owner. A competing
    voice at its column keeps the interpretation unresolved.
    """
    owners=defaultdict(set)
    for n in notes:
        for m in n.get('performance_marks') or []:
            if m.get('kind') in ('trill','mordent_lower'):
                owners[(m['kind'],str(m.get('group_id')))].add(str(n.get('id')))
    count=0
    for n in notes:
        marks=n.get('performance_marks') or []
        tr=[m for m in marks if m.get('kind')=='trill'];low=[m for m in marks if m.get('kind')=='mordent_lower']
        if len(tr)!=1 or len(low)!=1 or not printed_pair(tr[0],low[0]):continue
        a,b=tr[0],low[0]
        if any(len(owners[(m['kind'],str(m.get('group_id')))])!=1 for m in (a,b)):continue
        gap=gaps.get(n.get('staff'),10);x=(n.get('origin') or [None])[0]
        if x is None:continue
        peers=[p for p in notes if p is not n and all(p.get(k)==n.get(k) for k in ('page','system','measure','staff'))
            and p.get('origin') and abs(p['origin'][0]-x)<.4*gap]
        if peers:continue
        group=str(n['id'])+':'+COMBINATION;components=[str(a.get('group_id')),str(b.get('group_id'))]
        if any(not m.get('group_id') for m in (a,b)):continue
        for mark,phase in ((a,'body'),(b,'termination')):
            mark.setdefault('options',{}).update(combination_id=group,combination_kind=COMBINATION,
                combination_role=phase,component_group_ids=components,
                combination_evidence='same_font_'+_printed_relation(a,b)+'_unique_single_head_anchor')
        count+=1
    return count+annotate_long_mordents(notes,gaps)

def combination_pair(marks):
    """Read the explicit sparse relation, validating both retained inks again."""
    tr=[m for m in marks if m.get('kind')=='trill'];low=[m for m in marks if m.get('kind')=='mordent_lower']
    if len(tr)!=1 or len(low)!=1 or not printed_pair(tr[0],low[0]):return None
    a,b=tr[0],low[0];oa,ob=a.get('options',{}),b.get('options',{})
    group=oa.get('combination_id');components=[str(a.get('group_id')),str(b.get('group_id'))]
    if not group or ob.get('combination_id')!=group:return None
    if any(o.get('combination_kind')!=COMBINATION or o.get('component_group_ids')!=components
        or o.get('combination_evidence')!='same_font_'+_printed_relation(a,b)+'_unique_single_head_anchor' for o in (oa,ob)):return None
    return a,b,str(group)


def printed_long_mordent(upper,lower):
    """A lateral wave extension overlapping the stroked lower-mordent glyph.

    Equal/coincident symbols, separate rows and a mere side neighbor are not
    the single continuous long sign. The glyph reader retains both inks.
    """
    if upper.get('kind')!='mordent_upper' or lower.get('kind')!='mordent_lower':return False
    sa,sb=upper.get('source',{}),lower.get('source',{})
    if not sa.get('font') or sa.get('font')!=sb.get('font'):return False
    if sa.get('method')!='printed_music_glyph' or sb.get('method')!='printed_music_glyph':return False
    if any(sa.get(k) is not None and sb.get(k) is not None and sa[k]!=sb[k] for k in ('page','system','staff')):return False
    a,b=_box(upper),_box(lower)
    if not a or not b:return False
    wa,wb=a[2]-a[0],b[2]-b[0];ha,hb=a[3]-a[1],b[3]-b[1]
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]));union=max(a[2],b[2])-min(a[0],b[0])
    return (.75<=wa/wb<=1.33 and 1.15<=hb/ha<=2.2
        and .3*min(wa,wb)<=overlap<=.8*min(wa,wb) and 1.2<=union/max(wa,wb)<=1.8
        and abs((a[1]+a[3]-b[1]-b[3])/2)<=.2*ha
        and b[1]<=a[1]+.05*ha and a[3]<=b[3]+.05*ha)


def annotate_long_mordents(notes,gaps):
    owners=defaultdict(set)
    for n in notes:
        for m in n.get('performance_marks') or []:
            if m.get('kind') in ('mordent_upper','mordent_lower'):
                owners[(m['kind'],str(m.get('group_id')))].add(str(n.get('id')))
    count=0
    for n in notes:
        marks=n.get('performance_marks') or []
        relevant=[m for m in marks if m.get('kind') in ('trill','mordent_upper','mordent_lower','turn','inverted_turn')]
        if len(relevant)!=2:continue
        upper=[m for m in relevant if m['kind']=='mordent_upper'];lower=[m for m in relevant if m['kind']=='mordent_lower']
        if len(upper)!=1 or len(lower)!=1 or not printed_long_mordent(upper[0],lower[0]):continue
        a,b=upper[0],lower[0]
        if any(not m.get('group_id') or len(owners[(m['kind'],str(m.get('group_id')))])!=1 for m in (a,b)):continue
        gap=gaps.get(n.get('staff'),10);x=(n.get('origin') or [None])[0]
        if x is None:continue
        if any(p is not n and all(p.get(k)==n.get(k) for k in ('page','system','measure','staff'))
            and p.get('origin') and abs(p['origin'][0]-x)<.4*gap for p in notes):continue
        group=str(n['id'])+':'+LONG_MORDENT;components=[str(a['group_id']),str(b['group_id'])]
        for mark,role in ((a,'wave_extension'),(b,'lower_mordent')):
            mark.setdefault('options',{}).update(notation_id=group,notation_kind=LONG_MORDENT,notation_role=role,
                component_group_ids=components,notation_evidence='same_font_overlapping_collinear_waves_single_lower_stroke_unique_single_head_anchor')
        count+=1
    return count


def long_mordent_pair(marks):
    relevant=[m for m in marks if m.get('kind') in ('trill','mordent_upper','mordent_lower','turn','inverted_turn')]
    if len(relevant)!=2:return None
    upper=[m for m in relevant if m['kind']=='mordent_upper'];lower=[m for m in relevant if m['kind']=='mordent_lower']
    if len(upper)!=1 or len(lower)!=1 or not printed_long_mordent(upper[0],lower[0]):return None
    a,b=upper[0],lower[0];group=a.get('options',{}).get('notation_id');components=[str(a.get('group_id')),str(b.get('group_id'))]
    for mark,role in ((a,'wave_extension'),(b,'lower_mordent')):
        opt=mark.get('options',{})
        if (not group or opt.get('notation_id')!=group or opt.get('notation_kind')!=LONG_MORDENT or opt.get('notation_role')!=role
            or opt.get('component_group_ids')!=components
            or opt.get('notation_evidence')!='same_font_overlapping_collinear_waves_single_lower_stroke_unique_single_head_anchor'):return None
    return a,b,str(group)
