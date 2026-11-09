'use strict';

const STATUS_LABEL = {
  teacher: 'Замена учителя',
  subject: 'Другой предмет',
  room: 'Другой кабинет',
  cancel: 'Отменён',
  move_out: 'Перенесён',
  move_in: 'Перенесён',
};

const state = { meta: null, classId: null, picking: false };
const $main = document.getElementById('main');
const $classBtn = document.getElementById('class-btn');

const today = () => state.meta.today;
const bell = (n) => state.meta.bells.find((b) => b.lesson_no === n);

function lessonCard(e, date) {
  const b = bell(e.lesson_no);
  const struck = e.status === 'cancel' || e.status === 'move_out';
  const orig = e.orig || {};

  let note = null;
  if (e.status === 'teacher' && orig.teacher) note = `вместо: ${shortName(orig.teacher)}`;
  else if (e.status === 'subject') note = orig.subject ? `вместо: ${orig.subject}` : 'дополнительный урок';
  else if (e.status === 'room' && orig.room) note = `вместо каб. ${orig.room}`;
  else if (e.status === 'move_out') {
    note = e.move.date === date ? `на ${e.move.lesson_no}-й урок` : `на ${formatShort(e.move.date)}, ${e.move.lesson_no}-й урок`;
  } else if (e.status === 'move_in') {
    note = e.move.date === date ? `с ${e.move.lesson_no}-го урока` : `с ${formatShort(e.move.date)}, ${e.move.lesson_no}-го урока`;
  }

  const details = [e.group_no && `${e.group_no} группа`, !struck && shortName(e.teacher), !struck && e.room && `каб. ${e.room}`]
    .filter(Boolean).join(' · ');
  return h('li', { class: `lesson st-${e.status}${struck ? ' struck' : ''}` },
    h('div', { class: 'num' }, e.lesson_no),
    h('div', { class: 'head' },
      h('span', { class: 'subject' }, e.subject || '—'),
      h('span', { class: 'time' }, b ? b.start : '')),
    h('div', null,
      details ? h('div', { class: 'meta' }, details) : null,
      STATUS_LABEL[e.status]
        ? h('div', { class: `change-note st-${e.status}` }, STATUS_LABEL[e.status], note ? ` — ${note}` : '')
        : null,
      e.comment ? h('div', { class: 'comment' }, e.comment) : null));
}

function dayBlock(title, day) {
  return h('section', null,
    h('h2', { class: 'day-title' }, title, h('span', { class: 'muted' }, formatDayTitle(day.date))),
    day.lessons.length
      ? h('ul', { class: 'lessons' }, day.lessons.map((e) => lessonCard(e, day.date)))
      : h('div', { class: 'empty' }, 'Уроков нет'));
}

function renderPicker() {
  const list = h('div', { class: 'grade-list' }, state.meta.classes.map((c) => h('button', {
    type: 'button',
    'aria-current': c.id === state.classId ? 'true' : null,
    onclick: () => {
      state.classId = c.id;
      state.picking = false;
      Storage.set('classId', String(c.id));
      render();
    },
  }, c.name)));
  return h('div', { class: 'picker' },
    h('h2', null, 'Выберите класс'),
    state.meta.classes.length ? list : h('div', { class: 'empty' }, 'Классы ещё не добавлены.'));
}

async function renderSchedule() {
  const data = await Api.get('/api/schedule', { class_id: state.classId, start: today(), days: 8 });
  const [first, ...rest] = data.days;
  const next = rest.find((d) => d.lessons.length);
  const nextTitle = next && next.date === addDays(today(), 1) ? 'Завтра' : 'Следующий учебный день';
  return h('div', null,
    first.lessons.length ? dayBlock('Сегодня', first) : null,
    next ? dayBlock(nextTitle, next) : null,
    !first.lessons.length && !next ? h('div', { class: 'empty' }, 'Уроков на ближайшую неделю нет') : null);
}

async function render() {
  document.getElementById('school-name').textContent = state.meta.school_name;
  document.title = `Расписание — ${state.meta.school_name}`;
  document.getElementById('updated').textContent = formatUpdated(state.meta.last_updated, today());
  const cls = state.meta.classes.find((c) => c.id === state.classId);
  if (!cls) state.classId = null;
  $classBtn.hidden = !cls || state.picking;
  document.getElementById('class-label').textContent = cls ? cls.name : '';

  if (!state.classId || state.picking) {
    clear($main).append(renderPicker());
    return;
  }
  try {
    clear($main).append(await renderSchedule());
  } catch (err) {
    clear($main).append(h('div', { class: 'error-box' }, err.message));
  }
}

async function refresh() {
  if (document.hidden || state.picking) return;
  try {
    const meta = await Api.get('/api/meta');
    const changed = meta.last_updated !== state.meta.last_updated || meta.today !== state.meta.today;
    state.meta = meta;
    if (changed) render();
  } catch { /* попробуем в следующий раз */ }
}

async function init() {
  const saved = Number(Storage.get('classId'));
  state.classId = saved > 0 ? saved : null;
  $classBtn.addEventListener('click', () => { state.picking = true; render(); });
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, 60_000);
  try {
    state.meta = await Api.get('/api/meta');
  } catch (err) {
    clear($main).append(h('div', { class: 'error-box' }, err.message));
    return;
  }
  render();
}

init();
