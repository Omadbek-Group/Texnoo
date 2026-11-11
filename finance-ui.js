// ══════════════════════════════════════════════════
// MOLIYA VA KASSA (admin / kassir) + TO'LOVLARIM (talaba / ota-ona)
// Barcha raqamlar /api/finance/* dan keladi; brauzerda moliyaviy ma'lumot saqlanmaydi.
// index.html dagi globallardan foydalanadi: curUser, DB, escHtml, showToast, openGlobalModal, closeGlobalModal.
// ══════════════════════════════════════════════════
(function () {
  const METHOD = { cash: 'Naqd', card: 'Plastik', bank: 'Bank' };
  const CATEGORY = {
    rent: 'Ijara', salary: 'Ish haqi', utilities: 'Kommunal', marketing: 'Reklama',
    supplies: 'Jihozlar / kanselyariya', tax: 'Soliq', other: 'Boshqa'
  };
  const esc = (v) => escHtml(v == null ? '' : v);
  const fmt = (n) => (Number(n) || 0).toLocaleString('ru-RU').replace(/,/g, ' ') + " so'm";
  const pad = (n) => String(n).padStart(2, '0');
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const monthStart = () => today().slice(0, 8) + '01';
  const thisMonth = () => today().slice(0, 7);
  const dt = (ms) => { const d = new Date(Number(ms)); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const newKey = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : (Date.now().toString(36) + Math.random().toString(36).slice(2, 12));
  const digits = (v) => String(v || '').replace(/\D/g, '');
  const isFullAdmin = () => curUser && curUser.role === 'admin' && ['platform_admin', 'school_admin', 'director'].includes(curUser.level || 'school_admin');
  const canManage = () => isFullAdmin() || (curUser && curUser.role === 'admin' && curUser.level === 'manager');

  const st = { tab: 'dash', from: monthStart(), to: today(), page: 1, q: '', method: '', status: '', category: '', feeQ: '', auditPage: 1 };

  async function api(path, opts, base = '/api/finance') {
    const res = await fetch(base + path, {
      ...(opts || {}),
      headers: { 'Content-Type': 'application/json', ...((opts && opts.headers) || {}) }
    });
    const out = await res.json().catch(() => ({}));
    if (!res.ok || out.ok === false) throw new Error(out.message || ('Server xatosi (' + res.status + ')'));
    return out;
  }
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== '' && v != null).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');

  const box = (html) => `<div style="padding:28px;text-align:center;color:var(--text3);font-family:'JetBrains Mono',monospace;font-size:12px;">${html}</div>`;
  const loading = () => box('<i class="fas fa-spinner fa-spin"></i> Yuklanmoqda...');
  const errorBox = (msg, retry) => box(`<div style="color:var(--red);margin-bottom:10px;">❌ ${esc(msg)}</div><button class="btn btn-sm" onclick="${retry}"><i class="fas fa-rotate-right"></i> Qayta urinish</button>`);
  const statusBadge = (s) => s === 'void' ? '<span class="badge rr">BEKOR</span>' : '<span class="badge gr">FAOL</span>';
  const label = (t) => `<label style="font-size:10px;color:var(--text3);display:block;margin-bottom:4px;font-family:'JetBrains Mono',monospace;">${t}</label>`;
  const stat = (title, value, sub, cls) => `<div class="sc ${cls || ''}"><div class="sl">${title}</div><div class="sv" style="font-size:18px;">${value}</div><div class="ss">${sub || ''}</div></div>`;
  const pager = (page, size, total, fn) => {
    const pages = Math.max(1, Math.ceil(total / size));
    return `<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;font-size:11px;color:var(--text3);">
      <span>Jami: ${total}</span>
      <span style="display:flex;gap:6px;align-items:center;">
        <button class="btn btn-xs" ${page <= 1 ? 'disabled' : ''} onclick="${fn}(${page - 1})"><i class="fas fa-chevron-left"></i></button>
        ${page} / ${pages}
        <button class="btn btn-xs" ${page >= pages ? 'disabled' : ''} onclick="${fn}(${page + 1})"><i class="fas fa-chevron-right"></i></button>
      </span></div>`;
  };

  // ───────────────────────── Sahifa karkasi ─────────────────────────
  function finRender() {
    const pg = document.getElementById('finpg'); if (!pg) return;
    const tabs = [['dash', 'Dashboard'], ['pay', "To'lovlar"], ['exp', 'Xarajatlar'], ['debt', 'Qarzdorlar'], ['fees', 'Oylik tariflar']];
    pg.innerHTML = `
      <div class="ph"><h2>MOLIYA VA KASSA</h2><p>// To'lovlar, xarajatlar, qarzdorlik va kassa — real yozuvlardan</p></div>
      <div class="card" style="margin-bottom:12px;"><div class="cb" style="display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;">
        <div>${label('DAN')}<input type="date" class="form-control" id="finFrom" value="${st.from}"></div>
        <div>${label('GACHA')}<input type="date" class="form-control" id="finTo" value="${st.to}"></div>
        <button class="btn btn-cyan btn-sm" onclick="finApplyRange()"><i class="fas fa-filter"></i> Qo'llash</button>
        <button class="btn btn-sm" onclick="finQuickRange('today')">Bugun</button>
        <button class="btn btn-sm" onclick="finQuickRange('month')">Shu oy</button>
        <button class="btn btn-sm" onclick="finQuickRange('year')">Shu yil</button>
        <span style="flex:1"></span>
        <button class="btn btn-success btn-sm" onclick="finOpenPayment()"><i class="fas fa-plus"></i> To'lov qabul qilish</button>
        <button class="btn btn-gold btn-sm" onclick="finOpenExpense()"><i class="fas fa-minus"></i> Xarajat</button>
      </div></div>
      <div class="tab-row" style="flex-wrap:wrap;">${tabs.map(([k, t]) => `<button class="tab-btn ${st.tab === k ? 'active' : ''}" onclick="finTab('${k}')">${t}</button>`).join('')}</div>
      <div id="finBody"></div>`;
    finLoadTab();
  }

  function finTab(k) { st.tab = k; st.page = 1; finRender(); }
  function finApplyRange() {
    const f = document.getElementById('finFrom').value, t = document.getElementById('finTo').value;
    if (!f || !t) { showToast('❗ Sanalarni tanlang'); return; }
    st.from = f; st.to = t; st.page = 1; finLoadTab();
  }
  function finQuickRange(kind) {
    st.to = today();
    st.from = kind === 'today' ? today() : kind === 'year' ? today().slice(0, 4) + '-01-01' : monthStart();
    finRender();
  }

  function finLoadTab() {
    const body = document.getElementById('finBody'); if (!body) return;
    body.innerHTML = loading();
    const fn = { dash: loadDash, pay: loadPayments, exp: loadExpenses, debt: loadDebtors, fees: loadFees, audit: loadAudit }[st.tab] || loadDash;
    fn(body).catch(e => { body.innerHTML = errorBox(e.message, 'finLoadTab()'); });
  }

  // ───────────────────────── Dashboard ─────────────────────────
  async function loadDash(body) {
    const s = await api('/summary?' + qs({ from: st.from, to: st.to }));
    const cats = Object.entries(s.expense_by_category).sort((a, b) => b[1] - a[1]);
    body.innerHTML = `
      <div class="fin-grid">
        ${stat('TUSHUM', fmt(s.income), s.payments_count + " ta to'lov", 'gt')}
        ${stat('XARAJAT', fmt(s.expense), 'Tanlangan davr', 'rt')}
        ${stat('SOF FOYDA', fmt(s.net), 'Tushum − xarajat', s.net >= 0 ? 'yt' : 'rt')}
        ${stat('QARZDORLIK', fmt(s.debt_total), s.debtors_count + ' ta qarzdor', 'rt')}
        ${stat('NAQD', fmt(s.income_by_method.cash), 'Tushum')}
        ${stat('PLASTIK', fmt(s.income_by_method.card), 'Tushum')}
        ${stat('BANK', fmt(s.income_by_method.bank), 'Tushum')}
        ${stat("O'QUVCHILAR", s.students_billed + ' / ' + s.students_total, 'Tarif belgilangan / jami')}
      </div>
      <div class="g2">
        <div class="card"><div class="ch"><h4>KUNLIK TUSHUM VA XARAJAT</h4></div><div class="cb">${chart(s.daily)}</div></div>
        <div class="card"><div class="ch"><h4>KASSA QOLDIG'I (BARCHA DAVR)</h4></div><div class="cb">
          ${Object.entries(s.balance_by_method).map(([m, v]) => `<div class="fin-line"><span>${METHOD[m]}</span><strong style="color:${v < 0 ? 'var(--red)' : 'var(--green)'}">${fmt(v)}</strong></div>`).join('')}
          <div style="font-size:10px;color:var(--text3);margin-top:8px;font-family:'JetBrains Mono',monospace;">// Qabul qilingan to'lovlar − xarajatlar, bekor qilinganlarsiz</div>
          <h4 style="margin:16px 0 8px;font-size:12px;">XARAJAT KATEGORIYALARI</h4>
          ${cats.length ? cats.map(([c, v]) => `<div class="fin-line"><span>${esc(CATEGORY[c] || c)}</span><strong>${fmt(v)}</strong></div>`).join('') : '<div style="color:var(--text3);font-size:12px;">// Bu davrda xarajat yo\'q</div>'}
        </div></div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-sm" onclick="finExport('payments')"><i class="fas fa-file-csv"></i> To'lovlar CSV</button>
        <button class="btn btn-sm" onclick="finExport('expenses')"><i class="fas fa-file-csv"></i> Xarajatlar CSV</button>
      </div>`;
  }

  function chart(days) {
    if (!days.length || days.every(d => !d.income && !d.expense)) return box("// Bu davrda yozuv yo'q");
    const max = Math.max(1, ...days.map(d => Math.max(d.income, d.expense)));
    const w = 640, h = 180, slot = w / days.length, bw = Math.max(1, slot / 2 - 1);
    const bars = days.map((d, i) => {
      const x = i * slot, hi = (d.income / max) * (h - 20), he = (d.expense / max) * (h - 20);
      return `<g><title>${d.day}\nTushum: ${fmt(d.income)}\nXarajat: ${fmt(d.expense)}</title>
        <rect x="${x}" y="0" width="${slot}" height="${h}" fill="transparent"></rect>
        <rect x="${x}" y="${h - hi}" width="${bw}" height="${hi}" rx="1" style="fill:var(--green)"></rect>
        <rect x="${x + bw + 1}" y="${h - he}" width="${bw}" height="${he}" rx="1" style="fill:var(--red)"></rect></g>`;
    }).join('');
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:180px;display:block;">${bars}</svg>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3);margin-top:6px;font-family:'JetBrains Mono',monospace;">
        <span>${days[0].day}</span><span><span style="color:var(--green)">■</span> Tushum <span style="color:var(--red)">■</span> Xarajat</span><span>${days[days.length - 1].day}</span></div>`;
  }

  // ───────────────────────── To'lovlar ─────────────────────────
  async function loadPayments(body) {
    const out = await api('/payments?' + qs({ from: st.from, to: st.to, q: st.q, method: st.method, status: st.status, page: st.page, page_size: 25 }));
    body.innerHTML = `
      <div class="card"><div class="ch" style="flex-wrap:wrap;gap:8px;">
        <h4>TO'LOVLAR · ${fmt(out.sum)}</h4>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <input class="form-control" style="width:170px;" placeholder="Ism, guruh, kvitansiya №" value="${esc(st.q)}" onkeydown="if(event.key==='Enter'){finSetFilter('q',this.value)}">
          <select class="form-control" style="width:110px;" onchange="finSetFilter('method',this.value)"><option value="">Barcha turlar</option>${Object.entries(METHOD).map(([k, v]) => `<option value="${k}" ${st.method === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
          <select class="form-control" style="width:110px;" onchange="finSetFilter('status',this.value)"><option value="">Barchasi</option><option value="active" ${st.status === 'active' ? 'selected' : ''}>Faol</option><option value="void" ${st.status === 'void' ? 'selected' : ''}>Bekor</option></select>
          <button class="btn btn-sm" onclick="finExport('payments')"><i class="fas fa-file-csv"></i> CSV</button>
        </div></div>
        <div class="cb" style="padding:0;"><div class="tw"><table>
          <thead><tr><th>№</th><th>Sana</th><th>O'quvchi</th><th>Guruh</th><th>Summa</th><th>Turi</th><th>Davr</th><th>Qabul qildi</th><th>Holat</th><th></th></tr></thead>
          <tbody>${out.items.map(p => `<tr style="${p.status === 'void' ? 'opacity:.55;' : ''}">
            <td style="font-family:'JetBrains Mono',monospace;font-size:11px;">${esc(p.receipt_no)}</td>
            <td style="font-size:11px;">${dt(p.created_at)}</td>
            <td><strong>${esc(p.student_name)}</strong></td><td>${esc(p.group_name)}</td>
            <td style="font-weight:700;white-space:nowrap;">${fmt(p.amount)}</td><td>${METHOD[p.method] || esc(p.method)}</td><td>${esc(p.period)}</td>
            <td style="font-size:11px;">${esc(p.created_by_name)}</td>
            <td title="${esc(p.void_reason || '')}">${statusBadge(p.status)}</td>
            <td style="white-space:nowrap;"><button class="btn btn-xs" title="Kvitansiya" onclick="finShowReceipt('${esc(p.id)}')"><i class="fas fa-receipt"></i></button>
              ${isFullAdmin() && p.status === 'active' ? `<button class="btn btn-xs btn-danger" title="Bekor qilish" onclick="finVoid('payments','${esc(p.id)}')"><i class="fas fa-ban"></i></button>` : ''}</td>
          </tr>`).join('') || `<tr><td colspan="10">${box("// Bu davrda to'lov yo'q")}</td></tr>`}</tbody>
        </table></div>${pager(out.page, out.page_size, out.total, 'finPage')}</div></div>`;
  }
  function finSetFilter(k, v) { st[k] = v; st.page = 1; finLoadTab(); }
  function finPage(p) { st.page = p; finLoadTab(); }

  function studentOptions(selected) {
    return (DB.students || []).slice().sort((a, b) => String(a.name).localeCompare(String(b.name)))
      .map(s => `<option value="${s.id}" ${String(s.id) === String(selected) ? 'selected' : ''}>${esc(s.name)} — ${esc(s.group || '')}</option>`).join('');
  }

  function finOpenPayment(studentId, amount) {
    openGlobalModal(`
      <div class="modal-title"><i class="fas fa-cash-register"></i> To'lov qabul qilish</div>
      <input type="hidden" id="fpKey" value="${newKey()}">
      <div class="form-group">${label("O'QUVCHI")}
        <input class="form-control" placeholder="Qidirish..." style="margin-bottom:6px;" oninput="finFilterSelect('fpStudent',this.value)">
        <select class="form-control" id="fpStudent" size="6"><option value="">— tanlang —</option>${studentOptions(studentId)}</select></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:140px;">${label("SUMMA (SO'M)")}<input class="form-control" id="fpAmount" inputmode="numeric" value="${amount || ''}" placeholder="500000"></div>
        <div class="form-group" style="flex:1;min-width:120px;">${label('TURI')}<select class="form-control" id="fpMethod">${Object.entries(METHOD).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
        <div class="form-group" style="flex:1;min-width:120px;">${label('QAYSI OY UCHUN')}<input type="month" class="form-control" id="fpPeriod" value="${thisMonth()}"></div>
      </div>
      <div class="form-group">${label('IZOH')}<input class="form-control" id="fpNote" maxlength="500" placeholder="Ixtiyoriy"></div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-success" style="flex:1;" id="fpSubmit" onclick="finSubmitPayment()"><i class="fas fa-check"></i> Qabul qilish</button></div>`);
  }
  function finFilterSelect(id, q) {
    const sel = document.getElementById(id); if (!sel) return;
    const needle = q.trim().toLowerCase();
    Array.from(sel.options).forEach(o => { if (o.value) o.hidden = needle && !o.textContent.toLowerCase().includes(needle); });
  }
  async function finSubmitPayment() {
    const btn = document.getElementById('fpSubmit');
    const body = {
      idempotency_key: document.getElementById('fpKey').value,
      student_id: document.getElementById('fpStudent').value,
      amount: digits(document.getElementById('fpAmount').value),
      method: document.getElementById('fpMethod').value,
      period: document.getElementById('fpPeriod').value,
      note: document.getElementById('fpNote').value
    };
    if (!body.student_id) { showToast("❗ O'quvchini tanlang"); return; }
    if (!Number(body.amount)) { showToast('❗ Summani kiriting'); return; }
    btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saqlanmoqda...';
    try {
      const out = await api('/payments', { method: 'POST', body: JSON.stringify(body) });
      closeGlobalModal();
      showToast(out.duplicate ? "ℹ Bu to'lov allaqachon saqlangan" : "✅ To'lov qabul qilindi: " + out.payment.receipt_no);
      if (document.getElementById('finpg')?.classList.contains('active')) finLoadTab();
      finShowReceipt(out.payment.id);
    } catch (e) {
      showToast('❌ ' + e.message);
      btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Qabul qilish';
    }
  }

  // ───────────────────────── Kvitansiya ─────────────────────────
  function receiptHtml(p, school) {
    return `<div style="font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.7;">
      <div style="text-align:center;font-weight:700;font-size:14px;">${esc(school)}</div>
      <div style="text-align:center;margin-bottom:8px;">ELEKTRON KVITANSIYA</div>
      <div>№: <strong>${esc(p.receipt_no)}</strong></div>
      <div>Sana: ${dt(p.created_at)}</div>
      <div>O'quvchi: ${esc(p.student_name)} (ID ${esc(p.student_id)})</div>
      <div>Guruh: ${esc(p.group_name || '—')}</div>
      <div>Davr: ${esc(p.period || '—')}</div>
      <div>To'lov turi: ${METHOD[p.method] || esc(p.method)}</div>
      <div style="font-size:16px;font-weight:700;margin:6px 0;">Summa: ${fmt(p.amount)}</div>
      <div>Qabul qildi: ${esc(p.created_by_name)}</div>
      ${p.note ? `<div>Izoh: ${esc(p.note)}</div>` : ''}
      ${p.status === 'void' ? `<div style="color:#c00;font-weight:700;">BEKOR QILINGAN: ${esc(p.void_reason)}</div>` : ''}
      <div style="margin-top:8px;font-size:10px;opacity:.7;">ID: ${esc(p.id)}<br>Bu elektron kvitansiya, fiskal chek emas.</div>
    </div>`;
  }
  async function finShowReceipt(id) {
    try {
      const out = await api('/payments/' + encodeURIComponent(id));
      window.__finReceipt = receiptHtml(out.payment, out.school_name);
      openGlobalModal(`<div class="modal-title"><i class="fas fa-receipt"></i> Kvitansiya</div>
        <div style="background:var(--card2);border-radius:8px;padding:14px;margin-bottom:12px;">${window.__finReceipt}</div>
        <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Yopish</button>
        <button class="btn btn-cyan" style="flex:1;" onclick="finPrintReceipt()"><i class="fas fa-print"></i> Chop etish</button></div>`);
    } catch (e) { showToast('❌ ' + e.message); }
  }
  function finPrintReceipt() {
    const w = window.open('', '_blank', 'width=420,height=640');
    if (!w) { showToast('❗ Brauzer yangi oynani blokladi'); return; }
    w.document.write(`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Kvitansiya</title></head><body style="padding:16px;color:#000;background:#fff;">${window.__finReceipt || ''}</body></html>`);
    w.document.close(); w.focus(); w.print();
  }

  async function finVoid(kind, id) {
    const reason = prompt('Bekor qilish sababi (majburiy):');
    if (reason == null) return;
    if (reason.trim().length < 3) { showToast('❗ Sababni aniqroq yozing'); return; }
    try {
      await api('/' + kind + '/' + encodeURIComponent(id) + '/void', { method: 'POST', body: JSON.stringify({ reason: reason.trim() }) });
      showToast('✅ Bekor qilindi (yozuv tarixda qoladi)');
      finLoadTab();
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Xarajatlar ─────────────────────────
  async function loadExpenses(body) {
    const out = await api('/expenses?' + qs({ from: st.from, to: st.to, category: st.category, status: st.status, page: st.page, page_size: 25 }));
    body.innerHTML = `
      <div class="card"><div class="ch" style="flex-wrap:wrap;gap:8px;"><h4>XARAJATLAR · ${fmt(out.sum)}</h4>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <select class="form-control" style="width:150px;" onchange="finSetFilter('category',this.value)"><option value="">Barcha kategoriyalar</option>${Object.entries(CATEGORY).map(([k, v]) => `<option value="${k}" ${st.category === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
          <button class="btn btn-sm" onclick="finExport('expenses')"><i class="fas fa-file-csv"></i> CSV</button>
        </div></div>
        <div class="cb" style="padding:0;"><div class="tw"><table>
          <thead><tr><th>Sana</th><th>Kategoriya</th><th>Summa</th><th>Turi</th><th>Izoh</th><th>Kiritdi</th><th>Holat</th><th></th></tr></thead>
          <tbody>${out.items.map(x => `<tr style="${x.status === 'void' ? 'opacity:.55;' : ''}">
            <td style="font-size:11px;">${dt(x.created_at)}</td><td>${esc(CATEGORY[x.category] || x.category)}</td>
            <td style="font-weight:700;white-space:nowrap;">${fmt(x.amount)}</td><td>${METHOD[x.method] || esc(x.method)}</td>
            <td style="font-size:11px;">${esc(x.note)}</td><td style="font-size:11px;">${esc(x.created_by_name)}</td>
            <td title="${esc(x.void_reason || '')}">${statusBadge(x.status)}</td>
            <td>${isFullAdmin() && x.status === 'active' ? `<button class="btn btn-xs btn-danger" title="Bekor qilish" onclick="finVoid('expenses','${esc(x.id)}')"><i class="fas fa-ban"></i></button>` : ''}</td>
          </tr>`).join('') || `<tr><td colspan="8">${box("// Bu davrda xarajat yo'q")}</td></tr>`}</tbody>
        </table></div>${pager(out.page, out.page_size, out.total, 'finPage')}</div></div>`;
  }

  function finOpenExpense() {
    openGlobalModal(`
      <div class="modal-title"><i class="fas fa-file-invoice-dollar"></i> Xarajat kiritish</div>
      <input type="hidden" id="feKey" value="${newKey()}">
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:150px;">${label('KATEGORIYA')}<select class="form-control" id="feCategory">${Object.entries(CATEGORY).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
        <div class="form-group" style="flex:1;min-width:140px;">${label("SUMMA (SO'M)")}<input class="form-control" id="feAmount" inputmode="numeric" placeholder="250000"></div>
        <div class="form-group" style="flex:1;min-width:120px;">${label('TURI')}<select class="form-control" id="feMethod">${Object.entries(METHOD).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
      </div>
      <div class="form-group">${label('IZOH')}<input class="form-control" id="feNote" maxlength="500" placeholder="Masalan: noyabr ijarasi"></div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-gold" style="flex:1;" id="feSubmit" onclick="finSubmitExpense()"><i class="fas fa-check"></i> Saqlash</button></div>`);
  }
  async function finSubmitExpense() {
    const btn = document.getElementById('feSubmit');
    const body = {
      idempotency_key: document.getElementById('feKey').value,
      category: document.getElementById('feCategory').value,
      amount: digits(document.getElementById('feAmount').value),
      method: document.getElementById('feMethod').value,
      note: document.getElementById('feNote').value
    };
    if (!Number(body.amount)) { showToast('❗ Summani kiriting'); return; }
    btn.disabled = true;
    try {
      await api('/expenses', { method: 'POST', body: JSON.stringify(body) });
      closeGlobalModal(); showToast('✅ Xarajat saqlandi');
      if (document.getElementById('finpg')?.classList.contains('active')) finLoadTab();
    } catch (e) { showToast('❌ ' + e.message); btn.disabled = false; }
  }

  // ───────────────────────── Qarzdorlar va tariflar ─────────────────────────
  async function loadDebtors(body) {
    const out = await api('/debtors');
    body.innerHTML = `<div class="card"><div class="ch"><h4>QARZDORLAR · ${out.count} ta · ${fmt(out.total)}</h4></div>
      <div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'quvchi</th><th>Guruh</th><th>Telefon</th><th>Oylik</th><th>Hisoblangan</th><th>To'langan</th><th>Qarz</th><th>Oy</th><th></th></tr></thead>
        <tbody>${out.items.map(d => `<tr>
          <td><strong>${esc(d.student_name)}</strong></td><td>${esc(d.group_name)}</td><td style="font-size:11px;">${esc(d.phone)}</td>
          <td>${fmt(d.monthly_fee)}</td><td>${fmt(d.charged)}</td><td>${fmt(d.paid)}</td>
          <td style="color:var(--red);font-weight:700;white-space:nowrap;">${fmt(d.debt)}</td><td>${d.months_owed ?? '—'}</td>
          <td><button class="btn btn-xs btn-success" onclick="finOpenPayment(${d.student_id}, ${Math.min(Math.max(0, d.debt), d.monthly_fee || Math.max(0, d.debt)) || ''})"><i class="fas fa-cash-register"></i></button></td>
        </tr>`).join('') || `<tr><td colspan="9">${box('// Qarzdor yo\'q 🎉')}</td></tr>`}</tbody>
      </table></div></div>
      <div style="font-size:10px;color:var(--text3);padding:10px 14px;font-family:'JetBrains Mono',monospace;">// Qarz = oylik tariflar (tarif boshlangan oydan shu oygacha) − bekor qilinmagan to'lovlar</div></div>`;
  }

  async function loadFees(body) {
    const out = await api('/fees');
    window.__finFees = out.items;
    body.innerHTML = `<div class="card"><div class="ch" style="flex-wrap:wrap;gap:8px;"><h4>OYLIK TARIFLAR · ${esc(out.month)}</h4>
        <input class="form-control" style="width:200px;" placeholder="Ism yoki guruh" value="${esc(st.feeQ)}" oninput="finFeeSearch(this.value)"></div>
      <div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'quvchi</th><th>Guruh</th><th>Oylik tarif</th><th>To'langan</th><th>Qarz / avans</th><th></th></tr></thead>
        <tbody id="finFeeRows"></tbody></table></div></div></div>`;
    finFeeSearch(st.feeQ);
  }
  function finFeeSearch(q) {
    st.feeQ = q;
    const el = document.getElementById('finFeeRows'); if (!el) return;
    const needle = q.trim().toLowerCase();
    const rows = (window.__finFees || []).filter(r => !needle || (r.student_name + ' ' + r.group_name).toLowerCase().includes(needle));
    el.innerHTML = rows.map(r => `<tr>
      <td><strong>${esc(r.student_name)}</strong></td><td>${esc(r.group_name)}</td>
      <td>${r.monthly_fee || r.base_fee ? fmt(r.monthly_fee) : '<span style="color:var(--text3)">belgilanmagan</span>'}${r.discount_pct ? `<br><span class="badge bg" title="${esc(r.discount_reason)}">-${r.discount_pct}% · ${esc(r.discount_reason)}</span>` : ''}</td><td>${fmt(r.paid)}</td>
      <td style="font-weight:700;color:${r.debt > 0 ? 'var(--red)' : 'var(--green)'};">${r.debt > 0 ? fmt(r.debt) : r.debt < 0 ? 'avans ' + fmt(-r.debt) : '0'}</td>
      <td style="white-space:nowrap;">${isFullAdmin() ? `<button class="btn btn-xs btn-cyan" onclick="finOpenFee(${r.student_id})"><i class="fas fa-pen"></i> Tarif</button>` : ''}
        <button class="btn btn-xs btn-success" onclick="finOpenPayment(${r.student_id}, ${Math.min(Math.max(0, r.debt), r.monthly_fee || Math.max(0, r.debt)) || ''})"><i class="fas fa-cash-register"></i></button></td>
    </tr>`).join('') || `<tr><td colspan="6">${box("// O'quvchi topilmadi")}</td></tr>`;
  }
  async function finOpenFee(studentId) {
    const row = (window.__finFees || []).find(r => r.student_id === studentId) || {};
    let history = [];
    try { history = (await api('/fees?student_id=' + studentId)).history; } catch (e) { showToast('❌ ' + e.message); return; }
    openGlobalModal(`
      <div class="modal-title"><i class="fas fa-tags"></i> Oylik tarif: ${esc(row.student_name)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:150px;">${label("OYLIK SUMMA (SO'M)")}<input class="form-control" id="ffFee" inputmode="numeric" value="${row.base_fee || ''}"></div>
        <div class="form-group" style="flex:1;min-width:140px;">${label('QAYSI OYDAN')}<input type="month" class="form-control" id="ffFrom" value="${thisMonth()}"></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:0 0 110px;">${label('CHEGIRMA %')}<input class="form-control" id="ffDisc" inputmode="numeric" value="${row.discount_pct || 0}"></div>
        <div class="form-group" style="flex:1;min-width:160px;">${label('CHEGIRMA SABABI')}<input class="form-control" id="ffReason" maxlength="300" value="${esc(row.discount_reason || '')}" placeholder="Masalan: aka-uka, a'lochi, ijtimoiy"></div>
      </div>
      <div style="font-size:11px;color:var(--text3);margin-bottom:10px;">0 kiritilsa — shu oydan boshlab hisoblash to'xtaydi (masalan, o'quvchi ketganda). Eski tariflar tarixda qoladi.</div>
      ${history.length ? `<div style="font-size:11px;margin-bottom:10px;max-height:120px;overflow:auto;">${history.map(h => `<div class="fin-line"><span>${esc(h.effective_from)} dan</span><span>${fmt(h.monthly_fee)}${h.discount_pct ? ` −${h.discount_pct}% (${esc(h.discount_reason)})` : ''} · ${esc(h.created_by_name)}</span></div>`).join('')}</div>` : ''}
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-cyan" style="flex:1;" onclick="finSubmitFee(${studentId})"><i class="fas fa-check"></i> Saqlash</button></div>`);
  }
  async function finSubmitFee(studentId) {
    const fee = digits(document.getElementById('ffFee').value);
    if (fee === '') { showToast('❗ Summani kiriting'); return; }
    try {
      await api('/fees', { method: 'POST', body: JSON.stringify({ student_id: studentId, monthly_fee: Number(fee), effective_from: document.getElementById('ffFrom').value,
        discount_pct: Number(digits(document.getElementById('ffDisc').value) || 0), discount_reason: document.getElementById('ffReason').value.trim() }) });
      closeGlobalModal(); showToast('✅ Tarif saqlandi'); finLoadTab();
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Audit ─────────────────────────
  const ACTION = {
    'payment.create': "To'lov qabul qilindi", 'payment.void': "To'lov bekor qilindi", 'expense.create': 'Xarajat kiritildi',
    'expense.void': 'Xarajat bekor qilindi', 'fee.set': "Tarif o'rnatildi", 'finance.export': 'Eksport',
    'auth.login': 'Tizimga kirish', 'auth.register': "Ro'yxatdan o'tish", 'auth.change_password': "Parol o'zgardi",
    'data.import_json': 'JSON import', 'settings.exchange_rate': "Kurs o'zgardi"
  };
  async function loadAudit(body) {
    const out = await api('/audit?' + qs({ page: st.auditPage, page_size: 30 }));
    body.innerHTML = `<div class="card"><div class="ch"><h4>AUDIT LOG</h4></div><div class="cb" style="padding:0;"><div class="tw"><table>
      <thead><tr><th>Vaqt</th><th>Kim</th><th>Amal</th><th>Obyekt</th><th>Tafsilot</th><th>IP</th></tr></thead>
      <tbody>${out.items.map(a => `<tr>
        <td style="font-size:11px;white-space:nowrap;">${dt(a.created_at)}</td>
        <td>${esc(a.actor_name)} <span style="color:var(--text3);font-size:10px;">${esc(a.actor_role)} #${esc(a.actor_id)}</span></td>
        <td>${esc(ACTION[a.action] || a.action)}</td><td style="font-size:11px;">${esc(a.entity)} ${esc(String(a.entity_id || '').slice(0, 8))}</td>
        <td style="font-size:10px;font-family:'JetBrains Mono',monospace;max-width:260px;overflow:hidden;text-overflow:ellipsis;">${esc(JSON.stringify(a.details))}</td>
        <td style="font-size:10px;">${esc(a.ip)}</td></tr>`).join('') || `<tr><td colspan="6">${box("// Yozuv yo'q")}</td></tr>`}</tbody>
      </table></div>${pager(out.page, out.page_size, out.total, 'finAuditPage')}</div></div>`;
  }
  function finAuditPage(p) { st.auditPage = p; finLoadTab(); }

  // ───────────────────────── Eksport ─────────────────────────
  async function finExport(kind) {
    try {
      const res = await fetch('/api/finance/export?' + qs({ kind, from: st.from, to: st.to }));
      if (!res.ok) { const out = await res.json().catch(() => ({})); throw new Error(out.message || 'Eksport xatosi'); }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url; a.download = `${kind}_${st.from}_${st.to}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Talaba / ota-ona ─────────────────────────
  async function finRenderMy() {
    const pg = document.getElementById('myfinpg'); if (!pg) return;
    const title = curUser && curUser.role === 'parent' ? "FARZANDIM TO'LOVLARI" : "TO'LOVLARIM";
    pg.innerHTML = `<div class="ph"><h2>${title}</h2><p>// Oylik to'lov, qarz va kvitansiyalar</p></div><div id="myFinBody">${loading()}</div>`;
    const body = document.getElementById('myFinBody');
    try {
      const out = await api('/my');
      body.innerHTML = out.items.map(c => `
        <div class="card" style="margin-bottom:14px;"><div class="ch"><h4>${esc(c.student_name)} · ${esc(c.group_name)}</h4></div><div class="cb">
          <div class="fin-grid">
            ${stat('OYLIK TO\'LOV', c.monthly_fee ? fmt(c.monthly_fee) : '—', 'Joriy tarif')}
            ${stat(c.debt > 0 ? 'QARZ' : 'AVANS', fmt(Math.abs(c.debt)), out.month + ' holatiga', c.debt > 0 ? 'rt' : 'gt')}
            ${stat("JAMI TO'LANGAN", fmt(c.paid), c.payments.filter(p => p.status === 'active').length + " ta to'lov")}
          </div>
          <div class="tw"><table><thead><tr><th>№</th><th>Sana</th><th>Davr</th><th>Summa</th><th>Turi</th><th>Holat</th><th></th></tr></thead>
          <tbody>${c.payments.map(p => `<tr><td style="font-size:11px;font-family:'JetBrains Mono',monospace;">${esc(p.receipt_no)}</td><td style="font-size:11px;">${dt(p.created_at)}</td>
            <td>${esc(p.period)}</td><td style="font-weight:700;">${fmt(p.amount)}</td><td>${METHOD[p.method] || ''}</td><td>${statusBadge(p.status)}</td>
            <td><button class="btn btn-xs" onclick="finShowReceipt('${esc(p.id)}')"><i class="fas fa-receipt"></i></button></td></tr>`).join('')
          || `<tr><td colspan="7">${box("// To'lovlar hali yo'q")}</td></tr>`}</tbody></table></div>
        </div></div>`).join('') || box(curUser && curUser.role === 'parent'
          ? "// Bog'langan farzand topilmadi. \"Farzandim\" bo'limida farzandingiz telefonini bog'lang."
          : "// Ma'lumot yo'q");
    } catch (e) { body.innerHTML = errorBox(e.message, 'finRenderMy()'); }
  }

  // Kassir/menejer faqat o'z bo'limlarini ko'radi (server ham shunday cheklaydi). '' = hammasi ko'rinadi.
  const ROLE_PAGES = { cashier: /finpg|tapg|settpg|doLogout/, manager: /crmpg|schedpg|attpg|aicenterpg|tapg|settpg|doLogout/ };
  function finApplyRoleNav(level) {
    const keep = ROLE_PAGES[level];
    document.querySelectorAll('#aNav .nav-item').forEach(el => {
      el.style.display = keep && !keep.test(el.getAttribute('onclick') || '') ? 'none' : '';
    });
  }

  // ══════════════════════════════════════════════════
  // CRM: o'quvchi hayot sikli (faqat admin; kassir faqat o'qiy oladi)
  // ══════════════════════════════════════════════════
  const crmApi = (path, opts) => api(path, opts, '/api/crm');
  const STATUS = { active: ['Faol', 'gr'], frozen: ['Muzlatilgan', 'bb'], graduated: ['Bitirgan', 'bg'], left: ['Ketgan', 'rr'] };
  const statusTag = (s) => `<span class="badge ${(STATUS[s] || STATUS.active)[1]}">${(STATUS[s] || STATUS.active)[0].toUpperCase()}</span>`;
  const EVENT = { enrolled: 'Qabul qilindi', group_changed: "Guruh o'zgardi", status_changed: "Holat o'zgardi", course_added: "Kurs qo'shildi", course_removed: 'Kursdan chiqarildi' };
  const crm = { status: 'active', group: '', q: '', page: 1, groups: [], debtors: false };

  async function crmRender() {
    const pg = document.getElementById('crmpg'); if (!pg) return;
    const tabs = [['leads', 'Qabul (yangi kelganlar)'], ['active', 'Faol'], ['frozen', 'Muzlatilgan'], ['graduated', 'Bitiruvchilar arxivi'], ['left', 'Ketganlar'], ['all', 'Hammasi']];
    pg.innerHTML = `
      <div class="ph"><h2>O'QUVCHILAR (CRM)</h2><p>// Qabul, guruh, muzlatish, arxiv va o'quvchi tarixi</p></div>
      <div id="crmSummary" class="fin-grid">${loading()}</div>
      <div class="card" style="margin-bottom:12px;"><div class="cb" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
        <input class="form-control" style="width:200px;" placeholder="Ism, telefon yoki guruh" value="${esc(crm.q)}" onkeydown="if(event.key==='Enter'){crmSet('q',this.value)}">
        <select class="form-control" style="width:140px;" id="crmGroupSel" onchange="crmSet('group',this.value)"><option value="">Barcha guruhlar</option></select>
        <label style="font-size:12px;display:flex;align-items:center;gap:6px;"><input type="checkbox" ${crm.debtors ? 'checked' : ''} onchange="crmSet('debtors',this.checked)"> Faqat qarzdorlar</label>
        <span style="flex:1"></span>
        ${canManage() ? `<button class="btn btn-success btn-sm" onclick="crmOpenCreate()"><i class="fas fa-user-plus"></i> Yangi o'quvchi</button>` : ''}
      </div></div>
      <div class="tab-row" style="flex-wrap:wrap;">${tabs.map(([k, t]) => `<button class="tab-btn ${crm.status === k ? 'active' : ''}" onclick="crmSet('status','${k}')">${t}</button>`).join('')}</div>
      <div id="crmBody">${loading()}</div>`;
    crmApi('/summary').then(s => {
      document.getElementById('crmSummary').innerHTML =
        stat("O'QIYOTGANLAR", s.total, 'Faol + muzlatilgan', 'yt') + stat('FAOL', s.counts.active, '', 'gt') +
        stat('MUZLATILGAN', s.counts.frozen, '') + stat('BU OY YANGI', s.new_this_month, s.month, 'gt') +
        stat('BU OY KETGAN', s.left_this_month, s.month, 'rt') + stat('BITIRUVCHILAR', s.counts.graduated, 'Arxivda');
    }).catch(e => { document.getElementById('crmSummary').innerHTML = errorBox(e.message, 'crmRender()'); });
    crmApi('/groups').then(out => {
      crm.groups = out.items.map(x => x.name);
      const sel = document.getElementById('crmGroupSel');
      if (sel) sel.innerHTML = '<option value="">Barcha guruhlar</option>' + crm.groups.map(n => `<option ${n === crm.group ? 'selected' : ''}>${esc(n)}</option>`).join('');
    }).catch(() => {});
    crmLoad();
  }
  function crmSet(k, v) { crm[k] = v; crm.page = 1; if (k === 'status') crmRender(); else crmLoad(); }
  function crmPage(p) { crm.page = p; crmLoad(); }

  async function crmLoad() {
    const body = document.getElementById('crmBody'); if (!body) return;
    if (crm.status === 'leads') return leadsLoad(body);
    body.innerHTML = loading();
    try {
      const out = await crmApi('/students?' + qs({ status: crm.status, group: crm.group, q: crm.q, page: crm.page, page_size: 25, debtors: crm.debtors ? 1 : '' }));
      const admin = canManage();
      body.innerHTML = `<div class="card"><div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'quvchi</th><th>Telefon</th><th>Guruh</th><th>Holat</th><th>Qabul</th><th>Oylik</th><th>Qarz</th><th></th></tr></thead>
        <tbody>${out.items.map(s => `<tr>
          <td><strong>${esc(s.name)}</strong><br><span style="font-size:10px;color:var(--text3);font-family:'JetBrains Mono',monospace;">ID:${s.id}</span></td>
          <td style="font-size:11px;">${esc(s.phone)}${s.parentPhone ? `<br><span style="color:var(--text3);">ota-ona: ${esc(s.parentPhone)}</span>` : ''}</td>
          <td>${esc(s.group)}</td><td>${statusTag(s.status)}</td><td style="font-size:11px;white-space:nowrap;">${esc(s.enrolled_at || '—')}</td>
          <td>${s.monthly_fee ? fmt(s.monthly_fee) : '—'}</td>
          <td style="font-weight:700;color:${s.debt > 0 ? 'var(--red)' : 'var(--text2)'};white-space:nowrap;">${s.debt > 0 ? fmt(s.debt) : '—'}</td>
          <td style="white-space:nowrap;">
            <button class="btn btn-xs" title="Tarix" onclick="crmHistory(${s.id})"><i class="fas fa-clock-rotate-left"></i></button>
            ${admin ? crmActions(s) : ''}</td>
        </tr>`).join('') || `<tr><td colspan="7">${box("// O'quvchi topilmadi")}</td></tr>`}</tbody>
      </table></div>${pager(out.page, out.page_size, out.total, 'crmPage')}</div></div>`;
    } catch (e) { body.innerHTML = errorBox(e.message, 'crmLoad()'); }
  }

  function crmActions(s) {
    const btn = (kind, icon, title, cls) => `<button class="btn btn-xs ${cls || ''}" title="${title}" onclick="crmOpenAction(${s.id},'${kind}')"><i class="fas ${icon}"></i></button>`;
    if (s.status === 'active') return btn('move', 'fa-people-arrows', "Guruhga ko'chirish") + btn('frozen', 'fa-snowflake', 'Muzlatish') + btn('graduated', 'fa-graduation-cap', 'Bitirdi', 'btn-gold') + btn('left', 'fa-user-minus', 'Ketdi', 'btn-danger');
    if (s.status === 'frozen') return btn('active', 'fa-play', 'Qayta faollashtirish', 'btn-success') + btn('left', 'fa-user-minus', 'Ketdi', 'btn-danger');
    return btn('active', 'fa-rotate-left', 'Qayta faollashtirish', 'btn-success');
  }

  const groupSelect = (id, selected) => `<input class="form-control" id="${id}" list="${id}List" value="${esc(selected || '')}" placeholder="Masalan: D1">
    <datalist id="${id}List">${crm.groups.map(n => `<option value="${esc(n)}">`).join('')}</datalist>`;

  function crmOpenAction(id, kind) {
    const titles = { move: "Boshqa guruhga ko'chirish", frozen: 'Muzlatish', active: 'Qayta faollashtirish', graduated: 'Bitirdi (arxivga)', left: 'Ketdi (arxivga)' };
    const needReason = kind !== 'active';
    openGlobalModal(`
      <div class="modal-title"><i class="fas fa-user-gear"></i> ${titles[kind]}</div>
      ${kind === 'move' || kind === 'active' ? `<div class="form-group">${label(kind === 'move' ? 'YANGI GURUH' : 'GURUH (ixtiyoriy, o\'zgarsa)')}${groupSelect('caGroup', '')}</div>` : ''}
      <div class="form-group">${label('QAYSI SANADAN')}<input type="date" class="form-control" id="caDate" value="${today()}"></div>
      <div class="form-group">${label(needReason && kind !== 'move' ? 'SABAB (majburiy)' : 'IZOH')}<input class="form-control" id="caReason" maxlength="300"></div>
      ${kind === 'frozen' ? `<div style="font-size:11px;color:var(--text3);margin-bottom:10px;">Muzlatilgan butun oylar uchun oylik to'lov hisoblanmaydi. Tarix va to'lovlar saqlanadi.</div>` : ''}
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-cyan" style="flex:1;" id="caSubmit" onclick="crmSubmitAction(${id},'${kind}')"><i class="fas fa-check"></i> Tasdiqlash</button></div>`);
  }
  async function crmSubmitAction(id, kind) {
    const btn = document.getElementById('caSubmit');
    const group = document.getElementById('caGroup')?.value.trim() || '';
    const body = { date: document.getElementById('caDate').value, reason: document.getElementById('caReason').value.trim() };
    if (kind === 'move' && !group) { showToast('❗ Guruhni kiriting'); return; }
    btn.disabled = true;
    try {
      if (kind === 'move') await crmApi(`/students/${id}/move`, { method: 'POST', body: JSON.stringify({ ...body, group }) });
      else await crmApi(`/students/${id}/status`, { method: 'POST', body: JSON.stringify({ ...body, status: kind, group }) });
      closeGlobalModal(); showToast('✅ Saqlandi');
      await loadData(); // eski sahifalar (reyting, guruhlar) ham yangi holatni ko'rsin
      crmRender();
    } catch (e) { showToast('❌ ' + e.message); btn.disabled = false; }
  }

  function crmOpenCreate() {
    openGlobalModal(`
      <div class="modal-title"><i class="fas fa-user-plus"></i> Yangi o'quvchi</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:140px;">${label('ISM')}<input class="form-control" id="ccFirst"></div>
        <div class="form-group" style="flex:1;min-width:140px;">${label('FAMILIYA')}<input class="form-control" id="ccLast"></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:140px;">${label('TELEFON')}<input class="form-control" id="ccPhone" placeholder="+998901234567"></div>
        <div class="form-group" style="flex:1;min-width:140px;">${label('OTA-ONA TELEFONI')}<input class="form-control" id="ccParent" placeholder="Ixtiyoriy"></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:120px;">${label('GURUH')}${groupSelect('ccGroup', crm.group)}</div>
        <div class="form-group" style="flex:1;min-width:120px;">${label("OYLIK TO'LOV")}<input class="form-control" id="ccFee" inputmode="numeric" placeholder="Ixtiyoriy"></div>
        <div class="form-group" style="flex:1;min-width:120px;">${label('BOSHLANISH')}<input type="date" class="form-control" id="ccStart" value="${today()}"></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:0 0 160px;">${label("TUG'ILGAN SANA (ixtiyoriy)")}<input type="date" class="form-control" id="ccBirth" max="${today()}"></div>
        <div class="form-group" style="flex:1;min-width:180px;">${label('MANZIL (ixtiyoriy)')}<input class="form-control" id="ccAddress" maxlength="200"></div>
      </div>
      <div class="form-group">${label("PAROL (bo'sh qolsa avtomatik)")}<input class="form-control" id="ccPass" autocomplete="new-password"></div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-success" style="flex:1;" id="ccSubmit" onclick="crmSubmitCreate()"><i class="fas fa-check"></i> Qo'shish</button></div>`);
  }
  async function crmSubmitCreate() {
    const v = (id) => document.getElementById(id).value.trim();
    const fee = digits(v('ccFee'));
    const body = { firstName: v('ccFirst'), lastName: v('ccLast'), phone: v('ccPhone'), parentPhone: v('ccParent'), group: v('ccGroup'),
      start_date: v('ccStart'), birthDate: v('ccBirth'), address: v('ccAddress'), password: document.getElementById('ccPass').value, monthly_fee: fee === '' ? null : Number(fee) };
    if (!body.firstName || !body.lastName || !body.phone || !body.group) { showToast("❗ Ism, familiya, telefon va guruh majburiy"); return; }
    const btn = document.getElementById('ccSubmit'); btn.disabled = true;
    try {
      const out = await crmApi('/students', { method: 'POST', body: JSON.stringify(body) });
      if (window.__enrollLead) { await leadStatus(window.__enrollLead, 'enrolled', out.student.id); window.__enrollLead = null; }
      openGlobalModal(`<div class="modal-title"><i class="fas fa-check"></i> O'quvchi qo'shildi</div>
        <p style="margin:10px 0;">${esc(out.student.name)} · ${esc(out.student.group)}</p>
        ${out.password ? `<p style="margin-bottom:14px;">Kirish: <code>${esc(out.student.phone)}</code><br>Parol: <code style="font-size:16px;">${esc(out.password)}</code><br><span style="font-size:11px;color:var(--text3);">Parol faqat hozir ko'rsatiladi — o'quvchiga yetkazing.</span></p>` : ''}
        <button class="btn btn-cyan" style="width:100%;" onclick="closeGlobalModal()">Yopish</button>`);
      await loadData();
      crmRender();
    } catch (e) { showToast('❌ ' + e.message); btn.disabled = false; }
  }

  async function crmHistory(id) {
    try {
      const out = await crmApi(`/students/${id}/history`);
      const s = out.student;
      const evLine = (e) => {
        let what = EVENT[e.type] || e.type;
        if (e.type === 'group_changed') what += `: ${esc(e.from_group || '—')} → ${esc(e.to_group)}`;
        if (e.type === 'status_changed') what += `: ${(STATUS[e.from_status] || [e.from_status])[0]} → ${(STATUS[e.to_status] || [e.to_status])[0]}`;
        if (e.type === 'enrolled') what += ` (${esc(e.to_group || '')})`;
        return `<div class="fin-line"><span><strong>${esc(e.effective_date)}</strong> · ${what}${e.reason ? ` — <em>${esc(e.reason)}</em>` : ''}</span>
          <span style="color:var(--text3);font-size:10px;">${esc(e.actor_name || e.source)}</span></div>`;
      };
      openGlobalModal(`<div class="modal-title"><i class="fas fa-clock-rotate-left"></i> ${esc(s.name)}</div>
        <div class="fin-grid" style="margin-bottom:10px;">
          ${stat('TELEFON', `<a href="tel:${esc(s.phone)}" style="color:inherit;font-size:15px;">${esc(s.phone)}</a>`, s.parentPhone ? 'Ota-ona: ' + esc(s.parentPhone) : '')}
          ${stat('KURSLAR', 1 + s.extraGroups.length, [s.group, ...s.extraGroups].map(esc).join(', '))}
          ${stat("O'QITUVCHI", esc((out.teachers || []).join(', ') || '—'), '')}
          ${stat('DAVOMAT', out.attendance.rate == null ? '—' : out.attendance.rate + '%', `${out.attendance.present} keldi · ${out.attendance.absent} kelmadi`)}
          ${stat('VAZIFA BAHOSI', out.homework.avg ?? '—', out.homework.graded + ' ta baholangan')}
          ${stat('TESTLAR', out.tests.length, out.tests[0] ? `oxirgi: ${out.tests[0].correct}/${out.tests[0].total}` : '')}
        </div>
        <div style="font-size:12px;margin-bottom:10px;">${statusTag(s.status)} · Tug'ilgan: ${esc(s.birthDate || '—')} · Manzil: ${esc(s.address || '—')}<br>
          Oylik: ${s.monthly_fee ? fmt(s.monthly_fee) : '—'}${s.discount_pct ? ` (chegirma ${s.discount_pct}%: ${esc(s.discount_reason)})` : ''} · To'langan: ${fmt(s.paid)} · <strong style="color:${s.debt > 0 ? 'var(--red)' : 'var(--green)'}">${s.debt > 0 ? 'Qarz ' + fmt(s.debt) : s.debt < 0 ? 'Avans ' + fmt(-s.debt) : "Qarz yo'q"}</strong></div>
        <div style="max-height:50vh;overflow:auto;">
          <h4 style="font-size:12px;margin:8px 0;">TARIX</h4>${out.events.map(evLine).join('') || `<div style="color:var(--text3);font-size:12px;">// Hodisa yo'q (CRM'dan oldin qo'shilgan)</div>`}
          <h4 style="font-size:12px;margin:12px 0 8px;">TO'LOVLAR</h4>${out.payments.map(p => `<div class="fin-line"><span>${esc(p.day)} · ${esc(p.receipt_no)} · ${esc(p.period || '')}</span><span>${fmt(p.amount)} ${p.status === 'void' ? statusBadge('void') : ''}</span></div>`).join('') || `<div style="color:var(--text3);font-size:12px;">// To'lov yo'q</div>`}
          <h4 style="font-size:12px;margin:12px 0 8px;">TEST NATIJALARI</h4>${out.tests.map(t => `<div class="fin-line"><span>${esc(t.test)}</span><span>${esc(t.correct)}/${esc(t.total)} · ${t.date ? dt(t.date) : ''}</span></div>`).join('') || `<div style="color:var(--text3);font-size:12px;">// Test ishlamagan</div>`}
          <h4 style="font-size:12px;margin:12px 0 8px;">TARIFLAR</h4>${out.fees.map(f => `<div class="fin-line"><span>${esc(f.effective_from)} dan</span><span>${fmt(f.monthly_fee)}</span></div>`).join('') || `<div style="color:var(--text3);font-size:12px;">// Tarif belgilanmagan</div>`}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">
          ${isFullAdmin() ? `<button class="btn btn-success" style="flex:1;" onclick="finOpenPayment(${s.id}, ${Math.min(Math.max(0, s.debt), s.monthly_fee || Math.max(0, s.debt)) || ''})"><i class="fas fa-cash-register"></i> To'lov qabul qilish</button>` : ''}
          <button class="btn btn-gold" style="flex:1;" onclick="crmCertificate(${s.id})"><i class="fas fa-certificate"></i> Sertifikat</button>
          ${canManage() ? `<button class="btn btn-cyan" style="flex:1;" onclick="crmEditProfile(${s.id})"><i class="fas fa-pen"></i> Tahrirlash</button>
          <button class="btn" style="flex:1;" onclick="crmOpenCourse(${s.id})"><i class="fas fa-plus"></i> Kurs qo'shish</button>` : ''}
          <button class="btn" style="flex:1;" onclick="closeGlobalModal()">Yopish</button></div>`);
      window.__crmProfile = out;
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ══════════════════════════════════════════════════
  // DARS JADVALI, DAVOMAT, O'QITUVCHI OYLIGI
  // ══════════════════════════════════════════════════
  const schApi = (path, opts) => api(path, opts, '/api/school');
  const WD = { 1: 'Dushanba', 2: 'Seshanba', 3: 'Chorshanba', 4: 'Payshanba', 5: 'Juma', 6: 'Shanba', 7: 'Yakshanba' };
  const ATT = { present: ['Keldi', 'var(--green)'], late: ['Kechikdi', 'var(--gold)'], excused: ['Sababli', 'var(--cyan)'], absent: ['Kelmadi', 'var(--red)'] };
  const rate = (r) => r == null ? '—' : r + '%';
  const lessonsTable = (items, editable) => {
    if (!items.length) return box("// Jadvalda dars yo'q");
    const byDay = {};
    items.forEach(l => { (byDay[l.weekday] = byDay[l.weekday] || []).push(l); });
    return Object.keys(byDay).sort().map(d => `<div class="card" style="margin-bottom:10px;"><div class="ch"><h4>${WD[d]}</h4></div><div class="cb" style="padding:0;"><div class="tw"><table>
      <tbody>${byDay[d].map(l => `<tr><td style="white-space:nowrap;font-family:'JetBrains Mono',monospace;">${esc(l.start_time)}–${esc(l.end_time)}</td>
        <td><strong>${esc(l.group_name)}</strong></td><td>${esc(l.subject)}</td><td>${esc(l.teacher_name)}</td><td>${l.room ? 'Xona ' + esc(l.room) : ''}</td>
        <td>${editable ? `<button class="btn btn-xs btn-danger" title="Olib tashlash" onclick="schRemove('${esc(l.id)}')"><i class="fas fa-trash"></i></button>` : ''}</td></tr>`).join('')}</tbody>
    </table></div></div></div>`).join('');
  };

  async function schRender() {
    const pg = document.getElementById('schedpg'); if (!pg) return;
    const edit = canManage();
    const teachers = (DB.teachers || []).filter(t => t.status !== 'pending');
    pg.innerHTML = `<div class="ph"><h2>DARS JADVALI</h2><p>// Haftalik darslar; o'qituvchi, xona va guruh to'qnashuvi tekshiriladi</p></div>
      ${edit ? `<div class="card" style="margin-bottom:12px;"><div class="cb" style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;">
        <div>${label('GURUH')}<input class="form-control" id="slGroup" list="slGroupList" style="width:110px;"><datalist id="slGroupList"></datalist></div>
        <div>${label('FAN')}<input class="form-control" id="slSubject" style="width:130px;" placeholder="Python"></div>
        <div>${label("O'QITUVCHI")}<select class="form-control" id="slTeacher" style="width:150px;">${teachers.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select></div>
        <div>${label('XONA')}<input class="form-control" id="slRoom" style="width:80px;" placeholder="101"></div>
        <div>${label('KUN')}<select class="form-control" id="slDay" style="width:120px;">${Object.entries(WD).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
        <div>${label('BOSHLANISH')}<input type="time" class="form-control" id="slStart" value="14:00"></div>
        <div>${label('TUGASH')}<input type="time" class="form-control" id="slEnd" value="15:30"></div>
        <button class="btn btn-success btn-sm" onclick="schAdd()"><i class="fas fa-plus"></i> Qo'shish</button>
      </div></div>` : ''}
      ${edit ? `<div class="card" style="margin-bottom:12px;"><div class="ch"><h4>YANGI GURUH OCHISH</h4></div><div class="cb" style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;">
        <div>${label('GURUH NOMI')}<input class="form-control" id="ngName" style="width:110px;" placeholder="PY-1"></div>
        <div>${label('FAN')}<input class="form-control" id="ngSubject" style="width:130px;" placeholder="Python"></div>
        <div>${label("O'QITUVCHI")}<select class="form-control" id="ngTeacher" style="width:150px;">${teachers.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select></div>
        <div>${label('XONA')}<input class="form-control" id="ngRoom" style="width:80px;"></div>
        <div>${label('KUNLAR')}<div style="display:flex;gap:4px;flex-wrap:wrap;">${Object.entries(WD).map(([k, v]) => `<label style="font-size:11px;display:flex;align-items:center;gap:2px;"><input type="checkbox" class="ngDay" value="${k}">${v.slice(0, 3)}</label>`).join('')}</div></div>
        <div>${label('BOSHLANISH')}<input type="time" class="form-control" id="ngStart" value="14:00"></div>
        <div>${label('TUGASH')}<input type="time" class="form-control" id="ngEnd" value="15:30"></div>
        <button class="btn btn-success btn-sm" onclick="schCreateGroup()"><i class="fas fa-layer-group"></i> Guruh ochish</button>
      </div></div>` : ''}
      <div id="schBody">${loading()}</div>`;
    if (edit) crmApi('/groups').then(out => { const dl = document.getElementById('slGroupList'); if (dl) dl.innerHTML = out.items.map(x => `<option value="${esc(x.name)}">`).join(''); }).catch(() => {});
    try {
      const out = await schApi('/lessons');
      document.getElementById('schBody').innerHTML = lessonsTable(out.items, edit);
    } catch (e) { document.getElementById('schBody').innerHTML = errorBox(e.message, 'schRender()'); }
  }
  async function schAdd() {
    const v = (id) => document.getElementById(id).value.trim();
    try {
      await schApi('/lessons', { method: 'POST', body: JSON.stringify({ group: v('slGroup'), subject: v('slSubject'), teacher_id: Number(v('slTeacher')),
        room: v('slRoom'), weekday: Number(v('slDay')), start: v('slStart'), end: v('slEnd') }) });
      showToast("✅ Dars jadvalga qo'shildi"); schRender();
    } catch (e) { showToast('❌ ' + e.message); }
  }
  async function schRemove(id) {
    if (!confirm("Darsni jadvaldan olib tashlaysizmi?")) return;
    try { await schApi(`/lessons/${encodeURIComponent(id)}/remove`, { method: 'POST', body: '{}' }); showToast('✅ Olib tashlandi'); schRender(); }
    catch (e) { showToast('❌ ' + e.message); }
  }

  const att = { group: '', date: today(), month: thisMonth(), marks: {} };
  async function attRender() {
    const pg = document.getElementById('attpg'); if (!pg) return;
    pg.innerHTML = `<div class="ph"><h2>DAVOMAT</h2><p>// Keldi · kechikdi · sababli · kelmadi — kunlik va oylik statistika</p></div>
      ${canManage() ? `<div class="card" style="margin-bottom:12px;"><div class="ch"><h4>BUGUNGI DARSLAR</h4></div><div class="cb" id="attToday">${loading()}</div></div>` : ''}
      <div class="card" style="margin-bottom:12px;"><div class="cb" style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;">
        <div>${label('GURUH')}<select class="form-control" id="attGroup" style="width:140px;" onchange="attPick(this.value)"></select></div>
        <div>${label('SANA')}<input type="date" class="form-control" id="attDate" value="${att.date}" max="${today()}" onchange="att.date=this.value;attLoadSheet()"></div>
        <div>${label('OY (STATISTIKA)')}<input type="month" class="form-control" id="attMonth" value="${att.month}" onchange="attSetMonth(this.value)"></div>
      </div></div>
      <div id="attSheet"></div><div id="attStats"></div>`;
    window.att = att;
    if (canManage()) schApi('/attendance/today').then(out => {
      document.getElementById('attToday').innerHTML = out.items.length ? `<div class="tw"><table><tbody>${out.items.map(l => `<tr>
        <td style="font-family:'JetBrains Mono',monospace;">${esc(l.start_time)}</td><td><strong>${esc(l.group_name)}</strong></td><td>${esc(l.teacher_name)}</td>
        <td>${l.total ? `${l.present + l.late}/${l.group_size} keldi · ${rate(l.rate)}` : '<span style="color:var(--gold)">belgilanmagan</span>'}</td>
        <td><button class="btn btn-xs" onclick="attPick('${esc(l.group_name)}')">Ochish</button></td></tr>`).join('')}</tbody></table></div>`
        : box("// Bugun jadvalda dars yo'q");
    }).catch(e => { document.getElementById('attToday').innerHTML = errorBox(e.message, 'attRender()'); });
    try {
      const out = await schApi('/groups');
      const sel = document.getElementById('attGroup');
      if (!out.items.length) { document.getElementById('attSheet').innerHTML = box("// Sizga biriktirilgan guruh yo'q"); return; }
      if (!out.items.includes(att.group)) att.group = out.items[0];
      sel.innerHTML = out.items.map(n => `<option ${n === att.group ? 'selected' : ''}>${esc(n)}</option>`).join('');
      attLoadSheet(); attLoadStats();
    } catch (e) { document.getElementById('attSheet').innerHTML = errorBox(e.message, 'attRender()'); }
  }
  function attPick(group) { att.group = group; const sel = document.getElementById('attGroup'); if (sel) sel.value = group; attLoadSheet(); attLoadStats(); }
  function attSetMonth(m) { att.month = m; attLoadStats(); }

  async function attLoadSheet() {
    const el = document.getElementById('attSheet'); if (!el || !att.group) return;
    el.innerHTML = loading();
    try {
      const out = await schApi('/attendance/sheet?' + qs({ group: att.group, date: att.date }));
      att.marks = {};
      out.items.forEach(s => { if (s.mark) att.marks[s.student_id] = s.mark; });
      att.sheet = out.items;
      el.innerHTML = `<div class="card" style="margin-bottom:12px;"><div class="ch" style="flex-wrap:wrap;gap:8px;">
          <h4>${esc(out.group)} · ${esc(out.date)} ${out.lessons.map(l => `· ${esc(l.subject)} ${esc(l.start_time)}`).join(' ')}</h4>
          <div style="display:flex;gap:6px;"><button class="btn btn-sm" onclick="attAll('present')">Hammasi keldi</button>
          <button class="btn btn-cyan btn-sm" id="attSave" onclick="attSave()"><i class="fas fa-save"></i> Saqlash</button></div></div>
        <div class="cb" style="padding:0;"><div class="tw"><table><tbody id="attRows"></tbody></table></div>
        ${out.marked_by ? `<div style="font-size:10px;color:var(--text3);padding:8px 14px;">// Oxirgi belgilagan: ${esc(out.marked_by)}</div>` : ''}</div></div>`;
      attDrawRows();
    } catch (e) { el.innerHTML = errorBox(e.message, 'attLoadSheet()'); }
  }
  function attDrawRows() {
    const body = document.getElementById('attRows'); if (!body) return;
    body.innerHTML = (att.sheet || []).map(s => `<tr><td><strong>${esc(s.name)}</strong>${s.status === 'frozen' ? ' <span class="badge bb">MUZLATILGAN</span>' : ''}${s.debt > 0 ? ` <span class="badge rr">QARZ ${fmt(s.debt)}</span>` : ''}
      <br><span style="font-size:10px;color:var(--text3);">${esc(s.phone)}</span></td>
      <td style="white-space:nowrap;">${Object.entries(ATT).map(([k, [t, c]]) => `<button class="btn btn-xs" style="${att.marks[s.student_id] === k ? `background:${c};color:#000;border-color:${c};` : ''}"
        aria-pressed="${att.marks[s.student_id] === k}" onclick="attMark(${s.student_id},'${k}')">${t}</button>`).join(' ')}</td></tr>`).join('')
      || `<tr><td>${box("// Guruhda faol o'quvchi yo'q")}</td></tr>`;
  }
  function attMark(id, status) { att.marks[id] = status; attDrawRows(); }
  function attAll(status) { (att.sheet || []).forEach(s => { if (s.status !== 'frozen') att.marks[s.student_id] = status; }); attDrawRows(); }
  async function attSave() {
    const marks = Object.entries(att.marks).map(([student_id, status]) => ({ student_id: Number(student_id), status }));
    if (!marks.length) { showToast("❗ Hech kim belgilanmagan"); return; }
    const btn = document.getElementById('attSave'); btn.disabled = true;
    try {
      const out = await schApi('/attendance', { method: 'POST', body: JSON.stringify({ group: att.group, date: att.date, marks }) });
      showToast(`✅ Saqlandi: ${out.counts.present} keldi, ${out.counts.late} kechikdi, ${out.counts.excused} sababli, ${out.counts.absent} kelmadi`);
      attLoadStats();
    } catch (e) { showToast('❌ ' + e.message); }
    btn.disabled = false;
  }
  async function attLoadStats() {
    const el = document.getElementById('attStats'); if (!el || !att.group) return;
    try {
      const out = await schApi('/attendance/stats?' + qs({ group: att.group, month: att.month }));
      el.innerHTML = `<div class="card"><div class="ch"><h4>OYLIK STATISTIKA · ${esc(att.month)} · ${rate(out.summary.rate)}</h4></div><div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'quvchi</th><th>Keldi</th><th>Kechikdi</th><th>Sababli</th><th>Kelmadi</th><th>Davomat</th></tr></thead>
        <tbody>${out.students.map(s => `<tr><td>${esc(s.name)}</td><td>${s.present}</td><td>${s.late}</td><td>${s.excused}</td>
          <td style="color:${s.absent ? 'var(--red)' : ''}">${s.absent}</td><td><strong>${rate(s.rate)}</strong></td></tr>`).join('') || `<tr><td colspan="6">${box("// Ma'lumot yo'q")}</td></tr>`}</tbody>
      </table></div></div></div>`;
    } catch (e) { el.innerHTML = errorBox(e.message, 'attLoadStats()'); }
  }

  async function attRenderMy() {
    const pg = document.getElementById('myattpg'); if (!pg) return;
    pg.innerHTML = `<div class="ph"><h2>DAVOMAT VA JADVAL</h2><p>// Darslar jadvali va qatnashish tarixi</p></div>
      <div style="margin-bottom:12px;">${label('OY')}<input type="month" class="form-control" style="width:170px;" id="myAttMonth" value="${att.month}" onchange="att.month=this.value;attRenderMy()"></div>
      <div id="myAttBody">${loading()}</div>`;
    window.att = att;
    try {
      const out = await schApi('/attendance/my?' + qs({ month: att.month }));
      document.getElementById('myAttBody').innerHTML = out.items.map(c => `<div class="card" style="margin-bottom:14px;"><div class="ch"><h4>${esc(c.name)} · ${esc(c.group)}</h4></div><div class="cb">
        <div class="fin-grid">${stat('DAVOMAT', rate(c.stats.rate), att.month, 'gt')}${stat('KELDI', c.stats.present, '')}${stat('KECHIKDI', c.stats.late, '')}
          ${stat('SABABLI', c.stats.excused, '')}${stat('KELMADI', c.stats.absent, '', c.stats.absent ? 'rt' : '')}</div>
        <h4 style="font-size:12px;margin:6px 0;">DARS JADVALI</h4>${lessonsTable(c.lessons, false)}
        <h4 style="font-size:12px;margin:12px 0 6px;">QATNASHISH</h4>${c.records.map(r => `<div class="fin-line"><span>${esc(r.lesson_date)}</span>
          <strong style="color:${(ATT[r.status] || ['', ''])[1]}">${(ATT[r.status] || [r.status])[0]}</strong></div>`).join('') || `<div style="color:var(--text3);font-size:12px;">// Bu oyda yozuv yo'q</div>`}
      </div></div>`).join('') || box(curUser && curUser.role === 'parent' ? "// Bog'langan farzand topilmadi" : "// Ma'lumot yo'q");
    } catch (e) { document.getElementById('myAttBody').innerHTML = errorBox(e.message, 'attRenderMy()'); }
  }

  const ruleText = (r) => !r ? '<span style="color:var(--text3)">belgilanmagan</span>'
    : r.type === 'fixed' ? `Qat'iy ${fmt(r.value)}` : r.type === 'per_student' ? `Har to'lagan o'quvchi: ${fmt(r.value)}` : `${r.value / 100}% tushumdan`;
  const sal = { month: thisMonth() };
  async function salRender() {
    const pg = document.getElementById('salpg'); if (!pg) return;
    pg.innerHTML = `<div class="ph"><h2>O'QITUVCHILAR OYLIGI</h2><p>// Qat'iy maosh yoki o'quvchilar to'lovidan foiz</p></div>
      <div style="margin-bottom:12px;">${label('OY')}<input type="month" class="form-control" style="width:170px;" value="${sal.month}" onchange="salSetMonth(this.value)"></div>
      <div id="salBody">${loading()}</div>`;
    try {
      const out = await schApi('/salary?' + qs({ month: sal.month }));
      window.__salRows = out.items;
      document.getElementById('salBody').innerHTML = `<div class="card"><div class="ch"><h4>JAMI: ${fmt(out.total)}</h4></div><div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'qituvchi</th><th>Shart</th><th>O'quvchilar</th><th>Tushum (shu oy)</th><th>Hisoblangan oylik</th><th>Avans / berilgan</th><th>Qoldi</th><th></th></tr></thead>
        <tbody>${out.items.map(r => `<tr><td><strong>${esc(r.teacher_name)}</strong></td><td>${ruleText(r.rule)}</td><td>${r.students}</td>
          <td>${fmt(r.base)} <span style="color:var(--text3);font-size:10px;">(${r.payments_count} ta)</span></td>
          <td style="font-weight:700;color:var(--green);white-space:nowrap;">${fmt(r.amount)}</td>
          <td style="white-space:nowrap;">${fmt(r.advance)} / ${fmt(r.paid_out)}</td>
          <td style="font-weight:700;white-space:nowrap;color:${r.remaining < 0 ? 'var(--red)' : ''}">${fmt(r.remaining)}</td>
          <td style="white-space:nowrap;"><button class="btn btn-xs btn-cyan" onclick="salOpenRule(${r.teacher_id})"><i class="fas fa-pen"></i> Shart</button>
            <button class="btn btn-xs btn-gold" onclick="salOpenPayout(${r.teacher_id})"><i class="fas fa-hand-holding-dollar"></i> Berish</button></td></tr>`).join('')
          || `<tr><td colspan="8">${box("// O'qituvchi yo'q")}</td></tr>`}</tbody></table></div>
        <div style="font-size:10px;color:var(--text3);padding:10px 14px;font-family:'JetBrains Mono',monospace;">// Foizli oylik: shu oyda qabul qilingan, bekor qilinmagan to'lovlardan (to'lov paytidagi o'qituvchiga bog'lanadi)</div></div></div>`;
    } catch (e) { document.getElementById('salBody').innerHTML = errorBox(e.message, 'salRender()'); }
  }
  function salSetMonth(m) { sal.month = m; salRender(); }
  function salOpenRule(tid) {
    const r = (window.__salRows || []).find(x => x.teacher_id === tid) || {};
    const rule = r.rule || {};
    openGlobalModal(`<div class="modal-title"><i class="fas fa-sack-dollar"></i> Oylik sharti: ${esc(r.teacher_name)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:140px;">${label('TURI')}<select class="form-control" id="srType">
          <option value="percent" ${rule.type !== 'fixed' ? 'selected' : ''}>Foiz (tushumdan)</option><option value="fixed" ${rule.type === 'fixed' ? 'selected' : ''}>Qat'iy maosh</option><option value="per_student" ${rule.type === 'per_student' ? 'selected' : ''}>Har to'lagan o'quvchi uchun</option></select></div>
        <div class="form-group" style="flex:1;min-width:120px;">${label("QIYMAT (% yoki so'm)")}<input class="form-control" id="srValue" inputmode="decimal" value="${rule.type ? (rule.type === 'percent' ? rule.value / 100 : rule.value) : ''}"></div>
        <div class="form-group" style="flex:1;min-width:130px;">${label('QAYSI OYDAN')}<input type="month" class="form-control" id="srFrom" value="${sal.month}"></div>
      </div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-cyan" style="flex:1;" onclick="salSaveRule(${tid})"><i class="fas fa-check"></i> Saqlash</button></div>`);
  }
  async function salSaveRule(tid) {
    const type = document.getElementById('srType').value;
    const raw = document.getElementById('srValue').value.replace(/\s/g, '').replace(',', '.');
    if (raw === '' || isNaN(Number(raw))) { showToast('❗ Qiymatni kiriting'); return; }
    try {
      await schApi('/salary/rules', { method: 'POST', body: JSON.stringify({ teacher_id: tid, type, value: raw, effective_from: document.getElementById('srFrom').value }) });
      closeGlobalModal(); showToast('✅ Shart saqlandi'); salRender();
    } catch (e) { showToast('❌ ' + e.message); }
  }
  async function salRenderMy() {
    const pg = document.getElementById('mysalpg'); if (!pg) return;
    pg.innerHTML = `<div class="ph"><h2>OYLIGIM</h2><p>// Shart va shu oy hisoblangan summa</p></div>
      <div style="margin-bottom:12px;">${label('OY')}<input type="month" class="form-control" style="width:170px;" value="${sal.month}" onchange="sal.month=this.value;salRenderMy()"></div>
      <div id="mySalBody">${loading()}</div>`;
    window.sal = sal;
    try {
      const r = (await schApi('/salary/my?' + qs({ month: sal.month }))).item;
      document.getElementById('mySalBody').innerHTML = !r ? box("// Ma'lumot yo'q") : `
        <div class="fin-grid">${stat('HISOBLANGAN OYLIK', fmt(r.amount), sal.month, 'gt')}${stat('OLINGAN AVANS', fmt(r.advance), 'Jami berilgan: ' + fmt(r.paid_out))}${stat('QOLDI', fmt(r.remaining), '', 'yt')}${stat('SHART', ruleText(r.rule), '')}
          ${stat("O'QUVCHILARIM", r.students, r.paid_students + ' tasi shu oy to\'lagan')}${stat('TUSHUM', fmt(r.base), r.payments_count + " ta to'lov")}</div>
        ${r.rule && r.rule.type === 'percent' ? `<div class="card"><div class="ch"><h4>HISOBGA KIRGAN TO'LOVLAR</h4></div><div class="cb" style="padding:0;"><div class="tw"><table>
          <tbody>${(r.payments || []).map(x => `<tr><td>${esc(x.day)}</td><td>${esc(x.student_name)}</td><td>${fmt(x.amount)}</td></tr>`).join('') || `<tr><td>${box("// Bu oyda to'lov yo'q")}</td></tr>`}</tbody>
        </table></div></div></div>` : ''}`;
    } catch (e) { document.getElementById('mySalBody').innerHTML = errorBox(e.message, 'salRenderMy()'); }
  }

  // ───────────────────────── Sertifikat (chop etish uchun) ─────────────────────────
  function crmCertificate(id) {
    const out = window.__crmProfile;
    if (!out || out.student.id !== id) { showToast('❗ Profilni qayta oching'); return; }
    const s = out.student;
    const enrolled = (out.events.filter(e => e.type === 'enrolled').pop() || {}).effective_date || '';
    const finished = (out.events.find(e => e.type === 'status_changed' && e.to_status === 'graduated') || {}).effective_date || today();
    const school = (DB.settings && DB.settings.schoolName) || 'TEXNOO';
    const no = 'CERT-' + finished.replace(/-/g, '') + '-' + s.id;
    const w = window.open('', '_blank', 'width=1000,height=720');
    if (!w) { showToast('❗ Brauzer yangi oynani blokladi'); return; }
    w.document.write(`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Sertifikat ${esc(s.name)}</title>
      <style>@page{size:A4 landscape;margin:0}body{margin:0;font-family:Georgia,serif;background:#fff;color:#1a1a1a}
      .c{box-sizing:border-box;width:297mm;height:210mm;padding:22mm;border:12px double #b8860b;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
      h1{font-size:54px;letter-spacing:8px;margin:0 0 8px;color:#8a6508}.sub{font-size:18px;letter-spacing:3px;margin-bottom:28px}
      .name{font-size:40px;font-weight:bold;border-bottom:2px solid #b8860b;padding:0 30px 6px;margin:12px 0 18px}
      .meta{display:flex;justify-content:space-between;width:100%;margin-top:40px;font-size:14px}</style></head>
      <body><div class="c"><div style="font-size:20px;font-weight:bold;">${esc(school)}</div><h1>SERTIFIKAT</h1>
      <div class="sub">Ushbu sertifikat</div><div class="name">${esc(s.name)}</div>
      <div style="font-size:18px;max-width:80%;">${esc(s.group)} guruhida ${enrolled ? esc(enrolled) + ' — ' : ''}${esc(finished)} davomida o'qiganini tasdiqlaydi.</div>
      <div class="meta"><span>№ ${esc(no)}</span><span>Berilgan sana: ${esc(today())}</span><span>Rahbar: ____________</span></div>
      </div><script>window.onload=()=>window.print()<\/script></body></html>`);
    w.document.close();
  }

  // ───────────────────────── Qabul: yangi kelganlar fan bo'yicha ─────────────────────────
  const LEAD = { new: ['Yangi', 'bb'], contacted: ["Bog'lanildi", 'bg'], trial: ['Sinov darsi', 'bg'], waiting: ['Guruh kutmoqda', 'gr'], enrolled: ['Qabul qilindi', 'gr'], rejected: ['Rad etdi', 'rr'] };
  const leads = { subject: '', status: 'open' };
  async function leadsLoad(body) {
    body = body || document.getElementById('crmBody'); if (!body) return;
    body.innerHTML = loading();
    try {
      const out = await crmApi('/leads?' + qs({ subject: leads.subject, status: leads.status, q: crm.q }));
      body.innerHTML = `
        <div class="card" style="margin-bottom:12px;"><div class="ch"><h4>YANGI KELGAN O'QUVCHINI YOZISH</h4></div><div class="cb" style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;">
          <div>${label('ISM FAMILIYA')}<input class="form-control" id="ldName" style="width:170px;"></div>
          <div>${label('TELEFON')}<input class="form-control" id="ldPhone" style="width:150px;" placeholder="+998901234567"></div>
          <div>${label('FAN')}<input class="form-control" id="ldSubject" list="ldSubjects" style="width:150px;" placeholder="Python, Ingliz tili..."><datalist id="ldSubjects">${out.subjects.map(x => `<option value="${esc(x.subject)}">`).join('')}</datalist></div>
          <div>${label('IZOH')}<input class="form-control" id="ldNote" style="width:170px;" placeholder="Vaqti, darajasi..."></div>
          <button class="btn btn-success btn-sm" onclick="leadAdd()"><i class="fas fa-plus"></i> Yozish</button>
        </div></div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">
          <button class="btn btn-sm ${leads.subject ? '' : 'btn-cyan'}" onclick="leadsSet('subject','')">Barcha fanlar</button>
          ${out.subjects.map(x => `<button class="btn btn-sm ${leads.subject === x.subject ? 'btn-cyan' : ''}" onclick="leadsSet('subject','${esc(x.subject).replace(/'/g, "\\'")}')">${esc(x.subject)} · ${x.waiting} kutmoqda</button>`).join('')}
          <select class="form-control" style="width:150px;margin-left:auto;" onchange="leadsSet('status',this.value)">
            <option value="open" ${leads.status === 'open' ? 'selected' : ''}>Kutayotganlar</option>
            ${Object.entries(LEAD).map(([k, v]) => `<option value="${k}" ${leads.status === k ? 'selected' : ''}>${v[0]}</option>`).join('')}</select>
        </div>
        <div class="card"><div class="cb" style="padding:0;"><div class="tw"><table>
          <thead><tr><th>Ism</th><th>Telefon</th><th>Fan</th><th>Izoh</th><th>Yozilgan</th><th>Holat</th><th></th></tr></thead>
          <tbody>${out.items.map(l => `<tr><td><strong>${esc(l.name)}</strong></td><td style="font-size:11px;">${esc(l.phone)}</td><td>${esc(l.subject)}</td>
            <td style="font-size:11px;">${esc(l.note || '')}</td><td style="font-size:11px;">${dt(l.created_at)}</td>
            <td><span class="badge ${(LEAD[l.status] || LEAD.new)[1]}">${(LEAD[l.status] || LEAD.new)[0]}</span>${l.trial_at ? `<br><span style="font-size:10px;">🧪 ${esc(l.trial_at.replace('T', ' '))} · ${esc(l.trial_group || '')}</span>` : ''}</td>
            <td style="white-space:nowrap;">${['new', 'contacted', 'trial', 'waiting'].includes(l.status) ? `
              <select class="form-control" style="width:120px;display:inline-block;" onchange="leadStatus('${esc(l.id)}',this.value)"><option value="">Holat...</option>
                <option value="contacted">Bog'lanildi</option><option value="trial">Sinov darsiga yozish</option><option value="waiting">Guruh kutmoqda</option><option value="rejected">Rad etdi</option></select>
              <button class="btn btn-xs btn-success" title="Guruhga qabul qilish" onclick="leadEnroll('${esc(l.id)}')"><i class="fas fa-user-plus"></i> Qabul</button>` : ''}</td>
          </tr>`).join('') || `<tr><td colspan="7">${box("// Ro'yxat bo'sh")}</td></tr>`}</tbody></table></div></div></div>`;
      window.__leads = out.items;
    } catch (e) { body.innerHTML = errorBox(e.message, 'leadsLoad()'); }
  }
  function leadsSet(k, v) { leads[k] = v; leadsLoad(); }
  async function leadAdd() {
    const v = (id) => document.getElementById(id).value.trim();
    try {
      await crmApi('/leads', { method: 'POST', body: JSON.stringify({ name: v('ldName'), phone: v('ldPhone'), subject: v('ldSubject'), note: v('ldNote') }) });
      showToast("✅ Yozildi"); leadsLoad();
    } catch (e) { showToast('❌ ' + e.message); }
  }
  async function leadStatus(id, status, studentId) {
    if (!status) return;
    if (status === 'trial' && !studentId) return leadOpenTrial(id);
    try { await crmApi(`/leads/${encodeURIComponent(id)}/status`, { method: 'POST', body: JSON.stringify({ status, student_id: studentId }) }); leadsLoad(); }
    catch (e) { showToast('❌ ' + e.message); }
  }
  // Qabul: o'quvchi qo'shish oynasi lead ma'lumotlari bilan to'ldiriladi, saqlangach lead "qabul qilindi" bo'ladi.
  function leadEnroll(id) {
    const l = (window.__leads || []).find(x => x.id === id); if (!l) return;
    crmOpenCreate();
    const [first, ...rest] = l.name.split(' ');
    document.getElementById('ccFirst').value = first || '';
    document.getElementById('ccLast').value = rest.join(' ');
    document.getElementById('ccPhone').value = l.phone;
    window.__enrollLead = id;
  }

  // ───────────────────────── O'qituvchi: o'quvchilarim ─────────────────────────
  const stud = { q: '', debtors: false };
  async function studRender() {
    const pg = document.getElementById('mystudpg'); if (!pg) return;
    pg.innerHTML = `<div class="ph"><h2>O'QUVCHILARIM</h2><p>// Telefon, qarz va shu oy davomati</p></div>
      <div class="card" style="margin-bottom:12px;"><div class="cb" style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
        <input class="form-control" style="width:240px;" placeholder="Ism, telefon yoki guruh bo'yicha qidirish" value="${esc(stud.q)}" oninput="studSet('q',this.value)">
        <label style="font-size:12px;display:flex;align-items:center;gap:6px;"><input type="checkbox" ${stud.debtors ? 'checked' : ''} onchange="studSet('debtors',this.checked)"> Faqat qarzdorlar</label>
        <span id="studCount" style="font-size:12px;color:var(--text3);"></span>
      </div></div><div id="studBody">${loading()}</div>`;
    studLoad();
  }
  let studTimer = null;
  function studSet(k, v) { stud[k] = v; clearTimeout(studTimer); studTimer = setTimeout(studLoad, 250); }
  async function studLoad() {
    const el = document.getElementById('studBody'); if (!el) return;
    try {
      const out = await schApi('/students?' + qs({ q: stud.q, debtors: stud.debtors ? 1 : '' }));
      document.getElementById('studCount').textContent = `${out.items.length} ta o'quvchi · ${out.debtors} ta qarzdor`;
      const bday = out.birthdays.length ? `<div class="card" style="margin-bottom:12px;border-left:3px solid var(--gold);"><div class="cb">🎂 Bugun tug'ilgan kun: <strong>${out.birthdays.map(esc).join(', ')}</strong> — tabriklashni unutmang!</div></div>` : '';
      el.innerHTML = bday + `<div class="card"><div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'quvchi</th><th>Telefon</th><th>Ota-ona</th><th>Guruh</th><th>Davomat</th><th>Oylik</th><th>Qarz</th></tr></thead>
        <tbody>${out.items.map(s => `<tr style="${s.debt > 0 ? 'background:var(--red-dim);' : ''}"><td><strong>${esc(s.name)}</strong>${s.birthday ? ' 🎂' : ''}${s.status === 'frozen' ? ' <span class="badge bb">MUZLATILGAN</span>' : ''}</td>
          <td style="font-size:11px;"><a href="tel:${esc(s.phone)}" style="color:inherit;">${esc(s.phone)}</a></td><td style="font-size:11px;">${esc(s.parentPhone || '—')}</td>
          <td>${esc(s.group)}</td><td>${rate(s.attendance)}</td><td>${s.monthly_fee ? fmt(s.monthly_fee) : '—'}</td>
          <td style="font-weight:700;color:${s.debt > 0 ? 'var(--red)' : 'var(--green)'};white-space:nowrap;">${s.debt > 0 ? fmt(s.debt) : "yo'q"}</td></tr>`).join('')
          || `<tr><td colspan="7">${box("// O'quvchi topilmadi")}</td></tr>`}</tbody></table></div></div></div>`;
    } catch (e) { el.innerHTML = errorBox(e.message, 'studRender()'); }
  }

  // ───────────────────────── AI yordamchi (admin / menejer) ─────────────────────────
  const AI_QUICK = ['Bugun nechta dars va davomat qanday?', 'Nechta qarzdor bor va jami qarz qancha?', "Qaysi fanga eng ko'p o'quvchi kutmoqda?",
    "Yangi o'quvchini qanday qo'shaman?", "Chegirmani qanday qo'yaman?", "O'qituvchi oyligi qanday hisoblanadi?"];
  function aiRender() {
    const pg = document.getElementById('aicenterpg'); if (!pg) return;
    pg.innerHTML = `<div class="ph"><h2>AI YORDAMCHI</h2><p>// Markaz holati bo'yicha savol bering yoki tizimdan foydalanishni so'rang</p></div>
      <div class="card"><div class="cb">
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">${AI_QUICK.map(q => `<button class="btn btn-sm" onclick="aiAsk(this.textContent)">${esc(q)}</button>`).join('')}</div>
        <div style="display:flex;gap:8px;"><input class="form-control" id="aiQ" placeholder="Savolingizni yozing..." onkeydown="if(event.key==='Enter'){aiAsk(this.value)}">
          <button class="btn btn-cyan" onclick="aiAsk(document.getElementById('aiQ').value)"><i class="fas fa-paper-plane"></i></button></div>
        <div id="aiAnswer" style="margin-top:14px;white-space:pre-wrap;font-size:13px;line-height:1.6;"></div>
        <div style="font-size:10px;color:var(--text3);margin-top:10px;font-family:'JetBrains Mono',monospace;">// AI'ga faqat umumiy raqamlar yuboriladi — ism va telefonlar yuborilmaydi</div>
      </div></div>`;
  }
  async function aiAsk(question) {
    question = String(question || '').trim(); if (!question) return;
    const el = document.getElementById('aiAnswer');
    el.innerHTML = `<div style="color:var(--text3);margin-bottom:6px;">❓ ${esc(question)}</div>` + loading();
    try {
      const out = await schApi('/ai', { method: 'POST', body: JSON.stringify({ question }) });
      el.innerHTML = `<div style="color:var(--text3);margin-bottom:6px;">❓ ${esc(question)}</div>${esc(out.answer)}`;
    } catch (e) { el.innerHTML = `<div style="color:var(--red);">❌ ${esc(e.message)}</div>`; }
  }

  // ───────────────────────── Profilni tahrirlash, qo'shimcha kurs ─────────────────────────
  function crmEditProfile(id) {
    const s = (window.__crmProfile || {}).student; if (!s || s.id !== id) return;
    openGlobalModal(`<div class="modal-title"><i class="fas fa-user-pen"></i> ${esc(s.name)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:150px;">${label('TELEFON')}<input class="form-control" id="epPhone" value="${esc(s.phone)}"></div>
        <div class="form-group" style="flex:1;min-width:150px;">${label('OTA-ONA TELEFONI')}<input class="form-control" id="epParent" value="${esc(s.parentPhone)}"></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:0 0 160px;">${label("TUG'ILGAN SANA")}<input type="date" class="form-control" id="epBirth" max="${today()}" value="${esc(s.birthDate)}"></div>
        <div class="form-group" style="flex:1;min-width:180px;">${label('MANZIL')}<input class="form-control" id="epAddress" maxlength="200" value="${esc(s.address)}"></div>
      </div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="crmHistory(${id})">Orqaga</button>
        <button class="btn btn-cyan" style="flex:1;" onclick="crmSaveProfile(${id})"><i class="fas fa-check"></i> Saqlash</button></div>`);
  }
  async function crmSaveProfile(id) {
    const v = (x) => document.getElementById(x).value.trim();
    try {
      await crmApi(`/students/${id}/profile`, { method: 'POST', body: JSON.stringify({ phone: v('epPhone'), parentPhone: v('epParent'), birthDate: v('epBirth'), address: v('epAddress') }) });
      showToast('✅ Saqlandi'); await loadData(); crmHistory(id); crmLoad();
    } catch (e) { showToast('❌ ' + e.message); }
  }
  function crmOpenCourse(id) {
    const s = (window.__crmProfile || {}).student; if (!s || s.id !== id) return;
    openGlobalModal(`<div class="modal-title"><i class="fas fa-plus"></i> Qo'shimcha kurs: ${esc(s.name)}</div>
      <p style="font-size:12px;color:var(--text2);margin-bottom:10px;">Asosiy guruh (${esc(s.group)}) o'zgarmaydi — o'quvchi yangi guruh darslariga ham qatnashadi.</p>
      <div class="form-group">${label('GURUH')}${groupSelect('coGroup', '')}</div>
      ${s.extraGroups.length ? `<div style="font-size:12px;margin-bottom:10px;">Hozirgi qo'shimcha kurslar: ${s.extraGroups.map(g => `<button class="btn btn-xs" title="Olib tashlash" onclick="crmSaveCourse(${id},'remove','${esc(g).replace(/'/g, "\\'")}')">${esc(g)} ✕</button>`).join(' ')}</div>` : ''}
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="crmHistory(${id})">Orqaga</button>
        <button class="btn btn-success" style="flex:1;" onclick="crmSaveCourse(${id},'add')"><i class="fas fa-check"></i> Qo'shish</button></div>`);
  }
  async function crmSaveCourse(id, action, group) {
    group = group || document.getElementById('coGroup').value.trim();
    if (!group) { showToast('❗ Guruhni kiriting'); return; }
    try {
      await crmApi(`/students/${id}/courses`, { method: 'POST', body: JSON.stringify({ group, action }) });
      showToast(action === 'add' ? "✅ Kurs qo'shildi" : '✅ Kursdan chiqarildi'); await loadData(); crmHistory(id);
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Sinov darsi ─────────────────────────
  function leadOpenTrial(id) {
    const l = (window.__leads || []).find(x => x.id === id); if (!l) return;
    openGlobalModal(`<div class="modal-title"><i class="fas fa-flask"></i> Sinov darsi: ${esc(l.name)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:180px;">${label('SANA VA VAQT')}<input type="datetime-local" class="form-control" id="trAt"></div>
        <div class="form-group" style="flex:1;min-width:140px;">${label('QAYSI GURUHDA')}${groupSelect('trGroup', '')}</div>
      </div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal();leadsLoad()">Bekor</button>
        <button class="btn btn-cyan" style="flex:1;" onclick="leadSaveTrial('${esc(id)}')"><i class="fas fa-check"></i> Yozish</button></div>`);
  }
  async function leadSaveTrial(id) {
    try {
      await crmApi(`/leads/${encodeURIComponent(id)}/status`, { method: 'POST', body: JSON.stringify({ status: 'trial',
        trial_at: document.getElementById('trAt').value, trial_group: document.getElementById('trGroup').value.trim() }) });
      closeGlobalModal(); showToast('✅ Sinov darsiga yozildi'); leadsLoad();
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Yangi guruh ochish ─────────────────────────
  async function schCreateGroup() {
    const v = (id) => document.getElementById(id).value.trim();
    const weekdays = [...document.querySelectorAll('.ngDay:checked')].map(x => Number(x.value));
    try {
      await schApi('/groups', { method: 'POST', body: JSON.stringify({ name: v('ngName'), subject: v('ngSubject'), teacher_id: Number(v('ngTeacher')),
        room: v('ngRoom'), weekdays, start: v('ngStart'), end: v('ngEnd') }) });
      showToast('✅ Guruh ochildi va jadvalga qo\'shildi'); await loadData(); schRender();
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Avans / oylik berish ─────────────────────────
  function salOpenPayout(tid) {
    const r = (window.__salRows || []).find(x => x.teacher_id === tid) || {};
    openGlobalModal(`<div class="modal-title"><i class="fas fa-hand-holding-dollar"></i> ${esc(r.teacher_name)} — ${esc(sal.month)}</div>
      <div style="font-size:12px;margin-bottom:10px;">Hisoblangan: <strong>${fmt(r.amount)}</strong> · Berilgan: ${fmt(r.paid_out)} · Qoldi: <strong>${fmt(r.remaining)}</strong></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:130px;">${label('TURI')}<select class="form-control" id="poKind"><option value="advance">Avans (oldindan)</option><option value="salary">Oylik</option></select></div>
        <div class="form-group" style="flex:1;min-width:130px;">${label("SUMMA (SO'M)")}<input class="form-control" id="poAmount" inputmode="numeric" value="${Math.max(0, r.remaining || 0) || ''}"></div>
        <div class="form-group" style="flex:1;min-width:110px;">${label("TO'LOV TURI")}<select class="form-control" id="poMethod">${Object.entries(METHOD).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
      </div>
      <div class="form-group">${label('IZOH')}<input class="form-control" id="poNote" maxlength="200"></div>
      <div style="font-size:11px;color:var(--text3);margin-bottom:10px;">Kassada "Ish haqi" xarajati sifatida ham yoziladi.</div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-gold" style="flex:1;" onclick="salSavePayout(${tid})"><i class="fas fa-check"></i> Berildi</button></div>`);
  }
  async function salSavePayout(tid) {
    const amount = digits(document.getElementById('poAmount').value);
    if (!Number(amount)) { showToast('❗ Summani kiriting'); return; }
    try {
      await schApi('/salary/payouts', { method: 'POST', body: JSON.stringify({ teacher_id: tid, amount: Number(amount), month: sal.month,
        kind: document.getElementById('poKind').value, method: document.getElementById('poMethod').value, note: document.getElementById('poNote').value.trim() }) });
      closeGlobalModal(); showToast('✅ Yozildi'); salRender();
    } catch (e) { showToast('❌ ' + e.message); }
  }

  // ───────────────────────── Uy vazifasi bahosi (ustoz qo'yadi, bajarmagan bo'lsa ham) ─────────────────────────
  function hwGradeBadge(hwId) {
    const gr = (DB.homeworkGrades || []).find(x => x.homeworkId === hwId && String(x.studentId) === String(curUser && curUser.id));
    return gr ? `<div style="margin-top:6px;"><span class="badge ${gr.grade >= 4 ? 'gr' : gr.grade >= 3 ? 'bg' : 'rr'}">Baho: ${esc(gr.grade)}</span>${gr.comment ? ` <span style="font-size:11px;color:var(--text2);">${esc(gr.comment)}</span>` : ''}</div>` : '';
  }
  function hwOpenGrades(hwId) {
    const hw = (DB.homeworks || []).find(h => h.id === hwId); if (!hw) return;
    const targets = hw.targetType === 'student' ? DB.students.filter(s => s.id === hw.targetStudentId) : DB.students.filter(s => hwIsForStudent(hw, s));
    const done = (sid) => (DB.homeworkSubmissions || []).some(x => x.homeworkId === hwId && x.studentId === sid);
    const cur = (sid) => (DB.homeworkGrades || []).find(x => x.homeworkId === hwId && String(x.studentId) === String(sid)) || {};
    openGlobalModal(`<div class="modal-title"><i class="fas fa-star"></i> Baholash: ${esc(hw.title)}</div>
      <div style="font-size:11px;color:var(--text3);margin-bottom:8px;">Muddat: ${esc((hw.due || '—').replace('T', ' '))}. Bajarmagan o'quvchiga ham baho qo'yishingiz mumkin.</div>
      <div style="max-height:55vh;overflow:auto;"><table style="width:100%;"><tbody>${targets.map(s => `<tr>
        <td style="padding:6px;"><strong>${esc(s.name)}</strong><br><span style="font-size:10px;color:${done(s.id) ? 'var(--green)' : 'var(--red)'};">${done(s.id) ? 'Bajardi' : 'Bajarmadi'}</span></td>
        <td style="padding:6px;"><select class="form-control hwGrade" data-sid="${s.id}" style="width:80px;"><option value="">—</option>${[5, 4, 3, 2].map(n => `<option ${String(cur(s.id).grade) === String(n) ? 'selected' : ''}>${n}</option>`).join('')}</select></td>
        <td style="padding:6px;"><input class="form-control hwComment" data-sid="${s.id}" placeholder="Izoh" value="${esc(cur(s.id).comment || '')}"></td></tr>`).join('')
        || `<tr><td>${box("// O'quvchi yo'q")}</td></tr>`}</tbody></table></div>
      <div style="display:flex;gap:8px;margin-top:10px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-gold" style="flex:1;" onclick="hwSaveGrades('${esc(hwId)}')"><i class="fas fa-check"></i> Saqlash</button></div>`);
  }
  function hwSaveGrades(hwId) {
    DB.homeworkGrades = (DB.homeworkGrades || []).filter(x => x.homeworkId !== hwId);
    document.querySelectorAll('.hwGrade').forEach(sel => {
      if (!sel.value) return;
      const sid = Number(sel.dataset.sid);
      const comment = (document.querySelector(`.hwComment[data-sid="${sid}"]`) || {}).value || '';
      DB.homeworkGrades.push({ homeworkId: hwId, studentId: sid, grade: Number(sel.value), comment: comment.trim().slice(0, 200), teacherId: curUser.id, gradedAt: Date.now() });
    });
    saveData(); closeGlobalModal(); showToast('✅ Baholar saqlandi');
    if (typeof renderHwTeacherList === 'function') renderHwTeacherList();
  }

  // ───────────────────────── Ta'lim yangiliklari (RSS) ─────────────────────────
  const news = { all: false };
  async function eduNewsRender() {
    const el = document.getElementById('eduNews'); if (!el) return;
    el.innerHTML = `<div class="card" style="margin-bottom:14px;"><div class="ch" style="flex-wrap:wrap;gap:8px;"><h4>📰 TA'LIM YANGILIKLARI</h4>
      <label style="font-size:12px;display:flex;align-items:center;gap:6px;"><input type="checkbox" ${news.all ? 'checked' : ''} onchange="eduNewsSet(this.checked)"> Barcha yangiliklar</label></div>
      <div class="cb" id="eduNewsBody">${loading()}</div></div>`;
    try {
      const out = await schApi('/news?' + qs({ all: news.all ? 1 : '' }));
      document.getElementById('eduNewsBody').innerHTML = (out.items.map(n => `<div class="fin-line" style="align-items:flex-start;">
          <span><a href="${esc(n.link)}" target="_blank" rel="noopener noreferrer" style="color:var(--cyan);font-weight:600;">${esc(n.title)}</a>
          ${n.summary ? `<br><span style="font-size:11px;color:var(--text2);">${esc(n.summary.slice(0, 160))}</span>` : ''}</span>
          <span style="font-size:10px;color:var(--text3);white-space:nowrap;">${esc(n.source)}</span></div>`).join('')
        || box("// Hozircha ta'limga oid yangilik yo'q")) +
        `<div style="font-size:10px;color:var(--text3);margin-top:8px;">// Manbalar: ${out.sources.map(esc).join(', ') || '—'} · har 5 daqiqada yangilanadi</div>`;
    } catch (e) { document.getElementById('eduNewsBody').innerHTML = errorBox(e.message, 'eduNewsRender()'); }
  }
  function eduNewsSet(all) { news.all = all; eduNewsRender(); }

  const css = document.createElement('style');
  css.textContent = `
    .fin-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; margin-bottom:14px; }
    .fin-line { display:flex; justify-content:space-between; gap:10px; padding:6px 0; border-bottom:1px solid var(--bor2); font-size:12px; }
    #finpg table td, #finpg table th, #myfinpg table td, #myfinpg table th, #crmpg table td, #crmpg table th, #schedpg td, #attpg td, #attpg th, #salpg td, #salpg th, #myattpg td, #mystudpg td, #mystudpg th { padding:8px 10px; }
    @media (max-width:600px) { #finpg .tab-btn, #crmpg .tab-btn { flex:1 1 30%; } }`;
  document.head.appendChild(css);

  Object.assign(window, {
    finRender, finRenderMy, finTab, finApplyRange, finQuickRange, finLoadTab, finSetFilter, finPage, finOpenPayment,
    finFilterSelect, finSubmitPayment, finShowReceipt, finPrintReceipt, finVoid, finOpenExpense, finSubmitExpense,
    finFeeSearch, finOpenFee, finSubmitFee, finAuditPage, finExport, finApplyRoleNav,
    crmRender, crmSet, crmPage, crmLoad, crmOpenAction, crmSubmitAction, crmOpenCreate, crmSubmitCreate, crmHistory,
    schRender, schAdd, schRemove, attRender, attPick, attSetMonth, attLoadSheet, attMark, attAll, attSave, attRenderMy,
    salRender, salSetMonth, salOpenRule, salSaveRule, salRenderMy,
    crmCertificate, leadsLoad, leadsSet, leadAdd, leadStatus, leadEnroll, studRender, studSet, aiRender, aiAsk,
    crmEditProfile, crmSaveProfile, crmOpenCourse, crmSaveCourse, leadOpenTrial, leadSaveTrial, schCreateGroup,
    salOpenPayout, salSavePayout, hwOpenGrades, hwSaveGrades, hwGradeBadge, eduNewsRender, eduNewsSet
  });
})();
