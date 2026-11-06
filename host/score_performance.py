"""Report detected notation playback limits without changing note readiness."""


def source_ids(score):
    result=set()
    for note in score.get('source_notes',[]):
        values=note.get('source_note_ids') or [note.get('id')]
        result.update(value for value in values if type(value) in (str,int))
    return result


def performance_notice(notes, exported_ids=None, expanded_tremolo_ids=(), exported=False):
    """Assess only observed markers on selected or actually exported sources.

    Empty results do not certify absence of other, unrecognized notation.
    No duration, pitch, fingering, readiness or actual performance is inferred.
    """
    selected=[]
    for note in notes:
        ident=note.get('id')
        if (note.get('excluded') or note.get('hand')!='right' or type(ident) not in (str,int)
                or (exported_ids is not None and ident not in exported_ids)):
            continue
        selected.append(note)
    expanded=set(expanded_tremolo_ids)
    groups={('arpeggio','written-attacks'):[],('tremolo','quantized-written-subdivision'):[],
            ('tremolo','written-attacks'):[]}
    for note in selected:
        ident=note['id']
        if 'arpeggio_requires_review' in (note.get('issues') or []):
            groups[('arpeggio','written-attacks')].append(ident)
        if note.get('tremolo_group'):
            rendering='quantized-written-subdivision' if ident in expanded else 'written-attacks'
            groups[('tremolo',rendering)].append(ident)
    features=[dict(kind=kind,rendering=rendering,source_note_ids=list(dict.fromkeys(ids)))
              for (kind,rendering),ids in groups.items() if ids]
    if not features:
        return None
    messages=[]
    for feature in features:
        if feature['kind']=='arpeggio':
            messages.append('基础音符已导出，琶音未展开' if exported else '琶音未展开，导出保留基础音符位置')
        elif feature['rendering']=='quantized-written-subdivision':
            messages.append('震音已按书面节拍展开，速度需核对' if exported else '震音按书面节拍展开，速度需核对')
        else:
            messages.append('震音未展开，本次只保留基础音符' if exported else '震音未展开，导出保留基础音符位置')
    return dict(version=1,basis='detected-source-markers',features=features,message='；'.join(messages))
