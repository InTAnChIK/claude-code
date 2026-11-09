'use strict';

const VIEWS = ['today', 'tomorrow', 'week', 'changes', 'search'];
const STATUS_LABEL = {
  teacher: 'Замена учителя',
  subject: 'Другой предмет',
  room: 'Смена кабинета',
  cancel: 'Отмена урока',
  move_out: 'Перенос',
  move_in: 'Перенос',
};
const REFRESH_MS = 60_000;

const state = {
  meta: null,
  classId: null,
  view: 'today',
  picking: false,
  weekOffset: null,
  changesScope: 'class',
  searchKind: 'teacher',
  searchId: null,
  searchQuery: '',
};
let renderToken = 0;

const $main = document.getElementById('main');
const $tabs = document.getElementById('tabs');
const $classBtn = document.getElementById('class-btn');

const today = () => state.meta.today;
const currentClass = () => state.meta.classes.find((c) => c.id === state.classId);
const bell = (n) => state.meta.bells.find((b) => b.lesson_no === n);

/* ---------- карточка урока ---------- */
function lessonCard(e, { showClass = false, highlightNow = false } = {}) {
  const b = bell(e.lesson_no);
  const struck = e.status === 'cancel' || e.status === 'move_out';
  const orig = e.orig || {};
  let isNow = false;
  if (highlightNow && b && !struck) {
    const now = new Date();
    const hm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    isNow = b.start <= hm && hm < b.end;
  }

  const teacherLine = [];
  if (e.teacher) {
    teacherLine.push(h('b', null, shortName(e.teacher)));
    if (e.status === 'teacher' && orig.teacher && orig.teacher !== e.teacher) {
      teacherLine.push(` (вместо: ${shortName(orig.teacher)})`);
    }
  }
  if (e.room) {
    if (teacherLine.length) teacherLine.push(' · ');
    teacherLine.push('каб. ', h('b', null, e.room));
    if (orig.room && orig.room !== e.room && !struck) teacherLine.push(` (вместо: ${orig.room})`);
  }

  let was = null;
  if (e.status === 'subject') {
    was = orig.subject && orig.subject !== e.subject ? `вместо: ${orig.subject}` : 'дополнительный урок';
  } else if (e.status === 'cancel') {
    was = 'Урок отменён';
  } else if (e.status === 'move_out') {
    was = e.move.date === e.date
      ? `Перенесён на ${e.move.lesson_no}-й урок`
      : `Перенесён на ${formatShort(e.move.date)}, ${e.move.lesson_no}-й урок`;
  } else if (e.status === 'move_in') {
    was = e.move.date === e.date
      ? `Перенесён с ${e.move.lesson_no}-го урока`
      : `Перенесён с ${formatShort(e.move.date)}, ${e.move.lesson_no}-го урока`;
  }

  return h('li', { class: `lesson st-${e.status}${struck ? ' struck' : ''}${isNow ? ' now' : ''}` },
    h('div', { class: 'num', 'aria-label': `${e.lesson_no}-й урок` }, e.lesson_no),
    h('div', { class: 'head' },
      h('span', { class: 'time' }, b ? `${b.start}–${b.end}` : ''),
      isNow ? h('span', { class: 'now-tag' }, 'идёт сейчас') : null,
      STATUS_LABEL[e.status] ? h('span', { class: `badge st-${e.status}` }, STATUS_LABEL[e.status]) : null),
    h('div', { class: 'subject' },
      showClass ? h('span', { class: 'class-tag' }, `${e.class_name} · `) : null,
      e.subject || '—'),
    h('div', null,
      teacherLine.length ? h('div', { class: 'meta' }, teacherLine) : null,
      was ? h('div', { class: 'was' }, was) : null,
      e.comment ? h('div', { class: 'comment' }, e.comment) : null));
}

function dayBlock(day, opts = {}) {
  const isToday = day.date === today();
  const wrap = h('section', { class: `day${day.date < today() ? ' past' : ''}` },
    h('h2', { class: 'day-title' }, formatDayTitle(day.date),
      isToday ? h('span', { class: 'muted' }, 'сегодня') : null,
      opts.note ? h('span', { class: 'muted' }, opts.note) : null));
  const lessons = day.lessons.map((e) => lessonCard({ ...e, date: day.date }, { ...opts, highlightNow: isToday }));
  wrap.append(lessons.length
    ? h('ul', { class: 'lessons' }, lessons)
    : h('div', { class: 'empty' }, opts.emptyText || 'Уроков нет'));
  return wrap;
}

/* ---------- экраны ---------- */
function renderPicker() {
  const groups = new Map();
  for (const c of state.meta.classes) {
    const g = classGrade(c.name);
    const key = g == null ? 'Другие' : `${g} класс`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(c);
  }
  const wrap = h('div', { class: 'picker' },
    h('h2', null, 'Выберите класс'),
    h('p', { class: 'muted small' }, 'Выбор запомнится на этом устройстве — в следующий раз сразу откроется ваше расписание.'));
  if (!state.meta.classes.length) {
    wrap.append(h('div', { class: 'empty' }, 'Классы ещё не добавлены администратором.'));
  }
  for (const [title, list] of groups) {
    wrap.append(h('div', { class: 'grade' },
      h('div', { class: 'grade-title' }, title),
      h('div', { class: 'grade-list' }, list.map((c) => h('button', {
        type: 'button',
        'aria-current': c.id === state.classId ? 'true' : null,
        onclick: () => selectClass(c.id),
      }, c.name)))));
  }
  if (state.classId) {
    wrap.append(h('p', null, h('button', { class: 'btn ghost', type: 'button', onclick: () => { state.picking = false; render(); } }, 'Отмена')));
  }
  return wrap;
}

async function viewToday() {
  const data = await Api.get('/api/schedule', { class_id: state.classId, start: today(), days: 1 });
  return dayBlock(data.days[0], { emptyText: 'Сегодня уроков нет' });
}

async function viewTomorrow() {
  const tomorrow = addDays(today(), 1);
  const data = await Api.get('/api/schedule', { class_id: state.classId, start: tomorrow, days: 7 });
  const first = data.days.find((d) => d.lessons.length);
  if (!first) return dayBlock(data.days[0], { emptyText: 'Завтра уроков нет' });
  if (first.date === tomorrow) return dayBlock(first);
  return h('div', null,
    h('div', { class: 'empty' }, 'Завтра уроков нет.'),
    dayBlock(first, { note: 'ближайший учебный день' }));
}

async function viewWeek() {
  if (state.weekOffset == null) {
    const lastDay = Math.max(...state.meta.school_days);
    state.weekOffset = isoWeekday(today()) > lastDay ? 1 : 0;
  }
  const start = addDays(mondayOf(today()), state.weekOffset * 7);
  const data = await Api.get('/api/schedule', { class_id: state.classId, start, days: 7 });
  const days = data.days.filter((d) => d.is_school_day || d.lessons.length);
  const first = days[0]?.date ?? start;
  const last = days[days.length - 1]?.date ?? addDays(start, 6);
  const f = parseDate(first);
  const l = parseDate(last);
  const label = f.getMonth() === l.getMonth()
    ? `${f.getDate()}–${l.getDate()} ${MONTHS_GEN[l.getMonth()]}`
    : `${f.getDate()} ${MONTHS_GEN[f.getMonth()]} – ${l.getDate()} ${MONTHS_GEN[l.getMonth()]}`;

  const shift = (n) => { state.weekOffset += n; render(); };
  return h('div', null,
    h('div', { class: 'week-nav' },
      h('button', { class: 'btn small', type: 'button', onclick: () => shift(-1), 'aria-label': 'Предыдущая неделя', disabled: state.weekOffset <= -1 }, '‹'),
      h('div', { class: 'label' }, label),
      h('button', { class: 'btn small', type: 'button', onclick: () => shift(1), 'aria-label': 'Следующая неделя', disabled: state.weekOffset >= 2 }, '›')),
    h('div', { class: 'week-grid' }, days.map((d) => dayBlock(d))));
}

async function viewChanges() {
  const scopeBtn = (scope, text) => h('button', {
    type: 'button',
    'aria-pressed': String(state.changesScope === scope),
    onclick: () => { state.changesScope = scope; render(); },
  }, text);
  const params = state.changesScope === 'class' ? { class_id: state.classId } : {};
  const data = await Api.get('/api/changes', params);
  const showClass = state.changesScope !== 'class';
  const content = data.days.length
    ? data.days.map((d) => dayBlock({ date: d.date, lessons: d.items }, { showClass }))
    : h('div', { class: 'empty' }, 'Изменений на ближайшие дни нет.');
  return h('div', { class: 'stack' },
    h('div', { class: 'segmented', role: 'group', 'aria-label': 'Какие изменения показать' },
      scopeBtn('class', `Мой класс (${currentClass().name})`),
      scopeBtn('all', 'Все классы')),
    h('div', null, content));
}

async function viewSearch() {
  const results = h('div', { 'aria-live': 'polite' });
  const items = state.searchKind === 'teacher' ? state.meta.teachers : state.meta.rooms;
  const chips = h('div', { class: 'chips' });

  const drawChips = () => {
    const q = state.searchQuery.trim().toLowerCase();
    const filtered = items.filter((i) => i.name.toLowerCase().includes(q));
    clear(chips).append(...(filtered.length ? filtered.map((i) => h('button', {
      type: 'button',
      class: 'chip',
      'aria-pressed': String(i.id === state.searchId),
      onclick: () => { state.searchId = i.id; drawChips(); loadResults(); },
    }, state.searchKind === 'teacher' ? i.name : `каб. ${i.name}`)) : [h('span', { class: 'muted small' }, 'Ничего не найдено')]));
  };

  const loadResults = async () => {
    if (!state.searchId) {
      clear(results).append(h('p', { class: 'muted small' },
        state.searchKind === 'teacher' ? 'Выберите учителя, чтобы увидеть его уроки на неделю.' : 'Выберите кабинет, чтобы увидеть, какие уроки в нём проходят.'));
      return;
    }
    const params = { start: today(), days: 7, [state.searchKind === 'teacher' ? 'teacher_id' : 'room_id']: state.searchId };
    clear(results).append(h('p', { class: 'muted small' }, 'Загрузка…'));
    try {
      const data = await Api.get('/api/search', params);
      const days = data.days.filter((d) => d.lessons.length);
      clear(results).append(...(days.length
        ? days.map((d) => dayBlock(d, { showClass: true }))
        : [h('div', { class: 'empty' }, 'На ближайшие 7 дней уроков нет.')]));
    } catch (err) {
      clear(results).append(h('div', { class: 'error-box' }, err.message));
    }
  };
  state.reloadSearch = loadResults;

  const kindBtn = (kind, text) => h('button', {
    type: 'button',
    'aria-pressed': String(state.searchKind === kind),
    onclick: () => { state.searchKind = kind; state.searchId = null; state.searchQuery = ''; render(); },
  }, text);

  drawChips();
  loadResults();
  return h('div', { class: 'stack' },
    h('div', { class: 'segmented', role: 'group', 'aria-label': 'Что искать' },
      kindBtn('teacher', 'Учитель'), kindBtn('room', 'Кабинет')),
    h('div', null,
      h('input', {
        type: 'search',
        placeholder: state.searchKind === 'teacher' ? 'Фамилия учителя' : 'Номер кабинета',
        'aria-label': 'Поиск',
        value: state.searchQuery,
        oninput: (ev) => { state.searchQuery = ev.target.value; drawChips(); },
      }),
      chips),
    results);
}

const VIEW_FUNCS = { today: viewToday, tomorrow: viewTomorrow, week: viewWeek, changes: viewChanges, search: viewSearch };

/* ---------- отрисовка ---------- */
function updateHeader() {
  document.getElementById('school-name').textContent = state.meta.school_name;
  document.title = `Расписание — ${state.meta.school_name}`;
  document.getElementById('updated').textContent = formatUpdated(state.meta.last_updated, today());
  const cls = state.classId && currentClass();
  $classBtn.hidden = !cls;
  document.getElementById('class-label').textContent = cls ? cls.name : '';
  $tabs.hidden = !cls || state.picking;
  for (const btn of $tabs.querySelectorAll('button')) {
    btn.setAttribute('aria-selected', String(btn.dataset.view === state.view));
  }
}

async function render() {
  const token = ++renderToken;
  state.reloadSearch = null;
  updateHeader();
  if (!state.classId || state.picking) {
    clear($main).append(renderPicker());
    return;
  }
  try {
    const node = await VIEW_FUNCS[state.view]();
    if (token === renderToken) clear($main).append(node);
  } catch (err) {
    if (token !== renderToken) return;
    clear($main).append(h('div', { class: 'error-box' }, err.message, ' ',
      h('button', { class: 'btn small', type: 'button', onclick: render }, 'Повторить')));
  }
}

async function updateChangesDot() {
  if (!state.classId) return;
  try {
    const data = await Api.get('/api/changes', { class_id: state.classId });
    const soon = addDays(today(), 1);
    document.getElementById('changes-dot').hidden = !data.days.some((d) => d.date <= soon);
  } catch { /* не критично */ }
}

function selectClass(id) {
  state.classId = id;
  state.picking = false;
  Storage.set('classId', String(id));
  updateChangesDot();
  if (!VIEWS.includes(state.view)) state.view = 'today';
  render();
}

async function loadMeta() {
  state.meta = await Api.get('/api/meta');
  if (state.classId && !state.meta.classes.some((c) => c.id === state.classId)) state.classId = null;
}

async function refresh() {
  if (document.hidden || !state.meta) return;
  const before = `${state.meta.last_updated}|${state.meta.today}`;
  try {
    await loadMeta();
  } catch {
    return;
  }
  updateHeader();
  if (`${state.meta.last_updated}|${state.meta.today}` === before) return;
  updateChangesDot();
  if (state.view === 'search' && state.reloadSearch && !state.picking) state.reloadSearch();
  else render();
}

function viewFromHash() {
  const v = location.hash.slice(1);
  return VIEWS.includes(v) ? v : 'today';
}

async function init() {
  const saved = Number(Storage.get('classId'));
  state.classId = Number.isInteger(saved) && saved > 0 ? saved : null;
  state.view = viewFromHash();

  $tabs.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-view]');
    if (btn) location.hash = btn.dataset.view;
  });
  window.addEventListener('hashchange', () => { state.view = viewFromHash(); render(); });
  $classBtn.addEventListener('click', () => { state.picking = true; render(); });
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, REFRESH_MS);

  try {
    await loadMeta();
  } catch (err) {
    clear($main).append(h('div', { class: 'error-box' }, err.message, ' ',
      h('button', { class: 'btn small', type: 'button', onclick: () => location.reload() }, 'Повторить')));
    return;
  }
  updateChangesDot();
  render();
}

init();
