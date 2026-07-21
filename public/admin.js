'use strict';
const $ = (id) => document.getElementById(id);
const baht = (n) => '฿' + n.toLocaleString('th-TH');

function toast(msg){
  const t=$('toast'); t.textContent=msg; t.hidden=false;
  requestAnimationFrame(()=>t.classList.add('show'));
  clearTimeout(toast._t);
  toast._t=setTimeout(()=>{t.classList.remove('show');setTimeout(()=>t.hidden=true,260)},2400);
}

async function load(){
  const date = $('admin-date').value;
  const grid = $('res-grid');
  try{
    const r = await fetch('/api/reservations' + (date ? `?date=${date}` : ''));
    const { reservations } = await r.json();
    render(reservations);
  }catch(e){
    grid.innerHTML = `<div class="empty">โหลดข้อมูลไม่สำเร็จ</div>`;
  }
}

const STATUS_LABEL = { confirmed:'ยืนยันแล้ว', completed:'เช็คบิลแล้ว', cancelled:'ยกเลิก' };

function orderItemRow(it, editable){
  const lineTotal = it.qty * it.unit_price;
  if(!editable){
    return `
      <div class="order-item">
        <span class="oi-name">${it.name}</span>
        <span class="oi-price">×${it.qty}</span>
        <span class="oi-line-total">${baht(lineTotal)}</span>
      </div>`;
  }
  return `
    <div class="order-item" data-item-id="${it.id}">
      <span class="oi-name">${it.name}</span>
      <span class="oi-price">×${baht(it.unit_price)}</span>
      <div class="oi-stepper">
        <button type="button" class="oi-step" data-item-id="${it.id}" data-d="-1" data-qty="${it.qty}">–</button>
        <span class="oi-qty">${it.qty}</span>
        <button type="button" class="oi-step" data-item-id="${it.id}" data-d="1" data-qty="${it.qty}">+</button>
      </div>
      <span class="oi-line-total">${baht(lineTotal)}</span>
      <button type="button" class="oi-remove" data-item-id="${it.id}">×</button>
    </div>`;
}

function orderBox(r){
  const editable = r.status === 'confirmed';
  const items = r.items || [];
  if(!editable && items.length === 0) return '';
  return `
    <div class="order-box">
      ${items.map(it => orderItemRow(it, editable)).join('')}
      ${editable ? `
        <div class="order-add">
          <input type="text" class="oi-input-name" placeholder="ชื่อรายการ">
          <input type="number" class="oi-input-qty" placeholder="จน." min="1" value="1">
          <input type="number" class="oi-input-price" placeholder="ราคา" min="0">
          <button type="button" class="order-add-btn" data-res-id="${r.id}">+ เพิ่ม</button>
        </div>` : ''}
      <div class="order-total"><span>ยอดสั่ง</span><b>${baht(r.order_total || 0)}</b></div>
    </div>`;
}

function render(list){
  const grid = $('res-grid');
  const active = list.filter(r => r.status === 'confirmed');
  const completed = list.filter(r => r.status === 'completed');

  $('stat-count').textContent = active.length;
  $('stat-guests').textContent = active.reduce((a,r)=>a+r.party_size,0);
  $('stat-total').textContent = baht(completed.reduce((a,r)=>a+(r.paid_amount||0),0));

  if(!list.length){
    grid.innerHTML = `<div class="empty">ยังไม่มีการจองในวันนี้</div>`;
    return;
  }

  grid.innerHTML = list.map(r => `
    <div class="res-card ${r.status}">
      <div class="res-top">
        <span class="res-table">${r.table_name}</span>
        <span class="res-time">${r.res_time} น.</span>
      </div>
      <div class="res-line"><b>${r.customer_name}</b> · ${r.party_size} คน</div>
      <div class="res-line">${r.phone}</div>
      <div class="res-line">IG: ${r.instagram || '—'}</div>
      <div class="res-line">${r.res_date}
        <span class="badge ${r.status}">${STATUS_LABEL[r.status] || r.status}</span>
      </div>
      ${r.note ? `<div class="res-line">📝 ${r.note}</div>` : ''}
      ${r.status==='completed' ? `<div class="res-line">ยอดจ่าย <span class="paid-amount">${baht(r.paid_amount||0)}</span></div>` : ''}
      ${orderBox(r)}
      ${r.status==='confirmed' ? `
        <div class="res-actions">
          <button class="checkout-btn" data-id="${r.id}" data-suggested="${r.order_total || 0}">เช็คบิล</button>
          <button class="cancel-btn" data-id="${r.id}">ยกเลิก</button>
        </div>` : ''}
    </div>`).join('');

  grid.querySelectorAll('.cancel-btn').forEach(btn=>{
    btn.addEventListener('click', async ()=>{
      if(!confirm('ยืนยันการยกเลิกการจองนี้?')) return;
      try{
        await fetch(`/api/reservations/${btn.dataset.id}/cancel`, { method:'POST' });
        toast('ยกเลิกการจองแล้ว');
        load();
      }catch(e){ toast('ยกเลิกไม่สำเร็จ'); }
    });
  });

  grid.querySelectorAll('.checkout-btn').forEach(btn=>{
    btn.addEventListener('click', async ()=>{
      const input = prompt('ยอดที่ลูกค้าจ่าย (บาท)', btn.dataset.suggested || '0');
      if(input === null) return;
      const amount = Number(input.trim());
      if(!Number.isFinite(amount) || amount < 0){
        toast('กรุณาใส่ตัวเลขที่ถูกต้อง');
        return;
      }
      try{
        const r = await fetch(`/api/reservations/${btn.dataset.id}/checkout`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ paid_amount: amount }),
        });
        const data = await r.json().catch(()=>({}));
        if(!r.ok || !data.ok){ toast(data.error || 'เช็คบิลไม่สำเร็จ'); return; }
        toast('เช็คบิลแล้ว โต๊ะว่างให้จองใหม่ได้');
        load();
      }catch(e){ toast('เช็คบิลไม่สำเร็จ'); }
    });
  });

  grid.querySelectorAll('.oi-step').forEach(btn=>{
    btn.addEventListener('click', async ()=>{
      const next = Number(btn.dataset.qty) + Number(btn.dataset.d);
      try{
        await fetch(`/api/order-items/${btn.dataset.itemId}/qty`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ qty: next }),
        });
        load();
      }catch(e){ toast('ปรับจำนวนไม่สำเร็จ'); }
    });
  });

  grid.querySelectorAll('.oi-remove').forEach(btn=>{
    btn.addEventListener('click', async ()=>{
      try{
        await fetch(`/api/order-items/${btn.dataset.itemId}/remove`, { method:'POST' });
        load();
      }catch(e){ toast('ลบรายการไม่สำเร็จ'); }
    });
  });

  grid.querySelectorAll('.order-add-btn').forEach(btn=>{
    btn.addEventListener('click', async ()=>{
      const box = btn.closest('.order-add');
      const name = box.querySelector('.oi-input-name').value.trim();
      const qty = Number(box.querySelector('.oi-input-qty').value);
      const price = Number(box.querySelector('.oi-input-price').value);
      if(!name){ toast('กรุณาใส่ชื่อรายการ'); return; }
      if(!Number.isFinite(qty) || qty < 1){ toast('จำนวนต้องมากกว่า 0'); return; }
      if(!Number.isFinite(price) || price < 0){ toast('ราคาต้องไม่ติดลบ'); return; }
      try{
        const r = await fetch(`/api/reservations/${btn.dataset.resId}/items`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ name, qty, unit_price: price }),
        });
        const data = await r.json().catch(()=>({}));
        if(!r.ok || !data.ok){ toast(data.error || 'เพิ่มรายการไม่สำเร็จ'); return; }
        load();
      }catch(e){ toast('เพิ่มรายการไม่สำเร็จ'); }
    });
  });
}

function init(){
  const d = new Date();
  const iso = new Date(d - d.getTimezoneOffset()*60000).toISOString().slice(0,10);
  $('admin-date').value = iso;
  $('admin-date').addEventListener('change', load);
  load();
}
document.addEventListener('DOMContentLoaded', init);
