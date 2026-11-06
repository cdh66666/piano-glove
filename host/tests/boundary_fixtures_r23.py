from copy import deepcopy
from score_realization import realize_project

def mark(kind,gid,**options):return dict(kind=kind,group_id=gid,options=options)
def note(ident,pitch,beat,duration,measure=1,hand='right',marks=(),**extra):
    return dict(id=ident,hand=hand,pitch=pitch,finger=1 if hand=='right' else 5,beat=beat,duration_beats=duration,
                page=1,system=1,measure=measure,measure_beat=0,measure_start_beat=beat,
                source_fingering_state='printed',performance_marks=list(marks),**extra)
def project(notes,rests=()):
    return dict(name='Independent synthetic diagnosis',notes=notes,rests=list(rests),selection=dict(bpm=120,start_beat=0,repeat_mode='written'),
                performance_policy=dict(mode='practice'),source_kind='manual',recognition_performed=False)
def run(p):
    before=deepcopy(p);r=realize_project(p)
    assert p==before,'Source was unexpectedly changed'
    return dict(errors=r.get('errors'),duration_ms=r.get('duration_ms'),audio_events=r.get('audio_events'),
                fermata_features=[f for f in r.get('features',[]) if f['kind']=='fermata'])

def grace(start,anchor):
    g=note('small','D4',anchor,None,marks=[mark('grace_short','ornament',anchor_id='main',member_ids=['small'],order=0)],grace_kind='slashed')
    p=project([note('before','C4',0,1),g,note('main','E4',anchor,1),note('after','F4',anchor+1,1),note('tail','G4',anchor+2,1)])
    p['selection']['repeat_mode']='unfold';p['repeat_sections']=[dict(start_beat=start,end_beat=anchor+2,count=2,confirmed=True)]
    return p

def fermata(kind):
    rest=dict(id='silent',hand='right',page=1,system=1,measure=2,beat=1,measure_start_beat=1,measure_beat=0,duration_beats=2)
    p=project([note('before','C4',0,1),note('after','E4',3,1,measure=3)],[rest])
    if kind=='left_over_silence':
        lh=note('left','C3',None,1,measure=2,hand='left',marks=[mark('fermata','pause')]);p['notes'].append(lh)
    elif kind=='left_over_sound':
        p['notes'].append(note('middle','D4',1,2,measure=2))
        p['notes'].append(note('left','C3',None,1,measure=2,hand='left',marks=[mark('fermata','pause')]))
    elif kind=='right_rest':rest['performance_marks']=[mark('fermata','pause')]
    elif kind=='terminal_empty_measure':
        p=project([note('before','C4',0,1),note('left','C3',None,2,measure=2,hand='left',marks=[mark('fermata','pause')])])
        p['written_duration_beats']=3
    return p
