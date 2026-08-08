const tg = window.Telegram?.WebApp;
const state = { me:null, catalog:null };

if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.(tg.themeParams.bg_color || '#0f1115');
  tg.setBackgroundColor?.(tg.themeParams.bg_color || '#0f1115');
}

function initData(){ return tg?.initData || ''; }
async function api(path, options={}) {
  const headers = options.headers || {};
  headers['X-Telegram-Init-Data'] = initData();
  const res = await fetch(path, {...options, headers});
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.detail || data.message || 'خطایی رخ داد');
  return data;
}
function toast(msg){const e=document.getElementById('toast');e.textContent=msg;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),2500)}
function money(n){return Number(n||0).toLocaleString('fa-IR')+' تومان'}
function status(s){return ({pending:'⏳ در انتظار بررسی',approved:'✅ تایید شده',rejected:'❌ رد شده'})[s]||s}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}

async function boot(){
  try{
    state.me=await api('/api/me');
    document.getElementById('hello').textContent=`سلام ${state.me.user.first_name||'دوست عزیز'} 👋`;
    showPage('home');
  }catch(e){
    document.getElementById('content').innerHTML=`<div class="empty">⚠️ ${esc(e.message)}<br><small>این صفحه باید از داخل تلگرام باز شود.</small></div>`;
  }
}
async function showPage(page){
  document.querySelectorAll('.bottom-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('nav-'+page)?.classList.add('active');
  const c=document.getElementById('content');
  try{
    if(page==='home') c.innerHTML=homePage();
    if(page==='shop') { if(!state.catalog) state.catalog=await api('/api/catalog'); c.innerHTML=shopPage(); }
    if(page==='orders') { const d=await api('/api/orders'); c.innerHTML=ordersPage(d.orders); }
    if(page==='wallet') { state.me=await api('/api/me'); c.innerHTML=walletPage(); }
    if(page==='profile') { state.me=await api('/api/me'); c.innerHTML=profilePage(); }
  }catch(e){c.innerHTML=`<div class="empty">❌ ${esc(e.message)}</div>`}
}
function homePage(){
 return `<div class="hero"><h1>به ShopVPN خوش آمدی 👋</h1><p>${esc(state.me?.settings?.welcome_text||'سرویس مورد نظرت را انتخاب کن و در چند مرحله سفارش بده.')}</p><button class="primary" onclick="showPage('shop')">🛒 مشاهده فروشگاه</button></div>
 <div class="grid">
  <div class="card"><div>💳</div><h3>کیف پول</h3><p>موجودی فعلی</p><div class="price">${money(state.me?.wallet)}</div></div>
  <div class="card"><div>🤝</div><h3>زیرمجموعه</h3><p>تعداد دعوت‌ها</p><div class="price">${Number(state.me?.referral?.count||0).toLocaleString('fa-IR')}</div></div>
 </div>
 <div class="section-title">دسترسی سریع</div>
 <div class="grid">
  <div class="card" onclick="showPage('orders')"><h3>📦 سفارش‌های من</h3><p>مشاهده سفارش‌ها و کانفیگ‌ها</p></div>
  <div class="card" onclick="openTest()"><h3>🧪 تست رایگان</h3><p>در صورت فعال بودن</p></div>
  <div class="card" onclick="openReferral()"><h3>🤝 دعوت دوستان</h3><p>دریافت اعتبار کیف پول</p></div>
  <div class="card" onclick="openContact()"><h3>📞 پشتیبانی</h3><p>ارتباط مستقیم</p></div>
 </div>`;
}
function shopPage(){
 let html='<div class="section-title">فروشگاه</div>';
 for(const cat of (state.catalog?.categories||[])){
  html+=`<section class="category"><h3 class="category-title">📁 ${esc(cat.name)}</h3><div class="grid">`;
  for(const p of cat.products){
   html+=`<div class="card"><h3>${esc(p.name)}</h3><p>${esc(p.description)}</p><div class="price">${money(p.price)}</div><div class="stock">${p.stock>0?'✅ موجود':'⛔️ ناموجود'} · ${p.duration_days} روز</div><button class="primary" ${p.stock<=0?'disabled':''} onclick="openProduct(${p.id})">مشاهده</button></div>`;
  }
  html+='</div></section>';
 }
 return html||'<div class="empty">محصولی موجود نیست.</div>';
}
async function openProduct(id){
 const p=await api('/api/products/'+id);
 showModal(`<h2>${esc(p.name)}</h2><p>${esc(p.description)}</p><div class="price">${money(p.price)}</div><div class="stock">موجودی: ${p.stock} · مدت: ${p.duration_days} روز</div>
 <div class="form" style="margin-top:14px"><input id="discount" placeholder="کد تخفیف (اختیاری)" /><button class="primary" onclick="buy(${p.id})">ادامه خرید</button></div>`);
}
async function buy(id){
 try{
  const code=document.getElementById('discount')?.value.trim()||null;
  const o=await api('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_id:id,discount_code:code})});
  if(o.status==='approved'){
   showModal(`<h2>🎉 خرید موفق</h2><p>کانفیگ شما آماده است:</p><div class="config">${esc(o.config)}</div><button class="primary" onclick="closeModal()">بستن</button>`);
   tg?.HapticFeedback?.notificationOccurred('success'); return;
  }
  showModal(`<h2>💳 پرداخت</h2><p>${esc(o.after_buy_text||'مبلغ را پرداخت کنید و رسید را ارسال کنید.')}</p><div class="card"><p>شماره کارت</p><b>${esc(o.card_number)}</b><p>به نام</p><b>${esc(o.card_holder)}</b><p>مبلغ</p><div class="price">${money(o.final_price)}</div></div><input type="file" id="receipt" accept="image/*" style="margin-top:12px"><button class="primary" onclick="sendReceipt(${o.order_id})">📤 ارسال رسید</button>`);
 }catch(e){toast(e.message)}
}
async function sendReceipt(id){
 const f=document.getElementById('receipt').files[0];
 if(!f){toast('ابتدا عکس رسید را انتخاب کن');return}
 const fd=new FormData();fd.append('receipt',f);
 try{await api('/api/orders/'+id+'/receipt',{method:'POST',body:fd});showModal(`<h2>✅ رسید ارسال شد</h2><p>پس از بررسی ادمین، کانفیگ برایت ارسال می‌شود.</p><button class="primary" onclick="closeModal();showPage('orders')">متوجه شدم</button>`)}
 catch(e){toast(e.message)}
}
function ordersPage(orders){
 if(!orders.length)return '<div class="empty">هنوز سفارشی ثبت نکرده‌ای.</div>';
 return '<div class="section-title">سفارش‌های من</div>'+orders.map(o=>`<div class="card order"><h3>#${o.id} · ${esc(o.product)}</h3><span class="status">${status(o.status)}</span><p style="margin-top:10px">مبلغ: ${money(o.final_price)}</p>${o.config?`<div class="config">${esc(o.config)}<br><small>انقضا: ${esc(o.expires_at||'---')}</small></div>`:''}</div>`).join('');
}
function walletPage(){
 return `<div class="hero"><div class="muted">موجودی کیف پول</div><div class="balance">${money(state.me.wallet)}</div><p>اعتبار کیف پول در خریدها به صورت خودکار استفاده می‌شود.</p></div><button class="primary" onclick="openTopup()">➕ شارژ کیف پول</button><button class="secondary" onclick="openReferral()">🤝 دریافت اعتبار از دعوت دوستان</button>`;
}
function profilePage(){
 return `<div class="hero"><h2>${esc(state.me.user.first_name||'کاربر')}</h2><p>@${esc(state.me.user.username||'---')} · ${state.me.user.id}</p></div><div class="card"><h3>اطلاعات حساب</h3><p>موجودی: ${money(state.me.wallet)}</p><p>زیرمجموعه‌ها: ${Number(state.me.referral.count||0).toLocaleString('fa-IR')}</p></div>`;
}
function showModal(html){document.getElementById('modal-content').innerHTML=html;document.getElementById('modal').classList.remove('hidden')}
function closeModal(){document.getElementById('modal').classList.add('hidden')}
async function openTopup(){
 showModal(`<h2>➕ شارژ کیف پول</h2><div class="form"><input id="topupAmount" type="number" min="1000" placeholder="مبلغ به تومان"><button class="primary" onclick="createTopup()">ادامه</button></div>`)
}
async function createTopup(){
 try{
  const amount=Number(document.getElementById('topupAmount').value);
  const o=await api('/api/topups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount})});
  showModal(`<h2>💳 پرداخت</h2><p>مبلغ ${money(o.amount)} را واریز کن.</p><div class="card"><b>${esc(o.card_number)}</b><p>${esc(o.card_holder)}</p></div><input type="file" id="topupReceipt" accept="image/*" style="margin-top:12px"><button class="primary" onclick="sendTopupReceipt(${o.topup_id})">📤 ارسال رسید</button>`)
 }catch(e){toast(e.message)}
}
async function sendTopupReceipt(id){
 const f=document.getElementById('topupReceipt').files[0]; if(!f){toast('عکس رسید را انتخاب کن');return}
 const fd=new FormData();fd.append('receipt',f);
 try{await api('/api/topups/'+id+'/receipt',{method:'POST',body:fd});showModal('<h2>✅ ارسال شد</h2><p>درخواست شارژ برای ادمین ارسال شد.</p>')}catch(e){toast(e.message)}
}
async function openReferral(){
 try{const r=await api('/api/referral');showModal(`<h2>🤝 زیرمجموعه‌گیری</h2><p>با دعوت دوستان، ${r.percent}٪ از اولین خرید تاییدشده آن‌ها به کیف پولت اضافه می‌شود.</p><div class="card"><p>لینک دعوت</p><div class="config">${esc(r.link)}</div><p>تعداد: ${r.count} · اعتبار: ${money(r.credit)}</p></div><button class="primary" onclick="copyText('${encodeURIComponent(r.link)}')">📋 کپی لینک</button>`) }catch(e){toast(e.message)}
}
async function copyText(v){await navigator.clipboard?.writeText(decodeURIComponent(v));toast('کپی شد')}
async function openTest(){
 try{const r=await api('/api/test');showModal(`<h2>🧪 کانفیگ تست</h2><div class="config">${esc(r.config)}</div>`)}catch(e){toast(e.message)}
}
function openContact(){
 showModal(`<h2>📞 پشتیبانی</h2><div class="form"><textarea id="contactText" rows="5" placeholder="پیامت را بنویس..."></textarea><button class="primary" onclick="sendContact()">ارسال پیام</button></div>`)
}
async function sendContact(){
 try{await api('/api/contact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:document.getElementById('contactText').value})});showModal('<h2>✅ ارسال شد</h2><p>پیامت برای پشتیبانی ارسال شد.</p>')}catch(e){toast(e.message)}
}
boot();
