'use strict';

// ---------- ตำแหน่งโต๊ะบนแผนผัง (อิงตามแปลนร้าน) ----------
// แต่ละโต๊ะ: code ตรงกับฐานข้อมูล, surface = สี่เหลี่ยมพื้นโต๊ะ
const LAYOUT = {
  t5: { x:70,  y:140, w:64,  h:46 },
  t4: { x:70,  y:224, w:64,  h:46 },
  t2: { x:62,  y:318, w:50,  h:120 },
  t1: { x:58,  y:452, w:50,  h:40 },
  t3: { x:248, y:314, w:110, h:96 },
  t7: { x:418, y:168, w:52,  h:150 },
  t6: { x:476, y:104, w:60,  h:48 },
  bar1: { cx:624, cy:328, stool:true },
  bar2: { cx:624, cy:368, stool:true },
  bar3: { cx:624, cy:408, stool:true },
  bar4: { cx:624, cy:448, stool:true },
  bar5: { cx:624, cy:488, stool:true },
};

const TIME_SLOTS = ['18:00','19:00','20:00','21:00','22:00','23:00','00:00','01:00'];

const state = {
  tables: [], taken: new Set(),
  date: '', time: TIME_SLOTS[2], party: 2,
  selected: null,          // table object
};

const $ = (id) => document.getElementById(id);
const SVGNS = 'http://www.w3.org/2000/svg';

// ---------- utils ----------
function el(tag, attrs = {}, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
}
function toast(msg) {
  const t = $('toast');
  t.textContent = msg; t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => { t.hidden = true; }, 260);
  }, 2400);
}

// วางเก้าอี้รอบโต๊ะให้ครบตามจำนวนที่นั่ง
function seatPositions(rect, n) {
  const off = 15, r = { ...rect };
  const pts = [];
  if (r.h >= r.w) {
    // โต๊ะแนวตั้ง -> แบ่งซ้าย/ขวา
    const left = Math.ceil(n / 2), right = n - left;
    const place = (count, x) => {
      for (let i = 0; i < count; i++) {
        const y = r.y + (r.h * (i + 1)) / (count + 1);
        pts.push({ x, y });
      }
    };
    place(left, r.x - off);
    place(right, r.x + r.w + off);
  } else {
    // โต๊ะแนวนอน -> แบ่งบน/ล่าง
    const top = Math.ceil(n / 2), bot = n - top;
    const place = (count, y) => {
      for (let i = 0; i < count; i++) {
        const x = r.x + (r.w * (i + 1)) / (count + 1);
        pts.push({ x, y });
      }
    };
    place(top, r.y - off);
    place(bot, r.y + r.h + off);
  }
  return pts;
}

// ---------- วาดแผนผัง ----------
function drawFloor() {
  const layer = $('tables-layer');
  layer.innerHTML = '';

  state.tables.forEach((tb) => {
    const pos = LAYOUT[tb.code];
    if (!pos) return;

    const g = el('g', { class: 't-group', 'data-id': tb.id, tabindex: '0',
                        role: 'button', 'aria-label': `${tb.name} (${tb.capacity} ที่นั่ง)` });

    if (pos.stool) {
      // เก้าอี้บาร์ = วงกลม
      g.appendChild(el('circle', { class:'spotlight', cx:pos.cx, cy:pos.cy, r:34, fill:'url(#spot)' }));
      g.appendChild(el('circle', { class:'surface', cx:pos.cx, cy:pos.cy, r:15 }));
      g.appendChild(el('text', { class:'t-cap', x:pos.cx, y:pos.cy }, tb.name.replace('บาร์ ','B')));
    } else {
      const cx = pos.x + pos.w / 2, cy = pos.y + pos.h / 2;
      const R = Math.max(pos.w, pos.h) * 0.85;
      g.appendChild(el('rect', { class:'spotlight', x:cx-R, y:cy-R, width:R*2, height:R*2, fill:'url(#spot)' }));
      // เก้าอี้
      seatPositions(pos, tb.capacity).forEach((p) =>
        g.appendChild(el('circle', { class:'seat', cx:p.x, cy:p.y, r:7 })));
      // พื้นโต๊ะ
      g.appendChild(el('rect', { class:'surface', x:pos.x, y:pos.y, width:pos.w, height:pos.h, rx:9 }));
      // เลขโต๊ะ + จำนวนที่นั่ง
      g.appendChild(el('text', { class:'t-label', x:cx, y:cy-6 }, tb.name.replace('โต๊ะ ','')));
      g.appendChild(el('text', { class:'t-cap', x:cx, y:cy+13 }, tb.capacity + ' ที่'));
    }

    const activate = () => onPickTable(tb);
    g.addEventListener('click', activate);
    g.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
    });
    layer.appendChild(g);
  });
}

// อัปเดตสี/สถานะโต๊ะทุกตัว
function refreshFloorStates() {
  document.querySelectorAll('.t-group').forEach((g) => {
    const id = +g.dataset.id;
    const tb = state.tables.find((t) => t.id === id);
    g.classList.remove('taken', 'small', 'selected');
    if (state.taken.has(id)) g.classList.add('taken');
    // แสดงจาง ๆ ว่าที่นั่งอาจไม่พอ แต่ยังเลือกได้
    else if (tb.capacity < state.party) g.classList.add('tight');
    if (state.selected && state.selected.id === id) g.classList.add('selected');
  });
}

// ---------- เลือกโต๊ะ ----------
function onPickTable(tb) {
  if (state.taken.has(tb.id)) { toast(`${tb.name} ถูกจองไปแล้วในเวลานี้`); return; }
  // เลือกโต๊ะไหนก็ได้ แม้จำนวนคนจะมากกว่าจำนวนเก้าอี้
  if (tb.capacity < state.party) {
    toast(`${tb.name} มี ${tb.capacity} ที่นั่ง — จองได้ แต่ที่นั่งอาจไม่พอ`);
  }
  state.selected = tb;
  refreshFloorStates();
  renderSummary();
}

// ---------- แถบเวลา ----------
function renderTimeChips() {
  const box = $('time-chips');
  box.innerHTML = '';
  TIME_SLOTS.forEach((t) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.textContent = t;
    b.setAttribute('aria-pressed', String(t === state.time));
    b.addEventListener('click', () => {
      state.time = t;
      box.querySelectorAll('.chip').forEach((c) =>
        c.setAttribute('aria-pressed', String(c.textContent === t)));
      loadAvailability();
    });
    box.appendChild(b);
  });
}

// ---------- สรุป ----------
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('th-TH', { weekday:'short', day:'numeric', month:'short' });
}

function renderSummary() {
  const tv = $('pick-table-val');
  if (state.selected) {
    tv.textContent = `${state.selected.name} · ${state.selected.capacity} ที่นั่ง`;
    tv.classList.add('set'); tv.classList.remove('muted');
    $('mb-table').textContent = state.selected.name;
  } else {
    tv.textContent = 'ยังไม่ได้เลือก';
    tv.classList.remove('set'); tv.classList.add('muted');
    $('mb-table').textContent = 'ยังไม่ได้เลือกโต๊ะ';
  }
  $('pick-when').textContent = `${fmtDate(state.date)} · ${state.time}`;
  $('pick-party').textContent = `${state.party} คน`;
  validateForm();
}

function validateForm() {
  const ready = !!state.selected;
  const btns = [$('confirm-btn'), $('confirm-btn-mobile')];
  btns.forEach((b) => { b.disabled = !ready; });
  $('confirm-btn').textContent = ready ? 'ยืนยันการจอง' : 'เลือกโต๊ะก่อน';
}

// ---------- API ----------
async function api(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || 'เกิดข้อผิดพลาด');
  return data;
}

async function loadAvailability() {
  try {
    const { taken } = await api(`/api/availability?date=${state.date}&time=${encodeURIComponent(state.time)}`);
    state.taken = new Set(taken);
    // ถ้าโต๊ะที่เลือกไว้กลายเป็นเต็ม -> ยกเลิกการเลือก
    if (state.selected && state.taken.has(state.selected.id)) {
      toast(`${state.selected.name} เพิ่งถูกจองในเวลานี้ — เลือกใหม่ได้เลย`);
      state.selected = null;
    }
    refreshFloorStates();
    renderSummary();
  } catch (e) { toast(e.message); }
}

async function submit() {
  const name = $('name-input').value.trim();
  const phone = $('phone-input').value.trim();
  const instagram = $('ig-input').value.trim();
  const msg = $('form-msg');
  msg.classList.remove('ok');

  if (!state.selected) { msg.textContent = 'กรุณาเลือกโต๊ะ'; return; }
  if (!name) { msg.textContent = 'กรุณากรอกชื่อผู้จอง'; $('name-input').focus(); return; }
  if (phone.length < 8) { msg.textContent = 'กรุณากรอกเบอร์โทรให้ถูกต้อง'; $('phone-input').focus(); return; }
  if (!instagram) { msg.textContent = 'กรุณากรอกไอดีไอจี'; $('ig-input').focus(); return; }

  const payload = {
    table_id: state.selected.id,
    res_date: state.date,
    res_time: state.time,
    party_size: state.party,
    customer_name: name,
    phone,
    instagram,
    note: $('note-input').value.trim(),
  };

  const btns = [$('confirm-btn'), $('confirm-btn-mobile')];
  btns.forEach((b) => { b.disabled = true; });
  msg.textContent = 'กำลังจอง...';

  try {
    const res = await api('/api/reservations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    showSuccess(res.id);
  } catch (e) {
    msg.textContent = e.message;
    // อาจมีคนจองตัดหน้า -> รีเฟรชสถานะ
    loadAvailability();
  } finally {
    btns.forEach((b) => { b.disabled = false; });
  }
}

function showSuccess(id) {
  $('success-code').textContent = 'รหัสจอง #' + String(id).padStart(4, '0');
  $('success-detail').innerHTML = `
    <div><b>${state.selected.name}</b> · ${state.party} คน</div>
    <div>${fmtDate(state.date)} เวลา ${state.time} น.</div>
    <div>${$('name-input').value.trim()} · ${$('phone-input').value.trim()}</div>
    <div>IG: ${$('ig-input').value.trim()}</div>
  `;
  $('success-overlay').hidden = false;
}

function resetBooking() {
  state.selected = null;
  $('name-input').value = '';
  $('phone-input').value = '';
  $('ig-input').value = '';
  $('note-input').value = '';
  $('form-msg').textContent = '';
  $('success-overlay').hidden = true;
  loadAvailability();
  renderSummary();
}

// ---------- init ----------
function localISODate(d = new Date()) {
  // YYYY-MM-DD ตามเวลาท้องถิ่น (ไม่ใช่ UTC) เพื่อไม่ให้วันเพี้ยน
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d - off).toISOString().slice(0, 10);
}

async function init() {
  // วันที่เริ่มต้น = วันนี้ (เวลาท้องถิ่น)
  const iso = localISODate();
  state.date = iso;
  const di = $('date-input');
  di.value = iso; di.min = iso;
  di.addEventListener('change', () => {
    state.date = di.value || iso;
    loadAvailability();
  });

  // จำนวนคน
  $('party-stepper').querySelectorAll('.step-btn').forEach((b) => {
    b.addEventListener('click', () => {
      const next = Math.min(12, Math.max(1, state.party + (+b.dataset.party)));
      state.party = next;
      $('party-val').textContent = next;
      refreshFloorStates();
      renderSummary();
    });
  });

  renderTimeChips();
  $('confirm-btn').addEventListener('click', submit);
  $('confirm-btn-mobile').addEventListener('click', submit);
  $('again-btn').addEventListener('click', resetBooking);

  try {
    const { tables } = await api('/api/tables');
    state.tables = tables;
    drawFloor();
    renderSummary();
    await loadAvailability();
  } catch (e) {
    toast('โหลดข้อมูลไม่สำเร็จ: ' + e.message);
  }
}

document.addEventListener('DOMContentLoaded', init);
