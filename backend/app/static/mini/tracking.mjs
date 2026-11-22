const kinds = {deposit:"واریز بانکی",withdraw:"برداشت",crypto:"واریز رمزارز",tx:"تراکنش کیف پول",game:"بازی",card:"کارت",user:"کاربر"};
const statuses = {LOBBY:"در انتظار شروع",RUNNING:"در حال اجرا",ENDED:"پایان‌یافته",AWAITING_RECEIPT:"در انتظار رسید",PENDING_REVIEW:"در انتظار بررسی",PENDING:"در انتظار بررسی",APPROVED:"تأیید شده",REJECTED:"رد شده",PAID:"پرداخت ثبت شده",WAITING_PAYMENT:"در انتظار پرداخت",CONFIRMING:"در انتظار تأیید شبکه",CREDITED:"اعتبار ثبت شده",EXPIRED:"منقضی شده",NEEDS_REVIEW:"نیازمند بررسی",CANCELLED:"لغو شده",RECORDED:"ثبت شده"};
const escape = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const number = v => Number(v).toLocaleString("fa-IR");
const dateText = v => v ? new Date(v).toLocaleString("fa-IR") : "هنوز ثبت نشده";
const options = obj => Object.entries(obj).map(([v,t]) => `<option value="${v}">${t}</option>`).join("");

export function initTracking({apiFetch, getAccount}) {
  const dialog = document.createElement("dialog");
  dialog.id = "trackingCenter";
  dialog.dir = "rtl";
  dialog.setAttribute("aria-labelledby","trackingTitle");
  dialog.innerHTML = `
    <header><div class="tracking-brand"><span class="tracking-brand-mark" aria-hidden="true">↗</span><div><h2 id="trackingTitle">مرکز پیگیری</h2><p>بازی‌ها و امور مالی شما</p></div></div><button type="button" data-close aria-label="بستن پیگیری">×</button></header>
    <form id="trackingForm">
      <div class="tracking-search-heading"><h3>پرونده‌ات را پیدا کن</h3><label for="trackingQuery">کد رسید، شماره بازی یا هش تراکنش را وارد کن.</label></div>
      <div class="tracking-search"><input id="trackingQuery" maxlength="180" autocomplete="off" placeholder="کد رسید، بازی، بازی/کارت یا هش تراکنش" /><button type="button" data-paste>چسباندن</button><button class="tracking-primary" type="submit">پیگیری</button></div>
      <details><summary>فیلترهای جست‌وجو</summary><div class="tracking-filters">
        <label>نوع<select id="trackingKind"><option value="">همه</option>${options(kinds)}</select></label>
        <label>وضعیت<select id="trackingStatus"><option value="">همه</option>${options(statuses)}</select></label>
        <label>از تاریخ میلادی<input id="trackingSince" type="date" /></label>
        <label>تا تاریخ میلادی<input id="trackingUntil" type="date" /></label>
      </div></details>
    </form>
    <div id="trackingRecent" aria-label="جست‌وجوهای اخیر"></div>
    <p id="trackingFeedback" hidden role="status" aria-live="polite"></p>
    <div id="trackingBody"></div>
    <footer><span id="trackingUpdated"></span><button type="button" data-refresh>به‌روزرسانی</button></footer>`;
  document.body.append(dialog);
  const el = id => dialog.querySelector("#"+id);
  let account = 0, serial = 0, last = null, offset = 0, filters = {}, history = {}, detail = null;
  const feedback = text => { el("trackingFeedback").textContent=text; el("trackingFeedback").hidden=!text; };
  function recent() {
    try { return JSON.parse(sessionStorage.getItem("tracking_recent:"+account) || "[]").filter(v=>typeof v==="string").slice(0,6); }
    catch { return []; }
  }
  function renderRecent() {
    el("trackingRecent").innerHTML = recent().map(v=>`<button type="button" data-recent="${escape(v)}">${escape(v)}</button>`).join("");
  }
  function remember(q) {
    if (!q) return;
    try { sessionStorage.setItem("tracking_recent:"+account, JSON.stringify([q,...recent().filter(v=>v!==q)].slice(0,6))); } catch {}
    renderRecent();
  }
  function reset() {
    serial++;
    last=null;detail=null;history={};filters={};offset=0;
    el("trackingBody").replaceChildren();el("trackingUpdated").textContent="";
    el("trackingRecent").replaceChildren();feedback("");
    el("trackingForm").reset();
    el("trackingForm").hidden=false;el("trackingRecent").hidden=false;
  }
  function open() {
    const uid = Number(getAccount());
    if(account!==uid) { reset();account=uid; }
    if(!dialog.open) dialog.showModal();
    renderRecent();
    el("trackingQuery").focus();
    if(!uid)feedback("ابتدا از داخل ربات وارد حساب خود شوید.");
  }
  function close() { serial++;dialog.close(); }
  function tile(row) {
    return `<button type="button" class="tracking-result" data-kind="${escape(row.kind)}" data-id="${Number(row.id)}"><span><strong>${escape(row.title)}</strong><bdi>${escape(row.code)}</bdi></span><span class="tracking-state" data-status="${escape(row.status)}">${escape(row.status_label)}</span>${row.amount==null?"":`<strong class="tracking-amount">${number(row.amount)} <small>تومان</small></strong>`}<small>${escape(dateText(row.created_at))}</small></button>`;
  }
  function pagination(total, start, step, target) {
    return `<nav class="tracking-pages" aria-label="صفحه‌بندی"><button type="button" data-page="${target}" data-offset="${Math.max(0,start-step)}" ${start===0?"disabled":""}>قبلی</button><span>${number(total)} مورد · صفحه ${number(Math.floor(start/step)+1)}</span><button type="button" data-page="${target}" data-offset="${start+step}" ${start+step>=total?"disabled":""}>بعدی</button></nav>`;
  }
  async function request(path, render) {
    const mine=++serial, uid=account;
    if(!uid || uid!==Number(getAccount())) {reset();feedback("دوباره وارد حساب خود شوید.");return;}
    feedback("در حال دریافت اطلاعات…");dialog.setAttribute("aria-busy","true");
    try {
      const result=await apiFetch(path);
      if(mine!==serial || uid!==Number(getAccount()) || !dialog.open)return;
      render(result);
      el("trackingUpdated").textContent="به‌روزرسانی "+dateText(result.fetched_at);
      feedback("");
    } catch(error) {
      if(mine===serial && uid===Number(getAccount())) {
        feedback(error?.message || "دریافت اطلاعات انجام نشد؛ دوباره تلاش کنید.");
        el("trackingUpdated").textContent="اطلاعات تازه دریافت نشد.";
      }
    } finally {if(mine===serial)dialog.removeAttribute("aria-busy");}
  }
  async function search(start=0, readForm=false) {
    if(readForm) {
      if(el("trackingQuery").value.trim())history={};
      filters={q:el("trackingQuery").value.trim(),kind:el("trackingKind").value,status:el("trackingStatus").value,since:el("trackingSince").value,until:el("trackingUntil").value};
    }
    offset=start;last={type:"search",start};detail=null;
    const query=new URLSearchParams({...filters,...history,offset:start,limit:20});
    for(const [k,v] of [...query])if(!v)query.delete(k);
    await request("/mini-api/tracking/search?"+query, result=>{
      el("trackingForm").hidden=false;el("trackingRecent").hidden=false;
      el("trackingBody").innerHTML=`<div class="tracking-results-heading"><h3>${history.owner?"سوابق کاربر":history.game?"مرتبط با این بازی":"نتایج جست‌وجو"}</h3><span>${number(result.total)} مورد</span></div>${history.owner||history.game?'<button type="button" data-clear-scope>جست‌وجو در همهٔ موارد مجاز</button>':""}<div class="tracking-results">${result.items.map(tile).join("") || '<p class="tracking-empty">مورد قابل‌دسترسی پیدا نشد. کد و فیلترها را بررسی کنید.</p>'}</div>${pagination(result.total,start,20,"search")}`;
      remember(filters.q);
    });
  }
  async function show(kind,id,start=0) {
    last={type:"detail",kind,id,start};
    await request(`/mini-api/tracking/${kind}/${id}?offset=${start}`, row=>{
      detail=row;
      el("trackingForm").hidden=true;el("trackingRecent").hidden=true;
      if(start===0)dialog.scrollTop=0;
      const grid=row.card?`<div class="tracking-grid" style="--columns:${row.card.columns}" dir="ltr">${row.card.numbers.map(n=>`<span class="${n===0?"blank":row.called.includes(n)?"hit":""}">${n?number(n):""}</span>`).join("")}</div><p>${number(row.card.matches)} عدد تطبیق دارد. نتیجهٔ برد از رویداد ثبت‌شدهٔ بازی پیگیری می‌شود.</p>`:"";
      el("trackingBody").innerHTML=`
        <button class="tracking-back" type="button" data-back>→ بازگشت به جست‌وجو</button>
        <section class="tracking-summary"><div class="tracking-summary-heading"><span class="tracking-record-label">پرونده</span><h3>${escape(row.title)}</h3><bdi>${escape(row.code)}</bdi></div><span class="tracking-state" data-status="${escape(row.status)}">${escape(row.status_label)}</span>${row.amount==null?"":`<strong class="tracking-amount">${number(row.amount)} <small>تومان</small></strong>`}</section>
        <div class="tracking-actions" aria-label="عملیات پرونده"><button type="button" data-copy="code">کپی کد</button><button type="button" data-copy="summary">کپی خلاصه</button><button type="button" data-copy="link">کپی لینک پرونده</button>${row.history?'<button type="button" data-history>سوابق مرتبط</button>':""}</div>
        ${grid}${row.wins?`<section><h3>رویدادهای برد این کارت</h3>${row.wins.map(w=>`<p>${escape(w.label)} · ${w.amount==null?"مبلغ قابل تأیید نیست":number(w.amount)+" تومان"} · ${escape(dateText(w.at))}</p>`).join("") || "<p>بردی برای این کارت ثبت نشده است.</p>"}<p>وضعیت ثبت اعتبار را در تراکنش‌های مرتبط بازی بررسی کنید.</p></section>`:""}
        <div class="tracking-columns"><section class="tracking-info-panel"><h3>جزئیات پرونده</h3><dl>${row.fields.map(f=>`<div><dt>${escape(f.label)}</dt><dd>${escape(f.value)}</dd></div>`).join("")}</dl></section>
        <section class="tracking-timeline-panel"><h3>روند رسیدگی</h3><ol class="tracking-timeline">${row.timeline.map(t=>`<li><strong>${escape(t.label)}</strong><time>${escape(dateText(t.at))}</time></li>`).join("")}</ol></section></div>
        ${row.called?`<details><summary>اعداد اعلام‌شده (${number(row.called.length)})</summary><p class="tracking-draws">${row.called.map(number).join("، ") || "هنوز ثبت نشده"}</p></details>`:""}
        ${row.links.length?`<section><h3>پرونده‌های مرتبط</h3><div class="tracking-results">${row.links.map(tile).join("")}</div></section>`:""}
        ${row.audit.total?`<details open><summary>سابقهٔ اقدامات مدیریتی</summary>${row.audit.items.map(v=>`<p>${escape(v.action)} · مدیر ${number(v.actor)}<br>${escape(dateText(v.at))}<br>${escape(v.reason)}</p>`).join("")}${pagination(row.audit.total,start,20,"audit")}</details>`:""}`;
    });
  }
  async function refresh() {
    const scroll=dialog.scrollTop;
    if(last?.type==="detail")await show(last.kind,last.id,last.start);
    else await search(last?.start || 0);
    dialog.scrollTop=scroll;
  }
  el("trackingForm").addEventListener("submit",e=>{e.preventDefault();search(0,true);});
  dialog.addEventListener("close",()=>{serial++;dialog.removeAttribute("aria-busy");});
  dialog.addEventListener("click",async e=>{
    const button=e.target.closest("button");if(!button)return;
    try {
      if(button.hasAttribute("data-close"))close();
      else if(button.hasAttribute("data-paste"))el("trackingQuery").value=(await navigator.clipboard.readText()).slice(0,180);
      else if(button.hasAttribute("data-refresh"))await refresh();
      else if(button.dataset.kind)await show(button.dataset.kind,Number(button.dataset.id));
      else if(button.dataset.recent){el("trackingQuery").value=button.dataset.recent;await search(0,true);}
      else if(button.hasAttribute("data-back"))await search(offset);
      else if(button.hasAttribute("data-history")){history=detail.history;filters={};el("trackingForm").reset();await search(0);}
      else if(button.hasAttribute("data-clear-scope")){history={};await search(0,true);}
      else if(button.dataset.page==="search")await search(Number(button.dataset.offset));
      else if(button.dataset.page==="audit")await show(detail.kind,detail.id,Number(button.dataset.offset));
      else if(button.dataset.copy && detail){
        let value=detail.code;
        if(button.dataset.copy==="summary")value=[detail.title,detail.code,detail.status_label,detail.amount==null?"":number(detail.amount)+" تومان"].filter(Boolean).join("\n");
        if(button.dataset.copy==="link"){const url=new URL(location.href);url.hash="track="+detail.kind+"/"+detail.id;value=url.href;}
        await navigator.clipboard.writeText(value);feedback("کپی شد.");
      }
    } catch {feedback("عملیات انجام نشد. دسترسی کلیپ‌بورد را بررسی کنید.");}
  });
  function openLinked() {
    const m=/^#track=(deposit|withdraw|crypto|tx|game|card|user)\/(\d+)$/.exec(location.hash);
    if(m && getAccount()){open();show(m[1],Number(m[2]));}
  }
  window.addEventListener("hashchange",openLinked);
  document.getElementById("trackingBtn").addEventListener("click",open);
  return {openLinked, clear(){reset();account=0;close();}};
}
