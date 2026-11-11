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
  const isFullAdmin = () => curUser && curUser.role === 'admin' && curUser.level !== 'cashier';

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
    if (isFullAdmin()) tabs.push(['audit', 'Audit log']);
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
          <td><button class="btn btn-xs btn-success" onclick="finOpenPayment(${d.student_id}, ${d.debt})"><i class="fas fa-cash-register"></i></button></td>
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
      <td>${r.monthly_fee ? fmt(r.monthly_fee) : '<span style="color:var(--text3)">belgilanmagan</span>'}</td><td>${fmt(r.paid)}</td>
      <td style="font-weight:700;color:${r.debt > 0 ? 'var(--red)' : 'var(--green)'};">${r.debt > 0 ? fmt(r.debt) : r.debt < 0 ? 'avans ' + fmt(-r.debt) : '0'}</td>
      <td style="white-space:nowrap;">${isFullAdmin() ? `<button class="btn btn-xs btn-cyan" onclick="finOpenFee(${r.student_id})"><i class="fas fa-pen"></i> Tarif</button>` : ''}
        <button class="btn btn-xs btn-success" onclick="finOpenPayment(${r.student_id}, ${Math.max(0, r.debt) || ''})"><i class="fas fa-cash-register"></i></button></td>
    </tr>`).join('') || `<tr><td colspan="6">${box("// O'quvchi topilmadi")}</td></tr>`;
  }
  async function finOpenFee(studentId) {
    const row = (window.__finFees || []).find(r => r.student_id === studentId) || {};
    let history = [];
    try { history = (await api('/fees?student_id=' + studentId)).history; } catch (e) { showToast('❌ ' + e.message); return; }
    openGlobalModal(`
      <div class="modal-title"><i class="fas fa-tags"></i> Oylik tarif: ${esc(row.student_name)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <div class="form-group" style="flex:1;min-width:150px;">${label("OYLIK SUMMA (SO'M)")}<input class="form-control" id="ffFee" inputmode="numeric" value="${row.monthly_fee || ''}"></div>
        <div class="form-group" style="flex:1;min-width:140px;">${label('QAYSI OYDAN')}<input type="month" class="form-control" id="ffFrom" value="${thisMonth()}"></div>
      </div>
      <div style="font-size:11px;color:var(--text3);margin-bottom:10px;">0 kiritilsa — shu oydan boshlab hisoblash to'xtaydi (masalan, o'quvchi ketganda). Eski tariflar tarixda qoladi.</div>
      ${history.length ? `<div style="font-size:11px;margin-bottom:10px;max-height:120px;overflow:auto;">${history.map(h => `<div class="fin-line"><span>${esc(h.effective_from)} dan</span><span>${fmt(h.monthly_fee)} · ${esc(h.created_by_name)}</span></div>`).join('')}</div>` : ''}
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-cyan" style="flex:1;" onclick="finSubmitFee(${studentId})"><i class="fas fa-check"></i> Saqlash</button></div>`);
  }
  async function finSubmitFee(studentId) {
    const fee = digits(document.getElementById('ffFee').value);
    if (fee === '') { showToast('❗ Summani kiriting'); return; }
    try {
      await api('/fees', { method: 'POST', body: JSON.stringify({ student_id: studentId, monthly_fee: Number(fee), effective_from: document.getElementById('ffFrom').value }) });
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

  // Kassir faqat moliya, profil va sozlamalarni ko'radi (server ham shunday cheklaydi).
  function finApplyCashierNav(isCashier = true) {
    document.querySelectorAll('#aNav .nav-item').forEach(el => {
      const click = el.getAttribute('onclick') || '';
      const keep = /finpg|tapg|settpg|doLogout/.test(click);
      el.style.display = isCashier && !keep ? 'none' : '';
    });
  }

  // ══════════════════════════════════════════════════
  // CRM: o'quvchi hayot sikli (faqat admin; kassir faqat o'qiy oladi)
  // ══════════════════════════════════════════════════
  const crmApi = (path, opts) => api(path, opts, '/api/crm');
  const STATUS = { active: ['Faol', 'gr'], frozen: ['Muzlatilgan', 'bb'], graduated: ['Bitirgan', 'bg'], left: ['Ketgan', 'rr'] };
  const statusTag = (s) => `<span class="badge ${(STATUS[s] || STATUS.active)[1]}">${(STATUS[s] || STATUS.active)[0].toUpperCase()}</span>`;
  const EVENT = { enrolled: 'Qabul qilindi', group_changed: "Guruh o'zgardi", status_changed: "Holat o'zgardi" };
  const crm = { status: 'active', group: '', q: '', page: 1, groups: [] };

  async function crmRender() {
    const pg = document.getElementById('crmpg'); if (!pg) return;
    const tabs = [['active', 'Faol'], ['frozen', 'Muzlatilgan'], ['graduated', 'Bitiruvchilar arxivi'], ['left', 'Ketganlar'], ['all', 'Hammasi']];
    pg.innerHTML = `
      <div class="ph"><h2>O'QUVCHILAR (CRM)</h2><p>// Qabul, guruh, muzlatish, arxiv va o'quvchi tarixi</p></div>
      <div id="crmSummary" class="fin-grid">${loading()}</div>
      <div class="card" style="margin-bottom:12px;"><div class="cb" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
        <input class="form-control" style="width:200px;" placeholder="Ism, telefon yoki guruh" value="${esc(crm.q)}" onkeydown="if(event.key==='Enter'){crmSet('q',this.value)}">
        <select class="form-control" style="width:140px;" id="crmGroupSel" onchange="crmSet('group',this.value)"><option value="">Barcha guruhlar</option></select>
        <span style="flex:1"></span>
        ${isFullAdmin() ? `<button class="btn btn-success btn-sm" onclick="crmOpenCreate()"><i class="fas fa-user-plus"></i> Yangi o'quvchi</button>` : ''}
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
    body.innerHTML = loading();
    try {
      const out = await crmApi('/students?' + qs({ status: crm.status, group: crm.group, q: crm.q, page: crm.page, page_size: 25 }));
      const admin = isFullAdmin();
      body.innerHTML = `<div class="card"><div class="cb" style="padding:0;"><div class="tw"><table>
        <thead><tr><th>O'quvchi</th><th>Telefon</th><th>Guruh</th><th>Holat</th><th>Oylik</th><th>Qarz</th><th></th></tr></thead>
        <tbody>${out.items.map(s => `<tr>
          <td><strong>${esc(s.name)}</strong><br><span style="font-size:10px;color:var(--text3);font-family:'JetBrains Mono',monospace;">ID:${s.id}</span></td>
          <td style="font-size:11px;">${esc(s.phone)}${s.parentPhone ? `<br><span style="color:var(--text3);">ota-ona: ${esc(s.parentPhone)}</span>` : ''}</td>
          <td>${esc(s.group)}</td><td>${statusTag(s.status)}</td>
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
      <div class="form-group">${label("PAROL (bo'sh qolsa avtomatik)")}<input class="form-control" id="ccPass" autocomplete="new-password"></div>
      <div style="display:flex;gap:8px;"><button class="btn" style="flex:1;" onclick="closeGlobalModal()">Bekor</button>
        <button class="btn btn-success" style="flex:1;" id="ccSubmit" onclick="crmSubmitCreate()"><i class="fas fa-check"></i> Qo'shish</button></div>`);
  }
  async function crmSubmitCreate() {
    const v = (id) => document.getElementById(id).value.trim();
    const fee = digits(v('ccFee'));
    const body = { firstName: v('ccFirst'), lastName: v('ccLast'), phone: v('ccPhone'), parentPhone: v('ccParent'), group: v('ccGroup'),
      start_date: v('ccStart'), password: document.getElementById('ccPass').value, monthly_fee: fee === '' ? null : Number(fee) };
    if (!body.firstName || !body.lastName || !body.phone || !body.group) { showToast("❗ Ism, familiya, telefon va guruh majburiy"); return; }
    const btn = document.getElementById('ccSubmit'); btn.disabled = true;
    try {
      const out = await crmApi('/students', { method: 'POST', body: JSON.stringify(body) });
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
        <div style="font-size:12px;margin-bottom:10px;">${statusTag(s.status)} · ${esc(s.group)} · ${esc(s.phone)}<br>
          Oylik: ${s.monthly_fee ? fmt(s.monthly_fee) : '—'} · To'langan: ${fmt(s.paid)} · <strong style="color:${s.debt > 0 ? 'var(--red)' : 'var(--green)'}">${s.debt > 0 ? 'Qarz ' + fmt(s.debt) : s.debt < 0 ? 'Avans ' + fmt(-s.debt) : "Qarz yo'q"}</strong></div>
        <div style="max-height:50vh;overflow:auto;">
          <h4 style="font-size:12px;margin:8px 0;">TARIX</h4>${out.events.map(evLine).join('') || `<div style="color:var(--text3);font-size:12px;">// Hodisa yo'q (CRM'dan oldin qo'shilgan)</div>`}
          <h4 style="font-size:12px;margin:12px 0 8px;">TO'LOVLAR</h4>${out.payments.map(p => `<div class="fin-line"><span>${esc(p.day)} · ${esc(p.receipt_no)} · ${esc(p.period || '')}</span><span>${fmt(p.amount)} ${p.status === 'void' ? statusBadge('void') : ''}</span></div>`).join('') || `<div style="color:var(--text3);font-size:12px;">// To'lov yo'q</div>`}
          <h4 style="font-size:12px;margin:12px 0 8px;">TARIFLAR</h4>${out.fees.map(f => `<div class="fin-line"><span>${esc(f.effective_from)} dan</span><span>${fmt(f.monthly_fee)}</span></div>`).join('') || `<div style="color:var(--text3);font-size:12px;">// Tarif belgilanmagan</div>`}
        </div>
        <button class="btn" style="width:100%;margin-top:12px;" onclick="closeGlobalModal()">Yopish</button>`);
    } catch (e) { showToast('❌ ' + e.message); }
  }

  const css = document.createElement('style');
  css.textContent = `
    .fin-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; margin-bottom:14px; }
    .fin-line { display:flex; justify-content:space-between; gap:10px; padding:6px 0; border-bottom:1px solid var(--bor2); font-size:12px; }
    #finpg table td, #finpg table th, #myfinpg table td, #myfinpg table th, #crmpg table td, #crmpg table th { padding:8px 10px; }
    @media (max-width:600px) { #finpg .tab-btn, #crmpg .tab-btn { flex:1 1 30%; } }`;
  document.head.appendChild(css);

  Object.assign(window, {
    finRender, finRenderMy, finTab, finApplyRange, finQuickRange, finLoadTab, finSetFilter, finPage, finOpenPayment,
    finFilterSelect, finSubmitPayment, finShowReceipt, finPrintReceipt, finVoid, finOpenExpense, finSubmitExpense,
    finFeeSearch, finOpenFee, finSubmitFee, finAuditPage, finExport, finApplyCashierNav,
    crmRender, crmSet, crmPage, crmLoad, crmOpenAction, crmSubmitAction, crmOpenCreate, crmSubmitCreate, crmHistory
  });
})();
