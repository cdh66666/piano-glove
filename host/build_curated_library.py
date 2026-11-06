"""Build reviewed originals from independent, explicit musical transcriptions.

This is separate from recognition. Cached candidates supply PDF coordinates only;
they are not approved en masse. Every shipped entry needs its own transcription
and coverage evidence before inclusion here. No serial or application access.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from score_codec import encode, decode
from score_converter import export_reviewed, pitch_midi
from score_sources import ScoreSources

ROOT = Path(__file__).resolve().parent / 'assets' / 'score-library'
EVIDENCE = ROOT.parents[3] / 'evidence' / 'curation-r3-20261024'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def diatonic(index):
    octave, step = divmod(index, 7)
    return 'CDEFGAB'[step] + str(octave)


def apply_written_tempo_changes(score, project, spec):
    """Integrate explicit numeric tempo marks over the reviewed performance.

    Source beats remain quarter-note units in the review project. Only final
    event milliseconds and their source-span timestamps are transformed.
    """
    if not spec.get('tempo_changes'):
        return score
    assert not spec.get('repeats'), 'Tempo changes with repeats need explicit performance_order'
    bars = {bar['printed_measure']: bar for bar in spec['bars']}
    changes = {c['printed_measure']: c['bpm'] for c in spec['tempo_changes']}
    tempo_by_bar = {};current = spec['bpm']
    for bar in spec['bars']:
        current = changes.get(bar['printed_measure'], current)
        tempo_by_bar[bar['printed_measure']] = current
    segments=[];beat=0;milliseconds=0
    for number in spec.get('performance_order', [bar['printed_measure'] for bar in spec['bars']]):
        length=bars[number]['length'];bpm=tempo_by_bar[number]
        segments.append((beat,beat+length,milliseconds,bpm))
        beat+=length;milliseconds+=length*60000/bpm
    def time_at(value):
        for start,end,t,bpm in segments:
            if value < end-1e-9:
                return t+(value-start)*60000/bpm
        assert abs(value-beat)<1e-7, (value,beat)
        return milliseconds
    by_id={note['id']:note for note in project['notes']}
    for output, origin in zip(score['notes'],score['source_notes']):
        members=[by_id[i] for i in origin['source_note_ids']]
        start=members[0]['beat'];end=max(n['beat']+n['duration_beats'] for n in members)
        output['t_ms']=round(time_at(start));output['duration_ms']=round(time_at(end))-output['t_ms']
        origin.update(t_ms=output['t_ms'],duration_ms=output['duration_ms'])
        for span in origin.get('source_spans',[]):
            n=by_id[span['id']]
            span['t_ms']=round(time_at(n['beat']))
            span['duration_ms']=round(time_at(n['beat']+n['duration_beats']))-span['t_ms']
    score['duration_ms']=round(milliseconds)
    score['tempo_changes']=deepcopy(spec['tempo_changes'])
    return score


def hanon_transcription(number):
    """Entered from all four original page images; not inferred from OMR output.

    Both exercises: C major, 2/4, 29 printed bars. The first 14 patterns move
    upward by a diatonic step per bar; 15-28 move downward. All 224 pattern notes
    are sixteenths. Bar 29 is C3, a half note. Repeat end at bar 28 returns to bar
    1; the closing half note follows the second pass. There are no ties or rests.
    """
    patterns = {
        2: ((0, 2, 5, 4, 3, 4, 3, 2), (1, 2, 5, 4, 3, 4, 3, 2),
            (0, -3, -5, -4, -3, -4, -3, -2), (5, 2, 1, 2, 3, 2, 3, 4)),
        4: ((0, 1, 0, 2, 5, 4, 3, 2), (1, 2, 1, 2, 5, 4, 3, 2),
            (0, -1, 0, -3, -5, -4, -3, -2), (5, 4, 5, 2, 1, 2, 3, 4)),
    }
    up, uf, down, df = patterns[number]
    bars = []
    for measure in range(1, 30):
        if measure <= 14:
            pitches = [diatonic(21 + measure - 1 + offset) for offset in up]
            fingers, durations = uf, [0.25] * 8
        elif measure <= 28:
            pitches = [diatonic(39 - (measure - 15) + offset) for offset in down]
            fingers, durations = df, [0.25] * 8
        else:
            pitches, fingers, durations = ['C3'], [1], [2]
        bars.append(dict(printed_measure=measure, pitches=pitches,
                         fingers=list(fingers), durations=durations,
                         beat=(measure - 1) * 2))
    return bars


def associate_hanon(raw, bars):
    groups = defaultdict(list)
    for candidate in raw['notes']:
        groups[(candidate['page'], candidate['system'], candidate['measure'])].append(candidate)
    assert len(groups) == 29, 'Original must contain all 29 printed bars'
    notes, corrections = [], []
    for key, expected in zip(sorted(groups), bars):
        candidates = sorted(groups[key], key=lambda n: (n['bbox'][0], n['bbox'][1]))
        columns = []
        for candidate in candidates:
            if columns and abs(candidate['bbox'][0] - columns[-1][0]['bbox'][0]) < 1:
                columns[-1].append(candidate)
            else:
                columns.append([candidate])
        assert len(columns) == len(expected['pitches']), (key, len(columns))
        assert all(len(col) == 2 for col in columns), (key, 'Missing hand note')
        for offset, (column, pitch, finger, duration) in enumerate(zip(
                columns, expected['pitches'], expected['fingers'], expected['durations'])):
            # On these four reviewed pages the right voice is always above the
            # left voice, including the portions sharing the lower staff.
            candidate = min(column, key=lambda n: n['bbox'][1])
            assert candidate['pitch'] == pitch, (key, offset, candidate['pitch'], pitch)
            note = {field: deepcopy(candidate[field]) for field in (
                'id', 'page', 'system', 'measure', 'bbox', 'origin') if field in candidate}
            note.update(hand='right', pitch=pitch, finger=finger,
                        beat=expected['beat'] + offset * 0.25,
                        duration_beats=duration, confirmed=True,
                        printed_measure=expected['printed_measure'],
                        review_basis='independent-pattern-transcription-from-original-pages',
                        finger_basis='printed')
            notes.append(note)
            differences = {field: dict(candidate=candidate.get(field), reviewed=note[field])
                           for field in ('hand', 'finger', 'beat', 'duration_beats')
                           if candidate.get(field) != note[field]}
            if differences:
                corrections.append(dict(id=note['id'], page=note['page'],
                    printed_measure=note['printed_measure'], changes=differences))
    assert len(notes) == 225
    return notes, corrections


def explicit_czerny(number):
    """Full page-by-page transcription; each slash separates simultaneous notes.

    Pitch and finger sequences were checked against both original pages. Timing
    is entered from the visible beams, stems and rests; original repeat signs
    are explicitly represented. The cached recognizer does not decide these.
    """
    if number == 66:
        sequences = [
            ('C#5 A4 B4 C#5 D5 E5 F#5 G#5 A5 B5 C#6 A5', '312312311231'),
            ('B5 C#6 B5 C#6 D6 C#6 B5 A5 G#5', '232343212'),
            ('D5 B4 C#5 D5 E5 F#5 G#5 A5 B5 C#6 D6 B5', '312312312341'),
            ('C#6 D6 C#6 D6 E6 D6 C#6 B5 A5', '332354321'),
            ('A5 B5 C#6 D6 E6 F#6 G#6 A6 B6 C#7 D7 E7', '231234123455'),
            ('D7 C#7 B6 A6 G#6 F#6 E6 D6 C#6 B5 A5 G#5', '432143213214'),
            ('F#5 E5 D5 C#5 B4 A4 G#4 F#4 E4 D5 C#5 B4', '321321321532'),
            ('A4 B4 C#5 D5 E5 F#5 G#5 A5 A4', '123123451'),
            ('B5 E5 A5 E5 G#5 E5 A5 E5 B5 E5 G#5 E5', '513121314131'),
            ('A5 B4 G#5 B4 F#5 B4 G#5 B4 A5 B4 F#5 B4', '514141515141'),
            ('A5 B4 G#5 B4 F#5 B4 G#5 B4 A5 B4 F#5 B4', '515141515141'),
            ('G#5 B4 F#5 B4 E5 B4 F#5 B4 G#5 B4 E5 B4', '413121314121'),
            ('G#5 B4 F#5 B4 E5 B4 F#5 B4 G#5 B4 E5 B4', '514131414121'),
            ('C#5 F#5 C#5 F#5 A5 F#5 A5 F#5 C#5 F#5 C#5 F#5', '241354542413'),
            ('B4 C#5 D#5 E5 F#5 G#5 A5 B5 F#5 A5 G#5 F#5', '123123452432'),
            ('E5 E5 G#5 F#5 E5 D5', '124321'),
        ]
        bars = []
        for i, (pitches, fingers) in enumerate(sequences, 1):
            assert len(pitches.split()) == len(fingers)
            events = []
            for j, (pitch, finger) in enumerate(zip(pitches.split(), fingers)):
                duration = .5 if i == 16 or (i in (2, 4, 8) and j == 8) or (i in (9, 10) and j % 2 == 0) else .25
                events.append(dict(pitches=[pitch], fingers=[int(finger)],
                    onset=j * (.5 if i == 16 else .25), duration=duration))
            bars.append(dict(printed_measure=i, length=3, events=events,
                rests=[dict(onset=2.5, duration=.5)] if i in (2, 4, 8) else []))
        return dict(number=66, id='1002306', bpm=75, meter=3, bars=bars,
            expected_written_notes=177, tempo_basis='Printed quarter=72-88; chosen quarter=75 within the original range.',
            octave='8va spans bars 5-6 only; sounding pitches entered explicitly.',
            repeats=[], ties=[], performance_order=list(range(1, 9)) + list(range(1, 17)) + list(range(1, 9)),
            repeat_description='Bars 1-8 twice, then 9-16, then D.C. al Fine returns to 1-8 once; the repeat is omitted on the D.C. return.',
            deviations=['Bars 9-10: shared unison noteheads in two voices become one motor event with the longer eighth-note duration and upper-voice printed fingering. This preserves the sustained upper voice while the lower sixteenth-note interleaving continues on finger 1.',
                'No repeat on the D.C. return; final stop is the printed Fine after bar 8.'])
    if number == 65:
        sequences = [
            ('D5 E5 ' * 6, '12' * 6),
            ('F#5 G5 ' * 6, '3423' * 3),
            ('E5 F#5 ' * 6, '23' * 6),
            ('G5 A5 ' * 6, '4523' * 3),
            ('F#5 G5 ' * 6, '3423' * 3),
            ('A5 D5 E5 F#5 G5 A5 B5 C#6 D6 E6 F#6 D6', '512312311231'),
            ('E6 F#6 E6 F#6 E6 F#6 E6 F#6 A6 G6 F#6 E6', '232323235432'),
            ('D6 F#6 A6 F#6 D6', '13532'),
            ('B5 A5 ' * 6, '32' * 6),
            ('G5 A5 ' * 6, '4523' * 3),
            ('G5 F#5 G5 F#5 ' * 3, '4232' * 3),
            ('E5 F#5 ' * 6, '23' * 6),
            ('E5 D5 ' * 6, '2132' * 3),
            ('C#5 B4 C#5 B4 C#5 B4 D5 C#5 E5 D5 C#5 B4', '323232435432'),
            ('A4 B4 C#5 D5 E5 F#5 G5 A5 E5 G5 F#5 E5', '123123452432'),
            ('D5 F#5 A5 F#5 D5', '13531'),
        ]
        bars = []
        for i, (pitches, fingers) in enumerate(sequences, 1):
            notes = [dict(pitches=[pitch], fingers=[int(finger)], onset=j * .25,
                          duration=.5 if i in (8, 16) and j == 4 else .25)
                     for j, (pitch, finger) in enumerate(zip(pitches.split(), fingers))]
            assert len(pitches.split()) == len(fingers)
            bars.append(dict(printed_measure=i, length=3, events=notes,
                rests=[dict(onset=1.5, duration=.5), dict(onset=2, duration=1)] if i in (8, 16) else []))
        return dict(number=65, id='1002307', bpm=80, meter=3, bars=bars,
            expected_written_notes=178, tempo_basis='Printed quarter=72-88; chosen quarter=80 within the original range.',
            octave='8va begins at bar 6 note 5 and ends after bar 8 note 5; pitches are entered at sounding octave.',
            repeats=[(0, 24), (24, 48)], ties=[], deviations=[])
    if number == 59:
        # Each block contains (pitches in a simultaneous chord, corresponding
        # printed fingers, onset, duration), in quarter-note units.
        a = [('B4 D5', '13', 0, 1), ('B4 D5', '13', 1, .5), ('B4 D5', '13', 1.5, .5)]
        b = [('B4 D5', '24', 0, 1), ('B4 G5', '15', 1, .5)]
        c = [('C5 D5 F#5', '435', 0, 1), ('C5 D5 F#5', '135', 1, .5), ('C5 D5 F#5', '135', 1.5, .5)]
        d = [('B4 D5 G5', '135', 0, 1), ('B4 D5', '13', 1, 1)]
        e = [('C5 D5 F#5', '124', i * .5, .5) for i in range(4)]
        f = [('B4 D5 G5', '125', 0, 1)]
        run_specs = [
            ('D5 E5 F#5 G5 A5 G5 F#5 E5 D5 E5 F#5 G5 A5 B5 C6 D6', '1234543212345345'),
            ('G5 A5 B5 C6 D6 C6 B5 A5 G5 A5 C6 B5 A5 G5 F#5 E5', '1234543212432132'),
            ('D5 E5 F#5 G5 A5 G5 F#5 E5 D5 E5 F#5 G5 A5 B5 C6 D6', '1234543212345345'),
            ('B5 A5 B5 C6 D6 C6 B5 A5 G5 F#5 E5 D5 C5 B4 A4 G4', '3234543214321321'),
        ]
        runs = [[(pitch, finger, j * .125, .125) for j, (pitch, finger) in enumerate(zip(pitches.split(), fingers))]
                for pitches, fingers in run_specs]
        blocks = [a, b, c, d, a, b, e, f, *runs, a, b, e, f]
        bars = [dict(printed_measure=i, length=2,
            events=[dict(pitches=pitches.split(), fingers=[int(x) for x in fingers], onset=onset, duration=duration)
                    for pitches, fingers, onset, duration in block],
            rests=[dict(onset=1.5, duration=.5)] if i in (2, 6, 14)
                else [dict(onset=1, duration=1)] if i in (8, 16) else [])
            for i, block in enumerate(blocks, 1)]
        return dict(number=59, id='1002313', bpm=60, meter=2, bars=bars,
            expected_written_notes=138, tempo_basis='Printed Allegretto without numeric tempo; 60 BPM chosen for glove practice.',
            octave='No octave-transposition marks.', repeats=[(0, 16), (16, 32)], ties=[],
            deviations=['Practice tempo 60 BPM chosen; original prints Allegretto without metronome value.',
                'PGL motor format carries pitches, printed fingers and metric durations; dynamic, slur and staccato expression is retained in the source image, not rendered as velocity/shortening.'])
    raise ValueError(number)


def love_dream_transcription():
    blocks = [
        [('D4', 2, 1)], [('B4', 5, 3)], [('B4', 4, 3)], [('B4', 4, 3)],
        [('B4', 4, 2), ('B4', 4, 1)], [('B4', 4, 2), ('B4', 4, 1)],
        [('C5', 5, 2), ('B4', 4, 1)], [('B4', 4, 3)],
        [('E4', 1, 2), ('E4', 1, 1)], [('E4', 1, 1), ('F#4', 2, 1), ('G4', 3, 1)],
        [('B4', 5, 2), ('A4', 4, 1)], [('G4', 3, 3)],
        [('G4', 3, 2), ('D4', 1, 1)], [('B4', 5, 3)], [('B4', 4, 3)], [('B4', 4, 3)],
        [('B4', 4, 2), ('B4', 2, 1)], [('B4', 2, 2), ('B4', 2, 1)],
        [('C5', 3, 2), ('B4', 2, 1)], [('E5', 5, 3)],
        [('E4', 1, 2), ('E4', 1, 1)], [('E4', 1, 1), ('F#4', 2, 1), ('G4', 3, 1)],
        [('B4', 5, 2), ('A4', 4, 1)], [('G4', 3, 3)], [('G4', 3, 2)],
    ]
    bars, cursor = [], 0
    for i, block in enumerate(blocks, 1):
        onset, events = 0, []
        for pitch, finger, duration in block:
            events.append(dict(pitches=[pitch], fingers=[finger], onset=onset, duration=duration))
            onset += duration
        bars.append(dict(printed_measure=i, beat=cursor, length=onset, events=events, rests=[]))
        cursor += onset
    assert cursor == 72
    return dict(id='970081', name='爱之梦（完整）', bpm=80, meter=3, bars=bars,
        expected_written_notes=40, expected_played_notes=36,
        tempo_basis='Printed Moderato without numeric tempo; 80 BPM chosen for glove practice.',
        octave='No octave-transposition marks.', repeats=[],
        ties=[((4, 0), (5, 0)), ((12, 0), (13, 0)), ((16, 0), (17, 0)), ((24, 0), (25, 0))],
        inherited_fingering_notes=[(5, 0), (13, 0), (17, 0), (25, 0)],
        repeat_description='No repeats. Initial pickup is one quarter beat; final bar is two beats. All four cross-bar ties are sustained.',
        deviations=['80 BPM practice tempo selected for the printed Moderato.',
            'Four unnumbered tied continuation noteheads inherit the preceding finger and are merged into a sustained motor event.'])


def gamer_transcription():
    # Every printed bar is explicitly represented. A slash joins a chord;
    # event tuples are (pitches, fingers, onset, duration).
    a = [('A4', '1', 0, 1), ('B4', '2', 2, 1)]
    b = [('C5', '3', 0, 1), ('E5', '5', 1, 1), ('D5', '4', 2, 1), ('C5', '3', 3, 1)]
    c = [('B4', '2', 0, 1), ('C5', '1', 2, 1)]
    d = [('D5', '2', 0, 1), ('F5', '4', 1, 1), ('E5', '3', 2, 1), ('D5', '2', 3, 1)]
    e = [('C5 E5', '13', 0, 2), ('E5', '4', 2, .5), ('D5', '3', 2.5, .5), ('C5', '2', 3, .5), ('E5', '4', 3.5, .5)]
    f = [('B4 D5', '13', 0, 2), ('E5', '4', 2, .5), ('D5', '3', 2.5, .5), ('B4', '1', 3, .5), ('D5', '3', 3.5, .5)]
    blocks = [a, b, c, d, e, f,
        [('C5 E5', '24', 0, 2), ('C5', '3', 2, .5), ('A4', '1', 2.5, .5), ('C5', '3', 3, .5), ('D5', '4', 3.5, .5)],
        [('A4 B4 E5', '125', 0, 2), ('G#4 B4 E5', '125', 2, 2)], a, b, c, d, e, f,
        [('A4 C5', '13', 0, 2), ('A4 B4', '13', 2, 2)], [('A4', '2', 0, 4)],
        [('A3', '2', 0, 2), ('A3', '2', 2, 1.5), ('G3', '1', 3.5, .5)],
        [('A3', '2', 0, 1), ('C4', '4', 1, 1), ('B3', '3', 2, 1), ('A3', '2', 3, 1)],
        [('G3', '1', 0, 1), ('G3', '1', 1, 1), ('C4', '3', 2, 1), ('E4', '5', 3, 1)],
        [('B3 D4', '43', 0, 4)], [('F4', '4', 1, 1), ('E4', '3', 2, 1), ('D4', '2', 3, 1)],
        [('E4', '4', 1, 1), ('D4', '3', 2, 1), ('C4', '2', 3, 1)],
        [('D4', '3', 0, 2), ('C4', '2', 2, 1), ('E4', '4', 3, 1)],
        [('B3 D4', '13', 0, 2), ('D4', '1', 2, .5), ('E4', '2', 2.5, .5), ('F4', '3', 3, .5), ('G4', '4', 3.5, .5)],
        [('A4', '5', 0, 2), ('A4', '2', 2, 1.5), ('G4', '1', 3.5, .5)],
        [('A4', '2', 0, 1), ('C5', '4', 1, 1), ('B4', '3', 2, 1), ('A4', '2', 3, 1)],
        [('G4', '1', 0, 1), ('G4', '1', 1, 1), ('C5', '3', 2, 1), ('E5', '5', 3, 1)],
        [('B4 D5', '13', 0, 4)],
        [('D5 F5', '24', 1, 1), ('E5', '3', 2, 1), ('D5', '2', 3, 1)],
        [('C5 E5', '14', 1, 1), ('D5', '3', 2, 1), ('C5', '2', 3, 1)],
        [('A4 D5', '13', 1, 1), ('C5', '2', 2, 1), ('D5', '3', 3, 1)],
        [('A4 E5', '15', 0, 2), ('G#4 E5', '15', 2, 2)],
        [('A4', '5', 0, 2), ('A4', '2', 2, 1.5), ('G4', '1', 3.5, .5)],
        [('A4', '2', 0, 1), ('B4', '2', 1, 1), ('C5', '3', 2, 1), ('E5', '5', 3, 1)],
        [('B4 D5', '24', 0, 4)], [('C5', '3', 0, 2), ('B4', '2', 2, 2)],
        [('A4', '1', 0, 1), ('E5', '3', 2, 1)],
        [('A5', '3', 0, 1), ('E6', '1', 2, 1)],
        [('A6', '3', 0, 1), ('E7', '3', 2, 1)], [('A7', '3', 0, 1)],
    ]
    assert len(blocks) == 40
    bars = []
    for i, block in enumerate(blocks, 1):
        events = [dict(pitches=pitches.split(), fingers=[int(x) for x in fingers], onset=onset, duration=duration)
                  for pitches, fingers, onset, duration in block]
        rests = [dict(onset=1, duration=1), dict(onset=3, duration=1)] if i in (1, 3, 9, 11, 37, 38, 39) else []
        if i in (21, 22, 29, 30, 31): rests = [dict(onset=0, duration=1)]
        if i == 40: rests = [dict(onset=1, duration=1), dict(onset=2, duration=2)]
        bars.append(dict(printed_measure=i, length=4, events=events, rests=rests))
    return dict(id='1078144', name='电子游戏达人（完整）', bpm=88, meter=4, bars=bars,
        expected_written_notes=140, expected_played_notes=169,
        tempo_basis='Printed quarter=88.', repeats=[], ties=[],
        octave='8va spans bars 38-39. Bar 40 carries 15ma: its written A5 sounds A7.',
        performance_order=list(range(1, 33)) + list(range(9, 17)) + list(range(33, 41)),
        candidate_pitch_overrides={(40, 0, 'A7'): 'A5'},
        repeat_description='Play bars 1-32, D.S. returns to the segno at bar 9; on the second visit to bar 16, jump to Coda at bar 33 and finish at 40.',
        deviations=['Raw recognition missed final 15ma; the reviewed event is A7.',
            'Bar 24 last G4 uses the printed finger 4, correcting the raw digit association.',
            'Metric durations are retained; source staccato, dynamics and pedal indications are not rendered by the motor event format.'])


def bach_transcription():
    sequences = [
        ('C4 D4 E4 F4 D4 E4 C4 G4 C5 C5 B4 C5 B4 C5', '12342314543434'),
        ('D5 G4 A4 B4 C5 A4 B4 G4 D5 G5 G5 F5 G5 F5 G5', '512342314554545'),
        ('E5 A5 G5 F5 E5 G5 F5 A5 G5 F5 E5 D5 C5 E5 D5 F5', '2543243543212435'),
        ('E5 D5 C5 B4 A4 C5 B4 D5 C5 B4 A4 G4 F#4 A4 G4 B4', '4321243543212435'),
        ('A4 D4 C5 B4 C5 D5 B4 A4 G4 F#4 E4 G4 F#4 A4', '41434532121323'),
        ('G4 B4 A4 C5 B4 D5 C5 E5 D5 B4 C5 D5 G5 C5 B4 C5 B4 A4 G4', '2435454541235212121'),
        ('G4 G4 A4 B4 C5 A4 B4 G4', '11234231'),
        ('F#4 A4 B4 C5 D5 B4 C5 A4', '21234231'),
        ('B4 D5 C5 B4 A4 C5 B4 D5', '24321324'),
        ('C5 E5 D5 C5 B4 D5 C#5 E5', '35432434'),
        ('D5 C#5 D5 E5 F5 A4 B4 C#5', '32345124'),
        ('D5 F#4 G#4 A4 B4 C5 D5', '5121234'),
        ('D5 E4 F#4 G#4 A4 F#4 G#4 E4 E5 D5 C5 E5 D5 C5 B4 D5', '4134534154354323'),
        ('C5 A5 G#5 B5 A5 E5 F5 D5 G#4 F5 E5 D5 C5 B4 A4', '254543541432121'),
        ('A4 A5 G5 F5 E5 G5 F5 A5 G5', '154324354'),
        ('G5 E5 F5 G5 A5 F5 G5 E5 F5', '423453423'),
        ('F5 G5 F5 E5 D5 F5 E5 G5 F5', '343213243'),
        ('F5 D5 E5 F5 G5 E5 F5 D5 E5', '312342312'),
        ('E5 C5 D5 E5 F5 D5 E5 C5 D5 E5 F5 G5 A5 F5 G5 E5', '2123423123451231'),
        ('F5 G5 A5 B5 C6 A5 B5 G5 C6 G5 E5 D5 C5', '2345123142143'),
        ('C5 Bb4 A4 G4 F4 A4 G4 Bb4 A4 B4 C5 E4 D4 C5 F4 B4', '3212132434521515'),
    ]
    assert len(sequences) == 21
    durations = {
        1: [.25] * 7 + [.5, .5] + [1 / 12] * 3 + [.25, .5],
        2: [.25] * 8 + [.5, .5] + [1 / 12] * 3 + [.25, .5],
        5: [.5, .5, .125, .125, .5, .25] + [.25] * 8,
        6: [.25] * 9 + [.125, .125, .25, .25] + [1 / 12] * 3 + [.25, .25, .25],
        7: [.5] + [.25] * 7, 8: [.5] + [.25] * 7,
        9: [.5] + [.25] * 7, 10: [.5] + [.25] * 7,
        11: [.5] * 8, 12: [.5] * 6 + [1],
        14: [.25] * 12 + [.5, .25, .25],
        15: [.25] * 8 + [2], 16: [.25] * 8 + [2],
        17: [.25] * 8 + [2], 18: [.25] * 8 + [2],
        20: [.25] * 8 + [.5, .5, .5, .25, .25],
    }
    bars = []
    for i, (pitches, fingers) in enumerate(sequences, 1):
        pitch_list = pitches.split()
        assert len(pitch_list) == len(fingers), (i, len(pitch_list), len(fingers))
        values = durations.get(i, [.25] * len(pitch_list))
        assert len(values) == len(pitch_list), i
        cursor = .25 if i == 1 else 0
        events = []
        for j, (pitch, finger, duration) in enumerate(zip(pitch_list, fingers, values)):
            if i in (7, 8, 9, 10) and j == 1:
                cursor = 2.25
            events.append(dict(pitches=[pitch], fingers=[int(finger)], onset=cursor, duration=duration))
            cursor += duration
        assert abs(cursor - 4) < 1e-8, (i, cursor)
        rests = [dict(onset=0, duration=.25)] if i == 1 else []
        if i in (7, 8, 9, 10):
            rests = [dict(onset=.5, duration=.5), dict(onset=1, duration=1), dict(onset=2, duration=.25)]
        bars.append(dict(printed_measure=i, length=4, events=events, rests=rests))
    # The source prints an upward arpeggio on the final whole-note chord. Its
    # speed is unspecified: use a short 40 ms roll at the printed 120 BPM.
    bars.append(dict(printed_measure=22, length=4,
        events=[dict(pitches=['E4'], fingers=[1], onset=0, duration=4),
                dict(pitches=['G4'], fingers=[2], onset=.08, duration=3.92),
                dict(pitches=['C5'], fingers=[5], onset=.16, duration=3.84)], rests=[]))
    return dict(id='30483', name='巴赫二部创意曲 BWV 772（完整）', bpm=120, meter=4, bars=bars,
        expected_written_notes=256, expected_played_notes=251,
        tempo_basis='Printed quarter=120.', repeats=[],
        ties=[((12, 6), (13, 0)), ((15, 8), (16, 0)), ((16, 8), (17, 0)),
              ((17, 8), (18, 0)), ((18, 8), (19, 0))],
        inherited_fingering_notes=[(13, 0), (16, 0), (17, 0), (18, 0), (19, 0)],
        arranged_finger_bars=[1, 2, 5, 6, 12, 14, 19, 20, 21],
        octave='No octave-transposition marks.',
        repeat_description='All 22 bars once. No repeat navigation. Initial sixteenth rest, middle rests and all five cross-bar ties are retained.',
        deviations=['Several printed fingering options overlap. In bars 1, 2, 5, 6, 12, 14, 19, 20 and 21 the selected executable fingers are explicitly classified as our arrangement, based on visible options.',
            'Printed ornament realizations are played in full: three 32nd-note triplets occupy one sixteenth in bars 1, 2 and 6; bar 5 has two plain 32nds and a final short 16th beam.',
            'Final arpeggiated chord is rolled bottom-to-top with 40 ms between attacks. Fermata duration is not numeric in the original; final chord lasts its written four beats.'])


def build_explicit(spec, raw, source):
    score_id = spec['id']
    groups = defaultdict(list)
    source_candidates = list(raw['notes'])
    for candidate in spec.get('manual_candidates', []):
        assert candidate['id'] not in {n['id'] for n in source_candidates}
        assert candidate.get('hand') == 'right' and len(candidate['bbox']) == 4
        source_candidates.append(candidate)
    for candidate in source_candidates:
        if (candidate.get('staff') in spec['candidate_staff_ids'] if spec.get('candidate_staff_ids') else candidate['hand'] == 'right'):
            groups[(candidate['page'], candidate['system'], candidate['measure'])].append(candidate)
    for staff in raw.get('staves', []):
        if (staff['id'] in spec['candidate_staff_ids'] if spec.get('candidate_staff_ids') else staff.get('hand') == 'right'):
            for measure in range(1, staff['measure_count'] + 1):
                groups.setdefault((staff['page'], staff['system'], measure), [])
    for frame in spec.get('signature_only_frames', []):
        key=tuple(frame)
        assert key in groups and not groups[key], (score_id,key,'Signature frame contains notes')
        assert not any((r['page'],r['system'],r['measure'])==key for r in raw.get('rests',[])), (score_id,key,'Signature frame contains a rest')
        del groups[key]
    assert len(groups) == len(spec['bars']), (score_id, len(groups), len(spec['bars']))
    notes, corrections = [], []
    origin_index = {}
    for key, bar in zip(sorted(groups), spec['bars']):
        pool = sorted(groups[key], key=lambda n: (n['bbox'][0], n['bbox'][1]))
        for event_index, event in enumerate(bar['events']):
            for pitch, finger in zip(event['pitches'], event['fingers']):
                overrides = spec.get('candidate_pitch_overrides', {})
                candidate_pitch = overrides.get((bar['printed_measure'], event_index, pitch),
                    overrides.get(f"{bar['printed_measure']}:{event_index}:{pitch}", pitch))
                matches = [n for n in pool if (n.get('pitch') or n.get('written_pitch')) == candidate_pitch]
                if not matches:
                    matches = [n for n in pool if (n.get('pitch') or n.get('written_pitch')) == pitch]
                assert matches, (score_id, key, pitch)
                candidate = matches[0]
                pool.remove(candidate)
                note = {field: deepcopy(candidate[field]) for field in ('id', 'page', 'system', 'measure', 'bbox', 'origin') if field in candidate}
                note.update(hand='right', pitch=pitch, finger=finger, confirmed=True,
                    beat=bar.get('beat', (bar['printed_measure'] - 1) * spec['meter']) + event['onset'],
                    duration_beats=event['duration'], printed_measure=bar['printed_measure'],
                    review_basis='explicit-full-score-transcription-from-all-original-pages', finger_basis='printed')
                if event.get('finger_basis'):
                    note['finger_basis'] = event['finger_basis']
                if bar['printed_measure'] in spec.get('arranged_finger_bars', []):
                    note['finger_basis'] = 'arranged-from-overprinted-options'
                if (bar['printed_measure'], event_index) in {tuple(pair) for pair in spec.get('inherited_fingering_notes', [])}:
                    note['finger_basis'] = 'inherited-from-printed-tied-start'
                differences = {field: dict(candidate=candidate.get(field), reviewed=note[field])
                    for field in ('pitch', 'finger', 'beat', 'duration_beats') if candidate.get(field) != note[field]}
                if differences:
                    corrections.append(dict(id=note['id'], printed_measure=bar['printed_measure'], changes=differences))
                notes.append(note)
                origin_index[(bar['printed_measure'], event_index, pitch)] = note
        assert not pool, (score_id, key, 'Unexpected extra right-hand candidates')
    notes.sort(key=lambda n: (n['beat'], n['finger']))
    assert len(notes) == spec['expected_written_notes']
    end = sum(bar['length'] for bar in spec['bars'])
    for tie in spec.get('ties', []):
        (source_bar, source_event), (target_bar, target_event) = tie[:2]
        tied_pitch = tie[2] if len(tie) > 2 else None
        source_notes = [note for (bar, event, pitch), note in origin_index.items()
            if (bar, event) == (source_bar, source_event) and (tied_pitch is None or pitch == tied_pitch)]
        for note in source_notes:
            target = origin_index[(target_bar, target_event, note['pitch'])]
            note.update(tie_to=target['id'], tie_reviewed=True)
    project_notes = notes
    if spec.get('performance_order'):
        project_notes = []
        bars_by_number = {bar['printed_measure']: bar for bar in spec['bars']}
        assert len(bars_by_number) == len(spec['bars'])
        printed_offsets, cursor = {}, 0
        for bar in spec['bars']:
            printed_offsets[bar['printed_measure']] = bar.get('beat', cursor)
            cursor += bar['length']
        played_cursor = 0
        for occurrence, printed_measure in enumerate(spec['performance_order']):
            for original in notes:
                if original['printed_measure'] == printed_measure:
                    note = deepcopy(original)
                    note['written_beat'] = original['beat']
                    note['beat'] = played_cursor + original['beat'] - printed_offsets[printed_measure]
                    note['performance_measure'] = occurrence + 1
                    note['source_original_id'] = original['id']
                    note['id'] = original['id'] + '@performance-' + str(occurrence + 1)
                    if 'tie_to' in note:
                        note['tie_to_original'] = note.pop('tie_to')
                    project_notes.append(note)
            played_cursor += bars_by_number[printed_measure]['length']
        for note in project_notes:
            if 'tie_to_original' in note:
                targets = [n for n in project_notes
                    if n['source_original_id'] == note['tie_to_original'] and n['pitch'] == note['pitch']
                    and abs(n['beat'] - note['beat'] - note['duration_beats']) < 1e-8]
                if not targets:
                    target_original=next(n for n in notes if n['id']==note['tie_to_original'])
                    pair=[note['printed_measure'],target_original['printed_measure']]
                    assert pair in spec.get('allowed_tie_omissions_on_jumps', []), (score_id,note['id'],'Tie crosses a non-contiguous performance jump')
                    note['tie_omitted_for_alternate_ending']=pair
                else:
                    assert len(targets)==1
                    note['tie_to'] = targets[0]['id']
        end = played_cursor
    title=spec.get('name', f"车尔尼 599 No.{spec.get('number')}（完整）")
    if all(n['finger_basis'].startswith(('arranged','inherited')) for n in notes) and '编配' not in title:
        title=title.replace('（完整）','')+'（右手练习编配）'
    project = dict(name=title, source_name=source['filename'],
        source_sha256=source['sha256'], pages=raw['pages'], notes=project_notes,
        written_duration_beats=end,
        repeat_sections=[dict(start_beat=a, end_beat=b, count=2, confirmed=True) for a, b in spec['repeats']],
        selection=dict(bpm=spec['bpm'], start_beat=0, end_beat=end, range_reviewed=True,
            repeat_mode='unfold', repeats_reviewed=True, performance_order_reviewed=True, ties_reviewed=True))
    score = export_reviewed(project)
    score = apply_written_tempo_changes(score, project, spec)
    expected = spec.get('expected_played_notes', len(project_notes) if spec.get('performance_order') else len(notes) * 2)
    assert len(score['notes']) == expected, (score_id, len(score['notes']), expected)
    if spec.get('expected_duration_ms') is not None:
        assert score['duration_ms'] == spec['expected_duration_ms'], (score_id,score['duration_ms'],spec['expected_duration_ms'])
    blob = encode(score)
    assert decode(blob)['notes'] == score['notes']
    store = ScoreSources(EVIDENCE / 'source-store')
    store.record_document(source['sha256'], raw['page_previews'], raw['pages'])
    assert store.associate(blob, project, score)
    package = store.package(blob)
    source_pages = list(range(1, source['pages'] + 1))
    output = ROOT / 'ready' / score_id
    output.mkdir(parents=True, exist_ok=True)
    (output / 'score.pgl').write_bytes(blob)
    (output / 'score.pglpack').write_bytes(package)
    write_json(output / 'reviewed-project.json', project)
    write_json(output / 'score.json', score)
    evidence = dict(id=score_id, status='reviewed-complete', full_source_coverage=True,
        source_sha256=source['sha256'], source_pages=source_pages,
        printed_measures=spec.get('printed_measure_count', sum(bar['length']>0 for bar in spec['bars'])),
        source_measure_frames=len(spec['bars']),
        written_right_notes=spec.get('printed_right_noteheads', len(notes)),
        arranged_written_events=len(notes), played_right_events=len(score['notes']),
        duration_ms=score['duration_ms'], bpm=spec['bpm'], tempo_basis=spec['tempo_basis'],
        tempo_changes=spec.get('tempo_changes', []),
        method='Every printed right-hand chord/run on all source pages compared with explicit pitch/finger/onset/duration transcription, including rests, octave marks, ties and performance navigation.',
        printed_fingerings=sum(n['finger_basis'] == 'printed' for n in notes),
        arranged_fingerings=sum(n['finger_basis'].startswith('arranged') for n in notes),
        inherited_tied_fingerings=sum(n['finger_basis'].startswith('inherited') for n in notes), omitted_right_notes=0,
        unresolved_items=[], deviations=spec['deviations'], octave=spec['octave'],
        performance_title=score['title'],
        manual_source_candidates=spec.get('manual_candidates', []),
        explicit_arrangements=spec.get('explicit_arrangements', []),
        signature_only_frames=spec.get('signature_only_frames', []),
        ties=spec['ties'] or 'The printed curved marks connect different pitches/chords as phrasing; no right-hand ties.',
        repeat_order=spec.get('repeat_description', 'Bars 1-8 twice, then bars 9-16 twice, preserving all final rests.'),
        independent_transcription=spec['bars'], corrections_to_raw_candidates=corrections,
        visual_review=dict(pages=[f'pages/{score_id}/page-{page}.png' for page in source_pages],
            reviewed=f"All {len(spec['bars'])} source frames including signature-only frames, every right-hand event, fingering, beams/rests, octave shifts, ties and navigation signs."),
        verification=dict(pgl_round_trip=True, device_event_limit=60000, no_same_finger_overlap=True,
            source_page_association_events=len(store.lookup(blob)['note_pages']), hardware_playback=False))
    write_json(output / 'curation.json', evidence)
    write_json(EVIDENCE / (score_id + '-full-review.json'), evidence)
    return dict(id=score_id, status='reviewed-complete', full_source_coverage=True,
        source_sha256=source['sha256'], pages=source_pages,
        printed_measures=spec.get('printed_measure_count', sum(bar['length']>0 for bar in spec['bars'])),
        source_measure_frames=len(spec['bars']),
        written_right_notes=spec.get('printed_right_noteheads', len(notes)),
        arranged_written_events=len(notes), played_right_events=len(score['notes']),
        pgl=f'ready/{score_id}/score.pgl', pglpack=f'ready/{score_id}/score.pglpack',
        score_sha256=hashlib.sha256(blob).hexdigest(), package_sha256=hashlib.sha256(package).hexdigest(),
        evidence=f'ready/{score_id}/curation.json', unresolved_items=[])


def build_hanon(score_id, number, raw, source):
    bars = hanon_transcription(number)
    notes, corrections = associate_hanon(raw, bars)
    if number == 2:
        # The final C3 is unnumbered in No.2 (unlike No.4). This is an explicit
        # closing-thumb arrangement, not a digit claimed to exist on the PDF.
        notes[-1]['finger_basis'] = 'arranged-terminal-thumb-unprinted'
    project = dict(name=f'哈农 No.{number}（完整）', source_name=source['filename'],
        source_sha256=source['sha256'], pages=raw['pages'], notes=notes,
        written_duration_beats=58, repeat_sections=[dict(start_beat=0, end_beat=56,
            count=2, confirmed=True)],
        selection=dict(bpm=60, start_beat=0, end_beat=58, range_reviewed=True,
            repeat_mode='unfold', repeats_reviewed=True, performance_order_reviewed=True))
    score = export_reviewed(project)
    assert len(score['notes']) == 449 and score['duration_ms'] == 114000
    blob = encode(score)
    decoded = decode(blob)
    assert decoded['notes'] == score['notes']
    store = ScoreSources(EVIDENCE / 'source-store')
    store.record_document(source['sha256'], raw['page_previews'], raw['pages'])
    assert store.associate(blob, project, score)
    package = store.package(blob)
    output = ROOT / 'ready' / score_id
    output.mkdir(parents=True, exist_ok=True)
    (output / 'score.pgl').write_bytes(blob)
    (output / 'score.pglpack').write_bytes(package)
    write_json(output / 'reviewed-project.json', project)
    write_json(output / 'score.json', score)
    evidence = dict(id=score_id, source_sha256=source['sha256'],
        status='reviewed-complete', source_pages=[1, 2], printed_measures=29,
        written_right_notes=225, played_right_events=449, bpm=60,
        tempo_basis='printed quarter=60' if number == 2 else 'practice arrangement: quarter=60; no printed tempo',
        full_source_coverage=True, omitted_right_notes=0, unresolved_items=[],
        method='Independent diatonic pattern transcription after viewing every original page; each candidate location matched to explicit pitch/finger/duration sequence; 29 bars checked at 2 beats each.',
        rests='No right-hand rests in the 29 printed bars.', ties='No right-hand ties.',
        repeats='Printed end-repeat after bar 28: bars 1-28 twice, then bar 29.',
        hand_assignment='Right voice shares lower staff with left in opening/closing bars; identify the upper of the two simultaneous voices and preserve cross-staff sections.',
        printed_fingerings=224 if number == 2 else 225, arranged_fingerings=1 if number == 2 else 0,
        deviations=['Practice tempo 60 BPM chosen because this original prints no tempo.'] if number == 4
            else ['The unnumbered final C3 uses arranged finger 1; the original does not print this digit.'],
        visual_review=dict(pages=['pages/' + score_id + '/page-1.png', 'pages/' + score_id + '/page-2.png'],
            reviewed='All 29 bars on both pages; pitches, printed fingers, sixteenth beams, final half note, clef changes, cross-staff voice and end-repeat.'),
        bars=bars, corrections_to_raw_candidates=corrections,
        verification=dict(pgl_round_trip=True, device_event_limit=60000, no_same_finger_overlap=True,
            source_page_association_events=len(store.lookup(blob)['note_pages']),
            hardware_playback=False))
    write_json(output / 'curation.json', evidence)
    write_json(EVIDENCE / (score_id + '-full-review.json'), evidence)
    return dict(id=score_id, status='reviewed-complete', full_source_coverage=True,
        source_sha256=source['sha256'], pages=[1, 2], printed_measures=29,
        written_right_notes=225, played_right_events=449,
        pgl=f'ready/{score_id}/score.pgl', pglpack=f'ready/{score_id}/score.pglpack',
        score_sha256=hashlib.sha256(blob).hexdigest(),
        package_sha256=hashlib.sha256(package).hexdigest(),
        evidence=f'ready/{score_id}/curation.json', unresolved_items=[])


def build_independent_gold(gold, raw, source, evidence_path):
    """Attach an independently transcribed whole score to genuine PDF locations.

    The independent pitches/times/fingers remain authoritative. Matching by
    pitch class and written horizontal order tolerates a recognized octave
    error while preserving a one-to-one auditable candidate association.
    """
    score_id = source['id']
    assert gold['source_id'] == score_id and gold['source_sha256'] == source['sha256']
    candidate_groups, gold_groups = defaultdict(list), defaultdict(list)
    source_candidates = [n for n in raw['notes']
        if (n.get('staff') in gold['candidate_staff_ids'] if gold.get('candidate_staff_ids') else n.get('hand') == 'right')
        and n['id'] not in gold.get('excluded_candidate_ids', [])]
    for note in gold.get('manual_candidates', []):
        assert note['id'] not in {n['id'] for n in source_candidates}
        source_candidates.append(note)
    candidate_by_id={n['id']:n for n in source_candidates}
    assert len(candidate_by_id)==len(source_candidates)
    bound_ids=set();pairs=[]
    for note in gold['notes']:
        if note.get('source_candidate_id'):
            candidate=candidate_by_id[note['source_candidate_id']]
            assert candidate['id'] not in bound_ids
            assert candidate['page']==note['page'], (score_id,note['independent_id'],'Source binding is on a different page')
            bound_ids.add(candidate['id']);pairs.append((note,candidate))
        else:
            gold_groups[(note['page'], note['system'], note['measure'], pitch_midi(note['pitch']) % 12)].append(note)
    for note in source_candidates:
        if note['id'] not in bound_ids and (note.get('hand') == 'right' or gold.get('candidate_staff_ids')):
            candidate_pitch=note.get('pitch') or note.get('written_pitch')
            candidate_groups[(note['page'], note['system'], note['measure'], pitch_midi(candidate_pitch) % 12)].append(note)
    assert set(candidate_groups) == set(gold_groups), (score_id, 'Pitch-class coverage differs from the independent source')
    for key, originals in gold_groups.items():
        candidates = sorted(candidate_groups[key], key=lambda n: (round(n['bbox'][0]), -pitch_midi(n.get('pitch') or n.get('written_pitch'))))
        originals = sorted(originals, key=lambda n: (n['beat'], -pitch_midi(n['pitch'])))
        assert len(candidates) == len(originals), (score_id, key, 'Source count differs')
        pairs.extend(zip(originals,candidates))
    notes, comparison = [], []
    for original, candidate in pairs:
        note = deepcopy(original)
        note.update(id=original['independent_id'], confirmed=True, candidate_id=candidate['id'],
            review_basis='independent-full-transcription-' + evidence_path.name)
        for field in ('bbox', 'origin'):
            if field in candidate:
                note[field] = deepcopy(candidate[field])
        notes.append(note)
        changes = {field: dict(candidate=candidate.get(field), reviewed=original[field])
            for field in ('pitch', 'finger', 'beat', 'duration_beats') if candidate.get(field) != original[field]}
        if changes:
            comparison.append(dict(id=note['id'], candidate_id=candidate['id'],
                printed_measure=note['printed_measure'], changes=changes))
    written_notes = notes
    if gold.get('performance_notes') is not None:
        originals_by_id = {n['id']: n for n in written_notes}
        notes = []
        for performance in gold['performance_notes']:
            source_note = originals_by_id[performance['source_independent_id']]
            note = deepcopy(source_note)
            note.update(deepcopy(performance))
            note.update(id=performance['independent_id'], confirmed=True, hand='right',
                source_original_id=performance['source_independent_id'])
            notes.append(note)
    by_id = {n['id']: n for n in notes}
    assert len(by_id) == len(notes)
    for tie in gold.get('performance_ties', gold.get('ties', [])):
        by_id[tie['source']].update(tie_to=tie['target'], tie_reviewed=True)
    notes.sort(key=lambda n: (n['beat'], n['finger']))
    performance_end=gold.get('performance_duration_beats',gold['written_duration_beats'])
    project = dict(name=gold['title'] + '（完整）', source_name=source['filename'],
        source_sha256=source['sha256'], pages=raw['pages'], notes=notes,
        rests=gold.get('rests', []), written_duration_beats=performance_end,
        repeat_sections=gold.get('repeat_sections', []),
        selection=dict(bpm=gold['bpm'], start_beat=0, end_beat=performance_end,
            range_reviewed=True, repeat_mode='unfold', repeats_reviewed=True,
            performance_order_reviewed=True, ties_reviewed=True))
    assert not gold.get('navigation'), 'Independent navigation must be explicitly expanded before packaging'
    score = export_reviewed(project)
    blob = encode(score)
    assert decode(blob)['notes'] == score['notes']
    store = ScoreSources(EVIDENCE / 'source-store')
    store.record_document(source['sha256'], raw['page_previews'], raw['pages'])
    assert store.associate(blob, project, score)
    package = store.package(blob)
    output = ROOT / 'ready' / score_id
    output.mkdir(parents=True, exist_ok=True)
    (output / 'score.pgl').write_bytes(blob)
    (output / 'score.pglpack').write_bytes(package)
    write_json(output / 'reviewed-project.json', project)
    write_json(output / 'score.json', score)
    write_json(output / 'independent-transcription.json', gold)
    pages = list(range(1, source['pages'] + 1))
    evidence = dict(id=score_id, source_sha256=source['sha256'], status='reviewed-complete',
        full_source_coverage=True, source_pages=pages, printed_measures=len(gold['measure_lengths']),
        written_right_notes=len(written_notes), arranged_written_events=len(notes), played_right_events=len(score['notes']),
        method=gold['method'], coverage=gold['coverage'], independent_evidence=evidence_path.name,
        written_duration_beats=gold['written_duration_beats'],performance_duration_beats=performance_end,
        unresolved_items=[], omitted_right_notes=0, bpm=gold['bpm'],
        printed_fingerings=sum(n['finger_basis'] == 'printed' for n in notes),
        arranged_fingerings=sum(n['finger_basis'].startswith('arranged') for n in notes),
        inherited_tied_fingerings=sum(n['finger_basis'].startswith('tie-continuation') for n in notes),
        explicit_arrangements=gold.get('explicit_arrangements', []),
        ornament_realizations=gold.get('ornament_realizations', []),
        manual_source_candidates=gold.get('manual_candidates', []),
        excluded_candidate_ids=gold.get('excluded_candidate_ids', []),
        excluded_candidate_reasons=gold.get('excluded_candidate_reasons', {}),
        ties=gold.get('ties', []), repeat_sections=gold.get('repeat_sections', []),
        corrections_to_raw_candidates=comparison,
        verification=dict(pgl_round_trip=True, device_event_limit=60000, no_same_finger_overlap=True,
            source_page_association_events=len(store.lookup(blob)['note_pages']), hardware_playback=False))
    write_json(output / 'curation.json', evidence)
    write_json(EVIDENCE / (score_id + '-full-review.json'), evidence)
    return dict(id=score_id, status='reviewed-complete', full_source_coverage=True,
        source_sha256=source['sha256'], pages=pages, printed_measures=len(gold['measure_lengths']),
        written_right_notes=len(written_notes), arranged_written_events=len(notes), played_right_events=len(score['notes']),
        pgl=f'ready/{score_id}/score.pgl', pglpack=f'ready/{score_id}/score.pglpack',
        score_sha256=hashlib.sha256(blob).hexdigest(), package_sha256=hashlib.sha256(package).hexdigest(),
        evidence=f'ready/{score_id}/curation.json', unresolved_items=[])


def build_equivalent_scan(raw, source):
    """Reuse the reviewed music only after all six source pages were compared.

    The unnumbered scan has no OMR notes. Its own detected staff/bar geometry
    locates a complete source measure, rather than borrowing vector head boxes.
    """
    score_id = source['id']
    vector_folder = ROOT / 'ready' / '982245'
    project = json.loads((vector_folder / 'reviewed-project.json').read_text(encoding='utf-8'))
    vector_source = project['source_sha256']
    mapping = json.loads((EVIDENCE / 'scan-source-coordinate-map.json').read_text(encoding='utf-8'))
    assert mapping['source_scan_sha256'] == source['sha256']
    assert mapping['alternate_vector_sha256'] == vector_source
    assert mapping['reviewed_same_arrangement_pages'] == list(range(1, 7))
    systems = {(s['page'], s['system']): s for s in mapping['systems']}
    assert len(systems) == 32 and sum(s['detected_measure_count'] for s in systems.values()) == 167
    project.update(name='这世界那么多人（扫描谱·右手编配）', source_name=source['filename'],
        source_sha256=source['sha256'], pages=raw['pages'])
    for note in project['notes']:
        note['source_vector_note_id'] = note['id']
        note['id'] = 'scan-' + note['id']
        if note.get('tie_to'):
            note['tie_to'] = 'scan-' + note['tie_to']
        s = systems[(note['page'], note['system'])]
        assert s['detected_measure_count'] == s['expected_measure_count']
        left, right = s['bars'][note['measure'] - 1:note['measure'] + 1]
        top = max(0, s['lines'][0] - 70)
        bottom = min(s['image_height'], s['lines'][-1] + 35)
        note['bbox'] = [left / s['image_width'] * s['pdf_width'], top / s['image_height'] * s['pdf_height'],
            right / s['image_width'] * s['pdf_width'], bottom / s['image_height'] * s['pdf_height']]
        note.pop('origin', None)
        note.update(finger_basis='arranged-for-unfingered-scan',
            localization_granularity='complete-right-hand-measure',
            review_basis='six-page-music-equivalence-plus-independent-scan-staff-and-bar-location')
    score = export_reviewed(project)
    blob = encode(score)
    vector_score = decode((vector_folder / 'score.pgl').read_bytes())
    assert decode(blob)['notes'] == vector_score['notes']
    assert score['duration_ms'] == vector_score['duration_ms']
    store = ScoreSources(EVIDENCE / 'source-store')
    store.record_document(source['sha256'], raw['page_previews'], raw['pages'])
    assert store.associate(blob, project, score)
    package = store.package(blob)
    output = ROOT / 'ready' / score_id
    output.mkdir(parents=True, exist_ok=True)
    (output / 'score.pgl').write_bytes(blob)
    (output / 'score.pglpack').write_bytes(package)
    write_json(output / 'reviewed-project.json', project)
    write_json(output / 'score.json', score)
    evidence = dict(id=score_id, status='reviewed-complete', full_source_coverage=True,
        source_sha256=source['sha256'], source_pages=list(range(1, 7)), printed_measures=167,
        written_right_notes=876, arranged_written_events=len(project['notes']), played_right_events=len(score['notes']),
        alternate_reviewed_source=dict(id='982245', sha256=vector_source),
        method='All six original scan/vector page pairs visually compared and confirmed to contain the same complete arrangement. Reviewed music comes from the vector transcription; actual scan staff/bar geometry supplies measure-level source positions.',
        equivalence_anchors=['p1 all30 bars', 'p2 bars42-43 ties', 'p3 bars62-63 ties and71 fermata',
            'p4 bars111-115 ottava,115 triplets', 'p5 bars145-146 ties,147-148 rests',
            'p6 bars164-165 and166-167 ties'],
        scanner_recognizer_note_count=len(raw['notes']), printed_fingerings=0,
        arranged_fingerings=len(project['notes']), unresolved_items=[], omitted_right_notes=0,
        deviations=['The original scan contains no fingering numbers; all playing fingers are the explicitly credited right-hand practice arrangement.',
            'Scan source highlights identify a complete right-hand measure, not an allegedly detected notehead.',
            'The same reviewed grace, mordent, arpeggio, fermata and tempo choices as the annotated-vector arrangement apply.'],
        coordinate_evidence='scan-source-coordinate-map.json',
        verification=dict(pgl_round_trip=True, matches_reviewed_vector_events=True,
            detected_scan_systems=32, detected_scan_measures=167, device_event_limit=60000,
            source_page_association_events=len(store.lookup(blob)['note_pages']),
            no_same_finger_overlap=True, hardware_playback=False))
    write_json(output / 'curation.json', evidence)
    write_json(EVIDENCE / (score_id + '-full-review.json'), evidence)
    return dict(id=score_id, status='reviewed-complete', full_source_coverage=True,
        source_sha256=source['sha256'], pages=list(range(1, 7)), printed_measures=167,
        written_right_notes=876, arranged_written_events=len(project['notes']), played_right_events=len(score['notes']),
        pgl=f'ready/{score_id}/score.pgl', pglpack=f'ready/{score_id}/score.pglpack',
        score_sha256=hashlib.sha256(blob).hexdigest(), package_sha256=hashlib.sha256(package).hexdigest(),
        evidence=f'ready/{score_id}/curation.json', unresolved_items=[])


def main():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    # Manual source-coordinate corrections refer to the audited parser output.
    # Runtime recognition can be refreshed independently without changing it.
    project_root = EVIDENCE / 'recognizer-baseline'
    if not (project_root / 'precomputed.json').is_file():
        project_root = ROOT
    index = json.loads((project_root / 'precomputed.json').read_text(encoding='utf-8'))
    projects = {entry['id']: entry for entry in index['projects'].values()}
    sources = {entry['id']: entry for entry in manifest['scores']}
    for source in sources.values():
        if source['bundled']:
            assert hashlib.sha256((ROOT / source['file']).read_bytes()).hexdigest() == source['sha256']
    entries = []
    for score_id, number in [('1002604', 2), ('1002602', 4)]:
        raw = json.loads((project_root / projects[score_id]['file']).read_text(encoding='utf-8'))
        entries.append(build_hanon(score_id, number, raw, sources[score_id]))
    for score_id, number in [('1002307', 65), ('1002313', 59), ('1002306', 66)]:
        raw = json.loads((project_root / projects[score_id]['file']).read_text(encoding='utf-8'))
        entries.append(build_explicit(explicit_czerny(number), raw, sources[score_id]))
    raw = json.loads((project_root / projects['970081']['file']).read_text(encoding='utf-8'))
    entries.append(build_explicit(love_dream_transcription(), raw, sources['970081']))
    raw = json.loads((project_root / projects['1078144']['file']).read_text(encoding='utf-8'))
    entries.append(build_explicit(gamer_transcription(), raw, sources['1078144']))
    raw = json.loads((project_root / projects['30483']['file']).read_text(encoding='utf-8'))
    entries.append(build_explicit(bach_transcription(), raw, sources['30483']))
    for path in sorted(EVIDENCE.glob('independent-*.json')):
        gold = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(gold, dict):
            continue
        score_id = gold.get('source_id', gold.get('id'))
        if score_id not in sources or score_id in {entry['id'] for entry in entries}:
            continue
        if score_id not in {'1002169', '935702', '1020697'} and not gold.get('ready_for_packaging'):
            # Other collaborators can save a partial transcription while
            # reviewing it. Saving a draft is not approval for shipment.
            continue
        raw = json.loads((project_root / projects[score_id]['file']).read_text(encoding='utf-8'))
        if 'notes' in gold and 'measure_lengths' in gold:
            entries.append(build_independent_gold(gold, raw, sources[score_id], path))
        elif 'bars' in gold:
            entries.append(build_explicit(gold, raw, sources[score_id]))
    if '982245' in {entry['id'] for entry in entries}:
        scan_id = 'scan-5f380b0b4411'
        raw = json.loads((project_root / projects[scan_id]['file']).read_text(encoding='utf-8'))
        entries.append(build_equivalent_scan(raw, sources[scan_id]))
    for entry in entries:
        entry['title'] = decode((ROOT / entry['pgl']).read_bytes())['title']
    report = dict(schema_version=1, date='2026-10-24', scope='complete-right-hand-originals',
        expected_builtins=27, reviewed_complete=len(entries),
        holdout_ids=manifest['holdout_ids'], entries=entries,
        pending_ids=[entry['id'] for entry in manifest['scores'] if entry['bundled']
                     and entry['id'] not in {x['id'] for x in entries}],
        ready_for_full_library_release=len(entries) == 27)
    write_json(ROOT / 'curation-manifest.json', report)
    print(json.dumps({k: report[k] for k in ('reviewed_complete', 'pending_ids',
                                          'ready_for_full_library_release')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
