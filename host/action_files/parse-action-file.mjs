// Candidate file format only. Pure parsing: no transport, timers or motion.
export const FINGER_TO_SLOT = Object.freeze({ 1: 0, 2: 2, 3: 3, 4: 4, 5: 5 });
export const MAX_DURATION_MS = 300000;
export const MAX_EVENTS = 2000;

function exactKeys(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} 必须是对象`);
  const actual = Object.keys(value);
  if (actual.length !== keys.length || actual.some(k => !keys.includes(k))) {
    throw new Error(`${label} 只允许且必须包含 ${keys.join(', ')}`);
  }
}

/** Parse explicit fingering and timing. No automatic fingering is generated. */
export function parseActionFile(input) {
  if (typeof input === 'string' && input.length > 1000000) throw new Error('动作文件过大，最多 100 万字符');
  const source = typeof input === 'string' ? JSON.parse(input) : input;
  exactKeys(source, ['version', 'name', 'events'], '文件');
  if (source.version !== 1) throw new Error('version 必须为数字 1');
  if (typeof source.name !== 'string' || !source.name.trim() || source.name.length > 100) throw new Error('name 必须为 1–100 字符的非空名称');
  if (!Array.isArray(source.events) || source.events.length === 0 || source.events.length > MAX_EVENTS) throw new Error(`events 必须包含 1–${MAX_EVENTS} 个明确指法事件`);
  const events = source.events.map((event, index) => {
    const label = `events[${index}]`;
    exactKeys(event, ['t_ms', 'finger', 'duration_ms'], label);
    if (!Number.isFinite(event.t_ms) || event.t_ms < 0) throw new Error(`${label}.t_ms 必须为非负有限数字`);
    if (!Number.isFinite(event.duration_ms) || event.duration_ms <= 0) throw new Error(`${label}.duration_ms 必须为正有限数字`);
    if (!Number.isInteger(event.finger) || event.finger < 1 || event.finger > 5) throw new Error(`${label}.finger 必须为 1–5 的整数`);
    if (event.t_ms + event.duration_ms > MAX_DURATION_MS) throw new Error(`动作总时长不能超过 ${MAX_DURATION_MS / 1000} 秒；请拆分文件`);
    return { t_ms: event.t_ms, finger: event.finger, duration_ms: event.duration_ms, slot: FINGER_TO_SLOT[event.finger], source_index: index };
  }).sort((a, b) => a.t_ms - b.t_ms || a.finger - b.finger);
  const previousEnd = new Map();
  for (const event of events) {
    if (previousEnd.has(event.finger) && event.t_ms < previousEnd.get(event.finger)) throw new Error(`手指 ${event.finger} 的动作时间重叠（原事件 ${event.source_index}）`);
    previousEnd.set(event.finger, event.t_ms + event.duration_ms);
  }
  const duration_ms = Math.max(...events.map(e => e.t_ms + e.duration_ms));
  const warnings = ['候选格式，尚未确认甲方认可；解析通过不等于硬件安全或实际动作通过。', '执行前须确认拇指按压仍为 slot 0，侧摆为 slot 1；角色若对调，应停止并重新核对映射。'];
  if (duration_ms > 30000) warnings.push('文件超过 30 秒，交付演示建议拆成较短段落。');
  for (let finger = 1; finger <= 5; finger++) {
    const same = events.filter(e => e.finger === finger);
    if (same.some((e, i) => i > 0 && e.t_ms - (same[i - 1].t_ms + same[i - 1].duration_ms) < 500)) {
      warnings.push(`手指 ${finger} 的松开间隔不足 500 ms，必须按实机校准确认，不代表安全动作。`);
    }
  }
  return { version: 1, name: source.name.trim(), events, duration_ms, warnings };
}
