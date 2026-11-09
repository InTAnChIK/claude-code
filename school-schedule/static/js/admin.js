'use strict';

const TYPE_LABELS = {
  teacher: 'Замена учителя',
  subject: 'Другой предмет',
  room: 'Смена кабинета',
  cancel: 'Отмена урока',
  move: 'Перенос',
};
const ROLE_LABELS = { teacher: 'Учитель', admin: 'Администратор' };
const ACTION_LABELS = { create: 'добавлено', update: 'изменено', delete: 'удалено', login: 'вход' };
const DAY_SHORT = ['', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

const S = {
  user: null,
  meta: null,
  tab: 'changes',
  scheduleClass: null,
  scheduleDay: null,
  open: new Set(),
};

const $main = document.getElementById('main');
const $tabs = document.getElementById('tabs');
const $dialog = document.getElementById('dialog');

const isAdmin = () => S.user && S.user.role === 'admin';
const nameOf = (list, id) => (list.find((x) => x.id === id) || {}).name || '';
const opts = (list, fmt = (x) => x.name) => list.map((x) => ({ value: x.id, label: fmt(x) }));
const bellOptions = () => S.meta.bells.map((b) => ({ value: b.lesson_no, label: `${b.lesson_no}-й урок (${b.start}–${b.end})` }));

function errorBox(message) {
  return h('div', { class: 'error-box', role: 'alert' }, message);
}

/* ---------- универсальный диалог с формой ---------- */
function formDialog({ title, intro, fields = [], submitLabel = 'Сохранить', submitClass = 'primary', extraButtons = [], onSubmit }) {
  return new Promise((resolve) => {
    const controls = {};
    const err = h('div', { class: 'error-box', role: 'alert', hidden: true });
    let infoRun = 0;

    const read = () => {
      const values = {};
      for (const [name, c] of Object.entries(controls)) {
        const f = c.field;
        if (f.type === 'info') continue;
        if (f.type === 'checkbox') values[name] = c.input.checked;
        else {
          const raw = c.input.value.trim();
          values[name] = raw === '' ? null : (f.number ? Number(raw) : raw);
        }
      }
      return values;
    };

    const isVisible = (c, values) => !c.field.show || c.field.show(values);
    const isRequired = (c, values) => (typeof c.field.required === 'function' ? c.field.required(values) : !!c.field.required);

    const update = () => {
      const values = read();
      for (const c of Object.values(controls)) {
        c.wrap.hidden = !isVisible(c, values);
        if (c.star) c.star.hidden = !isRequired(c, values);
      }
      const run = ++infoRun;
      for (const c of Object.values(controls)) {
        if (c.field.type !== 'info') continue;
        Promise.resolve(c.field.text(values)).then((text) => {
          if (run !== infoRun) return;
          c.input.textContent = text || '';
          c.wrap.hidden = !text;
        }).catch(() => { c.wrap.hidden = true; });
      }
    };

    const form = h('form', { novalidate: true }, h('h2', null, title), intro ? h('p', { class: 'muted small' }, intro) : null);

    for (const f of fields) {
      let input;
      const attrs = { name: f.name, id: `f-${f.name}`, ...(f.attrs || {}) };
      if (f.type === 'select') {
        input = h('select', attrs,
          h('option', { value: '' }, f.placeholder || '— не выбрано —'),
          f.options.map((o) => h('option', { value: o.value }, o.label)));
        input.value = f.value ?? '';
      } else if (f.type === 'textarea') {
        input = h('textarea', { ...attrs, value: f.value ?? '' });
      } else if (f.type === 'checkbox') {
        input = h('input', { ...attrs, type: 'checkbox', checked: !!f.value });
      } else if (f.type === 'info') {
        input = h('div', { class: 'info-box' });
      } else {
        input = h('input', { ...attrs, type: f.type || 'text', value: f.value ?? '' });
      }

      let wrap;
      let star = null;
      if (f.type === 'checkbox') {
        wrap = h('label', { class: 'check' }, input, f.label);
      } else if (f.type === 'info') {
        wrap = h('div', null, input);
      } else {
        star = h('span', { class: 'req', 'aria-hidden': 'true' }, ' *');
        wrap = h('label', { class: 'field' },
          h('span', null, f.label, star), input,
          f.hint ? h('small', { class: 'muted' }, f.hint) : null);
      }
      controls[f.name] = { field: f, input, wrap, star };
      form.append(wrap);
    }

    const submitBtn = h('button', { type: 'submit', class: `btn ${submitClass}` }, submitLabel);
    const cancelBtn = h('button', { type: 'button', class: 'btn ghost', onclick: () => $dialog.close() }, 'Отмена');
    const extra = extraButtons.map((b) => h('button', {
      type: 'button',
      class: `btn ${b.className || ''}`,
      onclick: async () => {
        try {
          const result = await b.onClick();
          if (result !== false) { resolve(result ?? true); $dialog.close(); }
        } catch (e) { err.textContent = e.message; err.hidden = false; }
      },
    }, b.label));
    form.append(err, h('div', { class: 'actions' }, extra, h('span', { class: 'spacer' }), cancelBtn, submitBtn));

    form.addEventListener('input', update);
    form.addEventListener('change', update);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      err.hidden = true;
      const values = read();
      for (const c of Object.values(controls)) {
        if (!isVisible(c, values) || !isRequired(c, values)) continue;
        const v = values[c.field.name];
        if (v == null || v === '') {
          err.textContent = `Заполните поле «${c.field.label}»`;
          err.hidden = false;
          c.input.focus();
          return;
        }
      }
      submitBtn.disabled = true;
      try {
        const result = await onSubmit(values);
        resolve(result ?? true);
        $dialog.close();
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
      } finally {
        submitBtn.disabled = false;
      }
    });

    $dialog.addEventListener('close', () => resolve(null), { once: true });
    clear($dialog).append(form);
    update();
    $dialog.showModal();
    const first = form.querySelector('input:not([type=checkbox]), select, textarea');
    if (first && !first.value) first.focus();
  });
}

/* ---------- вход ---------- */
function showLogin(message) {
  S.user = null;
  Api.csrf = null;
  $tabs.hidden = true;
  document.getElementById('top-actions').hidden = true;
  document.getElementById('who').textContent = '';
  if ($dialog.open) $dialog.close();

  const err = h('div', { class: 'error-box', role: 'alert', hidden: !message }, message || '');
  const username = h('input', { type: 'text', name: 'username', autocomplete: 'username', maxlength: 64, required: true, autocapitalize: 'none', spellcheck: 'false' });
  const password = h('input', { type: 'password', name: 'password', autocomplete: 'current-password', maxlength: 200, required: true });
  const btn = h('button', { type: 'submit', class: 'btn primary block' }, 'Войти');

  const form = h('form', { class: 'card login-card stack', novalidate: true },
    h('h1', null, 'Вход для учителей'),
    h('p', { class: 'muted small' }, 'Ученикам и родителям вход не нужен — расписание открыто на главной странице.'),
    h('label', { class: 'field' }, h('span', null, 'Логин'), username),
    h('label', { class: 'field' }, h('span', null, 'Пароль'), password),
    err, btn);

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    if (!username.value.trim() || !password.value) {
      err.textContent = 'Введите логин и пароль';
      err.hidden = false;
      return;
    }
    btn.disabled = true;
    try {
      const res = await Api.post('/api/auth/login', { username: username.value.trim(), password: password.value });
      S.user = res.user;
      Api.csrf = res.csrf_token;
      await startPanel();
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
      password.value = '';
      password.focus();
    } finally {
      btn.disabled = false;
    }
  });
  clear($main).append(form);
  username.focus();
}

/* ---------- панель ---------- */
const TABS = [
  { id: 'changes', label: 'Замены', render: renderChanges },
  { id: 'schedule', label: 'Расписание', render: renderSchedule, admin: true },
  { id: 'settings', label: 'Настройки', render: renderSettingsTab, admin: true },
];
const visibleTabs = () => TABS.filter((t) => !t.admin || isAdmin());

async function reloadMeta() {
  S.meta = await Api.get('/api/meta');
  document.getElementById('school-name').textContent = S.meta.school_name;
}

async function startPanel() {
  await reloadMeta();
  document.getElementById('top-actions').hidden = false;
  document.getElementById('who').textContent = shortName(S.user.full_name);
  clear($tabs).append(...visibleTabs().map((t) => h('button', { type: 'button', role: 'tab', 'data-tab': t.id }, t.label)));
  $tabs.hidden = visibleTabs().length < 2;
  const fromHash = location.hash.slice(1);
  S.tab = visibleTabs().some((t) => t.id === fromHash) ? fromHash : 'changes';
  render();
}

async function render() {
  for (const b of $tabs.querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === S.tab));
  const tab = visibleTabs().find((t) => t.id === S.tab) || TABS[0];
  try {
    const node = await tab.render();
    clear($main).append(node);
  } catch (e) {
    if (e.status === 401) return;
    clear($main).append(errorBox(e.message), h('p', null, h('button', { type: 'button', class: 'btn', onclick: render }, 'Повторить')));
  }
}

/* ---------- изменения ---------- */
function describeChange(c) {
  const parts = [];
  if (c.new_subject) parts.push(c.new_subject);
  if (c.new_teacher) parts.push(shortName(c.new_teacher));
  if (c.new_room) parts.push(`каб. ${c.new_room}`);
  if (c.type === 'move') parts.push(`на ${formatShort(c.move_to_date)}, ${c.move_to_lesson}-й урок`);
  return parts.join(' · ');
}

async function lessonInfo(values, editingId) {
  if (!values.date || !values.class_id || !values.lesson_no) return null;
  const data = await Api.get('/api/schedule', { class_id: values.class_id, start: values.date, days: 1 });
  const entries = data.days[0].lessons.filter((e) => e.lesson_no === values.lesson_no);
  const own = entries.find((e) => e.status !== 'move_in');
  const base = own ? (own.orig || own) : null;
  let text = base && base.subject
    ? `По расписанию: ${[base.subject, shortName(base.teacher), base.room && `каб. ${base.room}`].filter(Boolean).join(' · ')}`
    : 'По расписанию урока нет — можно добавить урок через тип «Другой предмет».';
  if (own && own.change_id && own.change_id !== editingId) {
    text += '. Внимание: на этот урок уже есть изменение — отредактируйте его в списке.';
  }
  return text;
}

async function changeDialog(change) {
  const { meta } = S;
  const editing = !!change;
  const c = change || { date: S.meta.today, type: 'teacher' };
  const is = (...types) => (v) => types.includes(v.type);
  return formDialog({
    title: editing ? 'Изменить замену' : 'Новая замена',
    fields: [
      { name: 'date', label: 'Дата', type: 'date', required: true, value: c.date, attrs: { min: meta.today } },
      { name: 'class_id', label: 'Класс', type: 'select', number: true, required: true, value: c.class_id, options: opts(meta.classes) },
      { name: 'lesson_no', label: 'Урок', type: 'select', number: true, required: true, value: c.lesson_no, options: bellOptions() },
      { name: 'info', type: 'info', text: (v) => lessonInfo(v, c.id) },
      { name: 'type', label: 'Что случилось', type: 'select', required: true, value: c.type, placeholder: '— выберите —',
        options: Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label })) },
      { name: 'new_subject_id', label: 'Какой предмет будет', type: 'select', number: true, value: c.new_subject_id, options: opts(meta.subjects),
        show: is('subject'), required: true },
      { name: 'new_teacher_id', label: 'Кто ведёт', type: 'select', number: true, value: c.new_teacher_id, options: opts(meta.teachers),
        show: is('teacher', 'subject'), required: is('teacher') },
      { name: 'new_room_id', label: 'В каком кабинете', type: 'select', number: true, value: c.new_room_id, options: opts(meta.rooms),
        show: is('room'), required: true },
      { name: 'move_to_date', label: 'На какой день', type: 'date', value: c.move_to_date || c.date, attrs: { min: meta.today },
        show: is('move'), required: true },
      { name: 'move_to_lesson', label: 'На какой урок', type: 'select', number: true, value: c.move_to_lesson, options: bellOptions(),
        show: is('move'), required: true },
      { name: 'comment', label: 'Комментарий (необязательно)', type: 'textarea', value: c.comment, attrs: { maxlength: 500 } },
    ],
    onSubmit: async (v) => {
      if (v.date < meta.today) throw new Error('Нельзя вносить изменения на прошедшие даты');
      const payload = {
        date: v.date,
        class_id: v.class_id,
        lesson_no: v.lesson_no,
        type: v.type,
        new_subject_id: is('subject')(v) ? v.new_subject_id : null,
        new_teacher_id: is('teacher', 'subject')(v) ? v.new_teacher_id : null,
        new_room_id: is('room')(v) ? v.new_room_id : null,
        move_to_date: v.type === 'move' ? v.move_to_date : null,
        move_to_lesson: v.type === 'move' ? v.move_to_lesson : null,
        comment: v.comment || '',
      };
      if (editing) await Api.put(`/api/staff/changes/${c.id}`, payload);
      else await Api.post('/api/staff/changes', payload);
      toast('Сохранено — изменение уже видно на сайте');
    },
  });
}

async function renderChanges() {
  const data = await Api.get('/api/staff/changes');
  const addBtn = h('button', { type: 'button', class: 'btn primary block', onclick: async () => { if (await changeDialog()) render(); } }, '+ Добавить замену');

  const byDate = new Map();
  for (const item of data.items) {
    if (!byDate.has(item.date)) byDate.set(item.date, []);
    byDate.get(item.date).push(item);
  }

  const list = [];
  for (const [date, items] of byDate) {
    list.push(h('h2', { class: 'day-title' }, date === S.meta.today ? 'Сегодня' : formatDayTitle(date)));
    list.push(h('ul', { class: 'list' }, items.map((c) => h('li', { class: `item change-item st-${c.type}` },
      h('div', { class: 'grow' },
        h('div', { class: 'title' }, `${c.class_name}, ${c.lesson_no}-й урок`),
        h('div', { class: `sub change-note st-${c.type}` }, c.type_label, describeChange(c) ? ` → ${describeChange(c)}` : ''),
        c.comment ? h('div', { class: 'sub' }, c.comment) : null),
      c.can_edit ? h('div', { class: 'row' },
        h('button', { type: 'button', class: 'btn small', onclick: async () => { if (await changeDialog(c)) render(); } }, 'Изменить'),
        h('button', {
          type: 'button', class: 'btn small danger',
          onclick: async () => {
            if (!confirm(`Удалить замену: ${c.class_name}, ${formatShort(c.date)}, ${c.lesson_no}-й урок?`)) return;
            try {
              await Api.del(`/api/staff/changes/${c.id}`);
              toast('Удалено');
              render();
            } catch (e) { toast(e.message, true); }
          },
        }, 'Удалить')) : null))));
  }

  return h('div', { class: 'stack' },
    addBtn,
    h('div', null, list.length ? list : h('div', { class: 'empty' }, 'Замен на ближайшие дни нет')),
    isAdmin() ? null : collapsible('audit', 'История изменений', auditList));
}

/* ---------- сворачиваемый блок ---------- */
function collapsible(id, title, build) {
  const body = h('div', { class: 'fold-body' });
  const details = h('details', { class: 'card fold', open: S.open.has(id) }, h('summary', null, title), body);
  let loaded = false;
  const load = async () => {
    if (loaded) return;
    loaded = true;
    clear(body).append(h('p', { class: 'muted small' }, 'Загрузка…'));
    try { clear(body).append(await build()); } catch (e) { clear(body).append(errorBox(e.message)); loaded = false; }
  };
  details.addEventListener('toggle', () => {
    if (details.open) { S.open.add(id); load(); } else S.open.delete(id);
  });
  if (S.open.has(id)) load();
  return details;
}

/* ---------- журнал ---------- */
async function auditList() {
  const ul = h('ul', { class: 'list' });
  const more = h('button', { type: 'button', class: 'btn', hidden: true }, 'Показать ещё');
  let offset = 0;
  const loadMore = async () => {
    const data = await Api.get('/api/staff/audit', { limit: 30, offset });
    offset += data.items.length;
    ul.append(...data.items.map((e) => h('li', { class: 'item' },
      h('div', { class: 'grow' },
        h('div', null, e.summary),
        h('div', { class: 'sub' }, `${formatTs(e.ts)} · ${e.username} · ${ACTION_LABELS[e.action] || e.action}`)))));
    more.hidden = !data.has_more;
  };
  more.addEventListener('click', () => loadMore().catch((e) => toast(e.message, true)));
  await loadMore();
  return offset ? h('div', { class: 'stack' }, ul, more) : h('div', { class: 'empty' }, 'Пока пусто');
}

/* ---------- постоянное расписание ---------- */
async function renderSchedule() {
  const { meta } = S;
  if (!meta.classes.length) return h('div', { class: 'empty' }, 'Сначала добавьте классы в разделе «Справочники».');
  if (!meta.bells.length) return h('div', { class: 'empty' }, 'Сначала задайте расписание звонков в разделе «Звонки и школа».');
  if (!meta.classes.some((c) => c.id === S.scheduleClass)) S.scheduleClass = meta.classes[0].id;
  if (!meta.school_days.includes(S.scheduleDay)) S.scheduleDay = meta.school_days[0];

  const data = await Api.get('/api/admin/schedule', { class_id: S.scheduleClass });
  const cells = new Map(data.cells.map((c) => [`${c.weekday}-${c.lesson_no}`, c]));

  const editCell = async (lessonNo, cell) => {
    const className = nameOf(meta.classes, S.scheduleClass);
    const saved = await formDialog({
      title: `${className}, ${WEEKDAY_NAMES[S.scheduleDay % 7].toLowerCase()}, ${lessonNo}-й урок`,
      intro: 'Постоянное расписание. Разовые изменения вносите во вкладке «Изменения».',
      fields: [
        { name: 'subject_id', label: 'Предмет', type: 'select', number: true, required: true, value: cell?.subject_id, options: opts(meta.subjects) },
        { name: 'teacher_id', label: 'Учитель', type: 'select', number: true, value: cell?.teacher_id, options: opts(meta.teachers) },
        { name: 'room_id', label: 'Кабинет', type: 'select', number: true, value: cell?.room_id, options: opts(meta.rooms) },
      ],
      extraButtons: cell ? [{
        label: 'Убрать урок',
        className: 'danger',
        onClick: async () => {
          if (!confirm('Убрать этот урок из постоянного расписания?')) return false;
          await Api.del('/api/admin/schedule', { class_id: S.scheduleClass, weekday: S.scheduleDay, lesson_no: lessonNo });
          return true;
        },
      }] : [],
      onSubmit: (v) => Api.put('/api/admin/schedule', {
        class_id: S.scheduleClass, weekday: S.scheduleDay, lesson_no: lessonNo,
        subject_id: v.subject_id, teacher_id: v.teacher_id, room_id: v.room_id,
      }),
    });
    if (saved) { toast('Расписание сохранено'); render(); }
  };

  return h('div', null,
    h('div', { class: 'toolbar' },
      h('select', { 'aria-label': 'Класс', value: String(S.scheduleClass), onchange: (e) => { S.scheduleClass = Number(e.target.value); render(); } },
        meta.classes.map((c) => h('option', { value: String(c.id) }, c.name)))),
    h('div', { class: 'segmented', role: 'group', 'aria-label': 'День недели' },
      meta.school_days.map((d) => h('button', {
        type: 'button', 'aria-pressed': String(d === S.scheduleDay), onclick: () => { S.scheduleDay = d; render(); },
      }, DAY_SHORT[d]))),
    h('h2', { class: 'section-title' }, `${nameOf(meta.classes, S.scheduleClass)} — ${WEEKDAY_NAMES[S.scheduleDay % 7]}`),
    h('ul', { class: 'list' }, meta.bells.map((b) => {
      const cell = cells.get(`${S.scheduleDay}-${b.lesson_no}`);
      const details = cell && [shortName(nameOf(meta.teachers, cell.teacher_id)), cell.room_id && `каб. ${nameOf(meta.rooms, cell.room_id)}`].filter(Boolean).join(' · ');
      return h('li', null, h('button', { type: 'button', class: 'item row-btn', onclick: () => editCell(b.lesson_no, cell) },
        h('span', { class: 'num-badge' }, h('b', null, b.lesson_no)),
        h('span', { class: 'grow' },
          cell
            ? h('span', { class: 'title' }, nameOf(meta.subjects, cell.subject_id))
            : h('span', { class: 'cell-empty' }, '+ добавить урок'),
          h('span', { class: 'sub' }, [b.start, details].filter(Boolean).join(' · ')))));
    })));
}

/* ---------- справочники ---------- */
const DICTS = [
  { kind: 'classes', title: 'Классы', placeholder: 'Например, 5А', deleteWarning: 'Вместе с классом удалятся его постоянное расписание и замены.' },
  { kind: 'teachers', title: 'Учителя', placeholder: 'Фамилия Имя Отчество' },
  { kind: 'subjects', title: 'Предметы', placeholder: 'Например, Математика' },
  { kind: 'rooms', title: 'Кабинеты', placeholder: 'Например, 204 или Спортзал' },
];

function dictSection(d) {
  const input = h('input', { type: 'text', placeholder: d.placeholder, maxlength: 100, 'aria-label': `Добавить: ${d.title}` });
  const err = h('div', { class: 'error-box', role: 'alert', hidden: true });
  const form = h('form', { class: 'row', novalidate: true },
    h('div', { class: 'spacer' }, input),
    h('button', { type: 'submit', class: 'btn primary' }, 'Добавить'));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    if (!input.value.trim()) { err.textContent = 'Введите название'; err.hidden = false; return; }
    try {
      await Api.post(`/api/admin/dict/${d.kind}`, { name: input.value });
      await reloadMeta();
      toast('Добавлено');
      render();
    } catch (e) { err.textContent = e.message; err.hidden = false; }
  });
  const items = S.meta[d.kind];
  return h('div', { class: 'stack' },
    form, err,
    h('ul', { class: 'list' }, items.map((item) => h('li', { class: 'item' },
      h('div', { class: 'grow title' }, item.name),
      h('button', {
        type: 'button', class: 'btn small',
        onclick: async () => {
          const ok = await formDialog({
            title: 'Переименовать',
            fields: [{ name: 'name', label: 'Название', required: true, value: item.name, attrs: { maxlength: 100 } }],
            onSubmit: (v) => Api.put(`/api/admin/dict/${d.kind}/${item.id}`, { name: v.name }),
          });
          if (ok) { await reloadMeta(); toast('Сохранено'); render(); }
        },
      }, 'Переименовать'),
      h('button', {
        type: 'button', class: 'btn small danger',
        onclick: async () => {
          if (!confirm(`Удалить «${item.name}»?${d.deleteWarning ? `\n${d.deleteWarning}` : ''}`)) return;
          try {
            await Api.del(`/api/admin/dict/${d.kind}/${item.id}`);
            await reloadMeta();
            toast('Удалено');
            render();
          } catch (e) { toast(e.message, true); }
        },
      }, 'Удалить')))));
}

/* ---------- вкладка «Настройки» ---------- */
function renderSettingsTab() {
  return h('div', { class: 'stack' },
    collapsible('school', 'Школа и звонки', async () => renderSettings()),
    DICTS.map((d) => collapsible(d.kind, `${d.title} (${S.meta[d.kind].length})`, async () => dictSection(d))),
    collapsible('users', 'Пользователи', renderUsers),
    collapsible('audit', 'Журнал действий', auditList));
}

/* ---------- звонки и настройки школы ---------- */
function renderSettings() {
  const { meta } = S;

  const nameInput = h('input', { type: 'text', value: meta.school_name, maxlength: 150 });
  const dayChecks = [1, 2, 3, 4, 5, 6, 7].map((d) => h('input', { type: 'checkbox', value: String(d), checked: meta.school_days.includes(d) }));
  const settingsErr = h('div', { class: 'error-box', role: 'alert', hidden: true });
  const settingsForm = h('form', { class: 'stack', novalidate: true },
    h('h2', { class: 'section-title' }, 'Школа'),
    h('label', { class: 'field' }, h('span', null, 'Название школы'), nameInput),
    h('div', { class: 'field' }, h('span', null, 'Учебные дни'),
      h('div', { class: 'checks' }, dayChecks.map((c, i) => h('label', { class: 'check' }, c, DAY_SHORT[i + 1])))),
    settingsErr,
    h('button', { type: 'submit', class: 'btn primary' }, 'Сохранить'));
  settingsForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    settingsErr.hidden = true;
    const days = dayChecks.filter((c) => c.checked).map((c) => Number(c.value));
    try {
      if (!nameInput.value.trim()) throw new Error('Укажите название школы');
      if (!days.length) throw new Error('Отметьте хотя бы один учебный день');
      await Api.put('/api/admin/settings', { school_name: nameInput.value, school_days: days });
      await reloadMeta();
      toast('Настройки сохранены');
    } catch (e) { settingsErr.textContent = e.message; settingsErr.hidden = false; }
  });

  const rows = h('div', { class: 'stack' });
  const addRow = (start = '', end = '') => {
    const n = rows.children.length + 1;
    rows.append(h('div', { class: 'bell-row' },
      h('b', null, `${n}.`),
      h('input', { type: 'time', value: start, 'aria-label': `Начало ${n}-го урока`, required: true }),
      h('input', { type: 'time', value: end, 'aria-label': `Конец ${n}-го урока`, required: true })));
  };
  meta.bells.forEach((b) => addRow(b.start, b.end));
  const bellsErr = h('div', { class: 'error-box', role: 'alert', hidden: true });
  const bellsForm = h('form', { class: 'stack', novalidate: true },
    h('h2', { class: 'section-title' }, 'Расписание звонков'),
    rows,
    h('div', { class: 'row' },
      h('button', {
        type: 'button', class: 'btn small',
        onclick: () => {
          if (rows.children.length >= 12) { toast('Не больше 12 уроков', true); return; }
          addRow();
        },
      }, '+ Добавить урок'),
      h('button', {
        type: 'button', class: 'btn small danger',
        onclick: () => { if (rows.children.length > 1) rows.lastElementChild.remove(); },
      }, 'Убрать последний')),
    bellsErr,
    h('button', { type: 'submit', class: 'btn primary' }, 'Сохранить звонки'));
  bellsForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    bellsErr.hidden = true;
    const bells = [...rows.children].map((row, i) => {
      const [start, end] = row.querySelectorAll('input');
      return { lesson_no: i + 1, start: start.value, end: end.value };
    });
    try {
      const empty = bells.find((b) => !b.start || !b.end);
      if (empty) throw new Error(`Укажите время начала и конца ${empty.lesson_no}-го урока`);
      if (!bells.length) throw new Error('Добавьте хотя бы один урок');
      await Api.put('/api/admin/bells', { bells });
      await reloadMeta();
      toast('Звонки сохранены');
    } catch (e) { bellsErr.textContent = e.message; bellsErr.hidden = false; }
  });

  return h('div', { class: 'stack' }, settingsForm, bellsForm);
}

/* ---------- пользователи ---------- */
async function renderUsers() {
  const data = await Api.get('/api/admin/users');
  const roleOptions = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }));

  const addUser = async () => {
    const ok = await formDialog({
      title: 'Новый пользователь',
      fields: [
        { name: 'full_name', label: 'ФИО', required: true, attrs: { maxlength: 100 } },
        { name: 'username', label: 'Логин', required: true, attrs: { maxlength: 32, autocapitalize: 'none', autocomplete: 'off' },
          hint: 'Латинские буквы, цифры, точка, дефис, подчёркивание; 3–32 символа.' },
        { name: 'role', label: 'Роль', type: 'select', required: true, value: 'teacher', options: roleOptions },
        { name: 'password', label: 'Пароль', type: 'password', required: true, attrs: { autocomplete: 'new-password', maxlength: 200 },
          hint: 'Минимум 8 символов. Сообщите пароль пользователю лично.' },
      ],
      onSubmit: (v) => Api.post('/api/admin/users', v),
    });
    if (ok) { toast('Пользователь создан'); render(); }
  };

  const editUser = async (u) => {
    const ok = await formDialog({
      title: `Пользователь ${u.username}`,
      fields: [
        { name: 'full_name', label: 'ФИО', required: true, value: u.full_name, attrs: { maxlength: 100 } },
        { name: 'role', label: 'Роль', type: 'select', required: true, value: u.role, options: roleOptions },
        { name: 'is_active', label: 'Может входить в систему', type: 'checkbox', value: !!u.is_active },
        { name: 'password', label: 'Новый пароль', type: 'password', attrs: { autocomplete: 'new-password', maxlength: 200 },
          hint: 'Оставьте пустым, чтобы не менять. Минимум 8 символов.' },
      ],
      onSubmit: (v) => Api.put(`/api/admin/users/${u.id}`, { full_name: v.full_name, role: v.role, is_active: v.is_active, password: v.password }),
    });
    if (ok) { toast('Сохранено'); render(); }
  };

  return h('div', null,
    h('div', { class: 'toolbar' }, h('button', { type: 'button', class: 'btn primary', onclick: addUser }, '+ Добавить пользователя')),
    h('ul', { class: 'list' }, data.items.map((u) => h('li', { class: 'item' },
      h('div', { class: 'grow' },
        h('div', { class: 'title' }, u.full_name, u.id === S.user.id ? ' (это вы)' : ''),
        h('div', { class: 'sub' }, [u.username, ROLE_LABELS[u.role], u.is_active ? null : 'заблокирован'].filter(Boolean).join(' · '))),
      h('button', { type: 'button', class: 'btn small', onclick: () => editUser(u) }, 'Изменить'),
      u.id !== S.user.id ? h('button', {
        type: 'button', class: 'btn small danger',
        onclick: async () => {
          if (!confirm(`Удалить пользователя ${u.full_name} (${u.username})? Его записи в журнале сохранятся.`)) return;
          try {
            await Api.del(`/api/admin/users/${u.id}`);
            toast('Пользователь удалён');
            render();
          } catch (e) { toast(e.message, true); }
        },
      }, 'Удалить') : null))));
}

/* ---------- смена пароля и выход ---------- */
async function changePassword() {
  const ok = await formDialog({
    title: 'Смена пароля',
    fields: [
      { name: 'old_password', label: 'Текущий пароль', type: 'password', required: true, attrs: { autocomplete: 'current-password' } },
      { name: 'new_password', label: 'Новый пароль', type: 'password', required: true, attrs: { autocomplete: 'new-password', maxlength: 200 }, hint: 'Минимум 8 символов.' },
      { name: 'new_password2', label: 'Новый пароль ещё раз', type: 'password', required: true, attrs: { autocomplete: 'new-password' } },
    ],
    onSubmit: async (v) => {
      if (v.new_password.length < 8) throw new Error('Новый пароль должен быть не короче 8 символов');
      if (v.new_password !== v.new_password2) throw new Error('Новые пароли не совпадают');
      const res = await Api.post('/api/auth/password', { old_password: v.old_password, new_password: v.new_password });
      Api.csrf = res.csrf_token;
    },
  });
  if (ok) toast('Пароль изменён');
}

async function logout() {
  try { await Api.post('/api/auth/logout'); } catch { /* сессия могла уже истечь */ }
  location.hash = '';
  showLogin();
}

/* ---------- запуск ---------- */
async function init() {
  Api.onUnauthorized = () => { if (S.user) showLogin('Сессия истекла — войдите снова.'); };
  $tabs.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-tab]');
    if (!btn) return;
    S.tab = btn.dataset.tab;
    location.hash = S.tab;
    render();
  });
  document.getElementById('btn-password').addEventListener('click', changePassword);
  document.getElementById('btn-logout').addEventListener('click', logout);

  try {
    const me = await Api.get('/api/auth/me');
    if (me.user) {
      S.user = me.user;
      Api.csrf = me.csrf_token;
      await startPanel();
      return;
    }
  } catch (e) {
    clear($main).append(errorBox(e.message));
    return;
  }
  showLogin();
}

init();
