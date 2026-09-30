import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseActionFile, FINGER_TO_SLOT } from './parse-action-file.mjs';
const make = events => ({ version: 1, name: 'test', events });
const event = (t_ms = 0, finger = 1, duration_ms = 250) => ({ t_ms, finger, duration_ms });

test('candidate sample is 12.85 seconds and never maps side-swing slot 1', () => {
  const r = parseActionFile(readFileSync(new URL('./sparse-five-fingers.candidate.json', import.meta.url), 'utf8'));
  assert.equal(r.duration_ms, 12850);
  assert.equal(r.events.length, 10);
  assert.deepEqual(r.events.slice(0, 5).map(e => e.slot), [0, 2, 3, 4, 5]);
  assert.ok(r.events.every(e => e.slot !== 1));
  assert.ok(r.warnings.some(w => w.includes('尚未确认甲方认可')));
  assert.ok(Object.isFrozen(FINGER_TO_SLOT));
});
test('rejects invalid finite times and positive durations without coercion', () => {
  for (const time of [-1, NaN, Infinity, -Infinity, '0', null]) assert.throws(() => parseActionFile(make([event(time)])));
  for (const duration of [0, -1, NaN, Infinity, '250', null]) assert.throws(() => parseActionFile(make([event(0, 1, duration)])));
});
test('explicit fingers required; rejects out of bounds and inferred pitch input', () => {
  for (const finger of [0, 6, 1.5, '1', NaN, null]) assert.throws(() => parseActionFile(make([event(0, finger)])));
  assert.throws(() => parseActionFile(make([{ t_ms: 0, note: 60, duration_ms: 250 }])));
});
test('overlap checked after sorting; different fingers may be simultaneous', () => {
  assert.throws(() => parseActionFile(make([event(100), event(0)])), /重叠/);
  assert.throws(() => parseActionFile(make([event(0), event(0)])), /重叠/);
  assert.equal(parseActionFile(make([event(0, 2), event(0, 1)])).events.length, 2);
  assert.equal(parseActionFile(make([event(250), event(0)])).events.length, 2);
});
test('duration bound includes ending time and warns for long clips', () => {
  assert.throws(() => parseActionFile(make([event(300000)])), /不能超过/);
  assert.throws(() => parseActionFile(make([event(Number.MAX_VALUE, 1, Number.MAX_VALUE)])), /不能超过/);
  assert.equal(parseActionFile(make([event(299750)])).duration_ms, 300000);
  assert.ok(parseActionFile(make([event(31000)])).warnings.some(w => w.includes('超过 30 秒')));
});
test('reject malformed schema, empty files and excess events', () => {
  for (const input of [null, [], '{}', '{', make([]), { ...make([event()]), version: 2 }, { ...make([event()]), name: ' ' }, { ...make([event()]), extra: true }, make(Array.from({ length: 2001 }, () => event()))]) assert.throws(() => parseActionFile(input));
});
test('parsing does not mutate input and emits no inferred events', () => {
  const input = make([event(1400, 2), event(0, 1)]);
  const snapshot = JSON.stringify(input);
  const result = parseActionFile(input);
  assert.equal(JSON.stringify(input), snapshot);
  assert.equal(result.events.length, input.events.length);
  assert.equal(result.events[0].source_index, 1);
});
