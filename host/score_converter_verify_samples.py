"""Explicit manually read test excerpts. Never used by PDF recognition."""
import json
from pathlib import Path
from score_converter import recognize_pdf, export_reviewed
from score_codec import encode, decode

def verify(samples, output):
    output.mkdir(parents=True,exist_ok=True)
    cases=[
        dict(prefix='1007271',name='波尔卡右手第1至2小节',system=1,measures=[1,2],start=0,end=4,bpm=80,
             pitches=['D5','F5','E5','D5','D5','E5','E5'], fingers=[2,4,3,2,2,3,4],
             beats=[0,.5,.75,1,1.5,2,3], durations=[.5,.25,.25,.5,.5,.5,1], crop=[38,150,372,231]),
        dict(prefix='969886',name='阿拉伯风右手第3至4小节',system=1,measures=[3,4],start=4,end=8,bpm=80,
             pitches=['A4','B4','C5','B4','A4','A4','B4','C5','D5','E5'], fingers=[1,2,3,2,1,1,2,3,4,5],
             beats=[4,4.25,4.5,4.75,5,6,6.25,6.5,6.75,7], durations=[.25,.25,.25,.25,.5,.25,.25,.25,.25,.5], crop=[212,82,385,142]),
        dict(prefix='1003497',name='南瓜布吉舞右手第3小节',system=1,measures=[3],start=8,end=12,bpm=100,
             pitches=['C4','D4','Eb4','C4','D4','Eb4'], fingers=[1,2,3,1,2,3],
             beats=[8,9,9,10,11,11], durations=[1]*6,crop=[397,127,560,172]),
        dict(prefix='1002169',name='第2首右手第1小节：长音与双指和弦',system=1,measures=[1],start=0,end=4,bpm=120,
             pitches=['C5','E4','C5','E4','C5','E4'],fingers=[5,1,5,1,5,1],
             beats=[0,0,2,2,3,3],durations=[2,2,1,1,1,1],crop=[38,100,318,200]),
    ]
    reports=[]
    for case in cases:
        source=next(samples.glob(case['prefix']+'*.pdf'))
        project=recognize_pdf(source)
        notes=[n for n in project['notes'] if n['hand']=='right' and n['page']==1 and
               n['system']==case['system'] and n['measure'] in case['measures']]
        assert len(notes)==len(case['pitches'])
        actual=[(n['pitch'],n['finger'],n['duration_beats']) for n in notes]
        expected=list(zip(case['pitches'],case['fingers'],case['durations']))
        assert actual==expected,(case['name'],actual,expected)
        # Missing whole-score timing still needs explicit original-score review.
        # If the engine supplies a beat, it must agree with the reviewed excerpt.
        assert all(n.get('beat') is None or n['beat']==case['beats'][i]
                   for i,n in enumerate(notes)),case['name']
        for i,note in enumerate(notes):
            note.update(beat=case['beats'][i],confirmed=True,
                        review_note='逐音对照原PDF核对音高、指法、时值、休止；原issues保留')
        project.update(name=case['name'],notes=notes,
            selection=dict(hand='right',bpm=case['bpm'],start_beat=case['start'],end_beat=case['end'],range_reviewed=True),
            excerpt_source=dict(file=source.name,sha256=project['source_sha256'],page=1,
                                measures=case['measures'],crop_pdf_points=case['crop'],manual_review=True))
        score=export_reviewed(project);blob=encode(score);assert decode(blob)==score
        (output/(case['prefix']+'.reviewed.json')).write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/(case['prefix']+'.score.json')).write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/(case['prefix']+'.pgl')).write_bytes(blob)
        reports.append(dict(name=case['name'],notes=len(notes),bytes=len(blob),duration_ms=score['duration_ms'],source=project['excerpt_source']))
    (output/'reviewed-excerpts-report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    return reports


def verify_training_features(output):
    """Synthetic acceptance fixture, explicitly not a recognized PDF or song."""
    output.mkdir(parents=True,exist_ok=True)
    events=[('C4',1,0,2),('E4',3,0,2),('D4',2,3,3),
            ('G4',5,6,.5),('G4',5,6.5,.5),('F4',4,8,2),('D4',2,8,2)]
    notes=[dict(id=f'manual-feature-{i}',page=1,hand='right',pitch=pitch,finger=finger,
                beat=beat,duration_beats=duration,confirmed=True,
                review_note='合成功能测试数据，不来自PDF识别')
           for i,(pitch,finger,beat,duration) in enumerate(events)]
    # The UI has the same duration edit and explicit exclude actions: correct
    # a reviewed tie by keeping its first onset, combining duration, and
    # excluding the continuation. Slurs must never be merged automatically.
    notes.append(dict(id='manual-tie-continuation',page=1,hand='right',pitch='D4',finger=2,
                      beat=5,duration_beats=1,confirmed=False,excluded=True))
    notes.append(dict(id='left-not-transmitted',page=1,hand='left',pitch='C3',finger=1,
                      beat=0,duration_beats=12,confirmed=True))
    project=dict(name='合成功能测试：长音休止和弦重复',notes=notes,
                 selection=dict(hand='right',bpm=120,start_beat=0,end_beat=12,range_reviewed=True),
                 synthetic_fixture=True,not_pdf_recognition=True)
    score=export_reviewed(project);blob=encode(score)
    assert decode(blob)==score
    assert score['duration_ms']==6000 and len(score['notes'])==7
    timeline=[(0,5),(999,5),(1000,0),(1499,0),(1500,2),(2999,2),
              (3000,16),(3249,16),(3250,16),(3499,16),(3500,0),
              (4000,10),(4999,10),(5000,0),(5999,0)]
    for t,mask in timeline:
        actual=sum(1<<(n['finger']-1) for n in score['notes']
                   if n['t_ms']<=t<n['t_ms']+n['duration_ms'])
        assert actual==mask,(t,actual,mask)
    assert sum(n['finger']==2 and n['t_ms']==1500 for n in score['notes'])==1
    base=output/'feature-hold-rest-chord-repeat'
    base.with_suffix('.reviewed.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    base.with_suffix('.score.json').write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8')
    base.with_suffix('.pgl').write_bytes(blob)
    report=dict(synthetic_fixture=True,not_pdf_recognition=True,notes=7,bytes=len(blob),duration_ms=6000,
                timeline=[dict(t_ms=t,mask=mask) for t,mask in timeline],
                checks=['sustained_chord','middle_rest','merged_tie_one_onset','same_finger_repeated_notes',
                        'two_finger_chord','trailing_rest','right_hand_only','encode_decode_exact'])
    (output/'feature-fixture-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('samples',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    print(json.dumps(dict(real_excerpts=verify(a.samples,a.output),
                         synthetic_features=verify_training_features(a.output)),ensure_ascii=False,indent=2))
