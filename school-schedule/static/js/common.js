'use strict';

/* Создание DOM-элементов. Текст всегда вставляется как текст (не HTML), поэтому XSS невозможен. */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  const late = {};
  for (const [key, val] of Object.entries(attrs || {})) {
    if (val == null || val === false) continue;
    if (key === 'class') el.className = val;
    else if (key.startsWith('on') && typeof val === 'function') el.addEventListener(key.slice(2), val);
    else if (key === 'value' || key === 'checked' || key === 'selected') late[key] = val;
    else el.setAttribute(key, val === true ? '' : String(val));
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  Object.assign(el, late);
  return el;
}

function clear(el) {
  el.replaceChildren();
  return el;
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const Api = {
  csrf: null,
  onUnauthorized: null,

  async request(method, url, body) {
    const opts = { method, headers: {}, credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    if (method !== 'GET' && this.csrf) opts.headers['X-CSRF-Token'] = this.csrf;
    let res;
    try {
      res = await fetch(url, opts);
    } catch {
      throw new ApiError('Нет связи с сервером. Проверьте подключение к интернету.', 0);
    }
    let data = null;
    try { data = await res.json(); } catch { /* пустой ответ */ }
    if (!res.ok) {
      const message = (data && typeof data.detail === 'string') ? data.detail : `Ошибка сервера (${res.status})`;
      if (res.status === 401 && this.onUnauthorized && !url.endsWith('/login')) this.onUnauthorized(message);
      throw new ApiError(message, res.status);
    }
    return data;
  },
  get(url, params) {
    const qs = params ? new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null && v !== '')
    ).toString() : '';
    return this.request('GET', qs ? `${url}?${qs}` : url);
  },
  post(url, body) { return this.request('POST', url, body ?? {}); },
  put(url, body) { return this.request('PUT', url, body); },
  del(url, params) {
    const qs = params ? new URLSearchParams(params).toString() : '';
    return this.request('DELETE', qs ? `${url}?${qs}` : url);
  },
};

/* ---------- даты ---------- */
const WEEKDAY_NAMES = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'];
const WEEKDAY_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
  'сентября', 'октября', 'ноября', 'декабря'];

function parseDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function isoDate(date) {
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

function addDays(iso, n) {
  const d = parseDate(iso);
  d.setDate(d.getDate() + n);
  return isoDate(d);
}

function mondayOf(iso) {
  const d = parseDate(iso);
  const shift = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - shift);
  return isoDate(d);
}

function isoWeekday(iso) {
  return ((parseDate(iso).getDay() + 6) % 7) + 1;
}

function formatDayTitle(iso) {
  const d = parseDate(iso);
  return `${WEEKDAY_NAMES[d.getDay()]}, ${d.getDate()} ${MONTHS_GEN[d.getMonth()]}`;
}

function formatShort(iso) {
  const d = parseDate(iso);
  return `${WEEKDAY_SHORT[d.getDay()]} ${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/* "2026-11-09T14:32:05+03:00" → "в 14:32" или "08.11 в 14:32" (время школы, без пересчёта поясов). */
function formatUpdated(isoTs, todayIso) {
  if (!isoTs) return '';
  const day = isoTs.slice(0, 10);
  const time = isoTs.slice(11, 16);
  if (day === todayIso) return `обновлено в ${time}`;
  return `обновлено ${day.slice(8, 10)}.${day.slice(5, 7)} в ${time}`;
}

function formatTs(isoTs) {
  return `${isoTs.slice(8, 10)}.${isoTs.slice(5, 7)}.${isoTs.slice(0, 4)} ${isoTs.slice(11, 16)}`;
}

/* "Иванова Мария Петровна" → "Иванова М. П." */
function shortName(full) {
  if (!full) return '';
  const parts = full.trim().split(/\s+/);
  if (parts.length < 2) return full;
  return `${parts[0]} ${parts.slice(1).map((p) => `${p[0]}.`).join(' ')}`;
}

function classGrade(name) {
  const m = /^\s*(\d+)/.exec(name);
  return m ? Number(m[1]) : null;
}

/* ---------- уведомления ---------- */
let toastTimer = null;
function toast(message, isError = false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.classList.toggle('error', isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
}

const Storage = {
  get(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* приватный режим */ }
  },
};
