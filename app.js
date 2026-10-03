const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
const newId = () => crypto.randomUUID ? crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
let token = sessionStorage.getItem('account_token') || '';
let session = sessionStorage.getItem('chat_session') || newId();
let busy = false, detailVersion = 0;
sessionStorage.setItem('chat_session', session);
const welcome = $('messages').innerHTML;

async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers: {'Content-Type':'application/json', ...(token ? {Authorization:'Bearer '+token} : {})}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || 'Chưa lấy được thông tin. Bạn thử lại nhé.'); error.status=response.status; throw error; }
  return data;
}
function notice(error) { $('notice').textContent = error.message || error; }
function view(name) {
  ['chat','search','reviews'].forEach(key => $(key+'view').hidden=key!==name);
  document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===name));
}
function price(p) {
  const value = Number(p.price);
  if (!(value > 0)) return 'Chưa có giá';
  return new Intl.NumberFormat('vi-VN',{style:'currency',currency:p.currency==='USD'?'USD':'VND',maximumFractionDigits:p.currency==='USD'?2:0}).format(value);
}
function safeUrl(value) { try { const url=new URL(value); return ['https:','http:'].includes(url.protocol) ? url.href : null; } catch { return null; } }
function media(p) {
  const box=document.createElement('div'); box.className='media';
  const missing=()=>{ const label=document.createElement('span'); label.className='missing'; label.textContent='Chưa có ảnh sản phẩm'; box.replaceChildren(label); };
  const url=safeUrl(p.image_url);
  if(url){const img=document.createElement('img'); img.src=url; img.alt=p.name||'Ảnh sản phẩm'; img.loading='lazy'; img.onerror=missing; box.append(img);} else missing();
  // Tiki fills missing images in the background, without blocking the reply.
  if (!url && (p.product_id?.startsWith('tiki_') || p.product_id?.startsWith('amazon_'))) {
    const update=async attempts=>{
      if(!box.isConnected || attempts<=0) return;
      try { const data=await api('/api/product?id='+encodeURIComponent(p.product_id)); const image=safeUrl(data.image_url); if(image){p.image_url=image; const img=document.createElement('img');img.src=image;img.alt=p.name;img.loading='lazy';img.onerror=missing;box.replaceChildren(img);return;} if(!data.enrichment_pending)return; } catch { return; }
      setTimeout(()=>update(attempts-1),1700);
    };
    setTimeout(()=>update(8),1200);
  }
  return box;
}
function button(text, action) { const b=document.createElement('button'); b.type='button'; b.textContent=text; b.onclick=()=>Promise.resolve().then(action).catch(notice); return b; }
function card(p, index, compact=false) {
  const article=document.createElement('article');article.className='card';article.dataset.productId=p.product_id;
  const top=document.createElement('div');top.className='card-top';
  const content=document.createElement('div');content.innerHTML=`${index!==undefined?'<div class="rank">Lựa chọn '+(index+1)+'</div>':''}<h3>${esc(p.name)}</h3><p class="price">${esc(price(p))}</p><div class="meta">${esc(p.source||'')} ${p.brand?' · '+esc(p.brand):''}${Number(p.rating)>0?' · '+esc(p.rating)+'/5':''}</div>`;
  top.append(media(p),content);article.append(top);
  if(p.recommendation_reason){const reason=document.createElement('p');reason.className='reason';reason.textContent=p.recommendation_reason;article.append(reason);}
  const actions=document.createElement('div');actions.className='actions';
  if(!compact) actions.append(button('Chi tiết và đánh giá',()=>details(p.product_id)));
  actions.append(button('Sản phẩm tương tự',async()=>{if($('detail').open)$('detail').close();view('chat');await chat('Tìm sản phẩm tương tự '+p.name,{action:'similar',product_id:p.product_id});}),button('Lưu yêu thích',async()=>{if(!token){$('accountdialog').showModal();$('accountnotice').textContent='Đăng nhập để lưu sản phẩm này.';return;}await api('/api/account/favorite',{product_id:p.product_id});await account();notice('Đã lưu sản phẩm yêu thích.');}));
  const url=safeUrl(p.url);if(url){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Xem nơi bán';actions.append(a);}
  article.append(actions);return article;
}
function userMessage(text){$('welcome')?.remove();const row=document.createElement('div');row.className='message user';const bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=text;row.append(bubble);$('messages').append(row);scroll();return row;}
function scroll(){ $('messages').scrollTop=$('messages').scrollHeight; }
function renderAnswer(data) {
  const row=document.createElement('div');row.className='message assistant';
  let reply=data.message;
  if(/Qwen|FAISS|BPR|Python|công cụ|thuật toán|mô hình/i.test(reply||'')) reply=data.products?.length?'Mình đã tìm được các lựa chọn dưới đây. Bạn muốn xem đánh giá hay so sánh mẫu nào?':'Mình chưa lấy được thông tin lúc này, bạn thử lại nhé.';
  row.innerHTML='<div class="speaker">Trợ lý mua sắm</div><div class="bubble">'+esc(reply)+'</div>';
  if(data.products?.length){const grid=document.createElement('div');grid.className='products';data.products.slice(0,5).forEach((p,i)=>grid.append(card(p,i)));row.append(grid);}
  if(data.type==='reviews') (data.products||[]).forEach(p=>{const heading=document.createElement('h3');heading.textContent='Đánh giá: '+p.name;row.append(heading);renderReviews(row,p.reviews||[],false);});
  if(data.comparison?.length){const wrapper=document.createElement('div');wrapper.className='comparison-wrap';wrapper.innerHTML='<table><thead><tr><th>Sản phẩm</th><th>Giá ghi nhận</th><th>Đánh giá</th><th>Lượt đánh giá</th></tr></thead><tbody>'+data.comparison.map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(price(p))}</td><td>${Number(p.rating)>0?esc(p.rating)+'/5':'Chưa có'}</td><td>${esc(p.review_count||'Chưa có')}</td></tr>`).join('')+'</tbody></table>';row.append(wrapper);}
  if(data.products?.length){const sources=document.createElement('details');sources.innerHTML='<summary>Nguồn thông tin</summary>';for(const p of data.products){const line=document.createElement('p');line.textContent=p.name+' — '+(p.source||'')+' — '+p.product_id;sources.append(line);}row.append(sources);}
  $('messages').append(row);scroll();
}
async function chat(message, extra={}) {
  message=message.trim();if(!message || busy)return;
  busy=true;$('send').disabled=true;$('query').value='';$('notice').textContent='';
  userMessage(message);
  const loading=document.createElement('div');loading.className='message loading';loading.textContent='Mình đang xem các lựa chọn cho bạn…';$('messages').append(loading);scroll();
  try{const data=await api('/api/chat',{message,session_id:session,...extra});loading.remove();renderAnswer(data);}catch(error){loading.textContent=error.message;notice(error);}finally{busy=false;$('send').disabled=false;$('query').focus();}
}
function renderReviews(target, reviews, pending) {
  if(!reviews.length){const text=document.createElement('p');text.className='muted';text.textContent=pending?'Đánh giá đang được tải, bạn đợi một chút nhé.':'Chưa tìm được đánh giá của người mua cho sản phẩm này.';target.append(text);return;}
  for(const r of reviews){const item=document.createElement('article');item.className='review';const rating=Number(r.rating)>0?`${r.rating}/5`:'Chưa có điểm';item.innerHTML=`<strong>${esc(r.title||'Nhận xét của người mua')}</strong><p>${esc(r.text)}</p><small>${esc(rating)} · ${esc(r.source||'')} · Mã đánh giá ${esc(r.review_id||'chưa có')}</small>`;target.append(item);}
}
async function details(id) {
  const version=++detailVersion;
  if(!$('detail').open)$('detail').showModal();
  $('detailbody').textContent='Mình đang lấy thông tin sản phẩm…';
  const populate=async()=>{
    const p=await api('/api/product?id='+encodeURIComponent(id)+'&session_id='+encodeURIComponent(session));
    if(version!==detailVersion || !$('detail').open)return null;
    $('detailbody').replaceChildren(card(p,undefined,true));
    const description=document.createElement('p');description.textContent=p.description||'Chưa có mô tả chi tiết.';$('detailbody').append(description);
    const heading=document.createElement('h3');heading.textContent='Đánh giá của người mua';$('detailbody').append(heading);
    renderReviews($('detailbody'),p.reviews||[],p.reviews_pending||p.enrichment_pending);
    const foot=document.createElement('p');foot.className='muted';foot.textContent='Giá ghi nhận trong dữ liệu; hãy kiểm tra giá mới tại nơi bán.';$('detailbody').append(foot);return p;
  };
  try{let p=await populate();let tries=0;const poll=async()=>{if(!p||version!==detailVersion||!$('detail').open||tries++>=8)return;if(p.enrichment_pending||p.reviews_pending){try{p=await populate();setTimeout(poll,1800);}catch(error){notice(error);}}};if(p?.enrichment_pending||p?.reviews_pending)setTimeout(poll,1800);}catch(error){$('detailbody').textContent=error.message;}
}
async function search(kind) {
  const prefix=kind==='reviews'?'review':'search',target=$(prefix+'results'),form=$(prefix+'form');
  const submit=form.querySelector('button');submit.disabled=true;target.innerHTML='<p class="empty">Mình đang tìm sản phẩm…</p>';
  try{const data=await api('/api/search?q='+encodeURIComponent($(prefix+'query').value));target.replaceChildren();if(!data.items.length){target.innerHTML='<p class="empty">Chưa có sản phẩm phù hợp. Bạn thử tên ngắn hơn hoặc thay khoảng giá nhé.</p>';return;}data.items.slice(0,5).forEach((p,i)=>target.append(card(p,i)));}catch(error){target.textContent=error.message;}finally{submit.disabled=false;}
}
async function history(){const data=await api('/api/history?session_id='+encodeURIComponent(session));$('messages').innerHTML=data.items.length?'':welcome;for(const turn of data.items){userMessage(turn.user);renderAnswer(turn.answer);}}
async function account(){
  if(!token){$('auth').hidden=false;$('profile').hidden=true;$('sessions').replaceChildren();return;}
  const data=await api('/api/account');$('auth').hidden=true;$('profile').hidden=false;$('email').textContent=data.email;$('name').value=data.profile.name||'';$('preferences').value=data.profile.preferences||'';$('favorites').replaceChildren();
  data.favorites.forEach(p=>{const row=document.createElement('div');row.className='favorites-row';const title=document.createElement('p');title.textContent=p.name;row.append(title,button('Xem sản phẩm',()=>{$('accountdialog').close();return details(p.product_id);}),button('Bỏ lưu',async()=>{await api('/api/account/favorite',{product_id:p.product_id,remove:true});await account();}));$('favorites').append(row);});
  $('sessions').replaceChildren();data.sessions.forEach((s,i)=>$('sessions').append(button('Hội thoại '+(i+1),async()=>{if(busy)return;session=s;sessionStorage.setItem('chat_session',s);$('accountdialog').close();view('chat');await history();})));
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>view(b.dataset.view));
$('messages').addEventListener('click',event=>{const b=event.target.closest('[data-query]');if(b)chat(b.dataset.query);});
$('compose').onsubmit=event=>{event.preventDefault();chat($('query').value);};
$('query').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();chat($('query').value);}};
$('searchform').onsubmit=event=>{event.preventDefault();search('search');};$('reviewform').onsubmit=event=>{event.preventDefault();search('reviews');};
$('close').onclick=()=>{++detailVersion;$('detail').close();};$('accountopen').onclick=()=>$('accountdialog').showModal();$('accountclose').onclick=()=>$('accountdialog').close();
$('auth').onsubmit=async event=>{event.preventDefault();try{const data=await api('/api/account/'+event.submitter.value,Object.fromEntries(new FormData(event.target)));token=data.token;session=data.session_id;sessionStorage.setItem('account_token',token);sessionStorage.setItem('chat_session',session);event.target.reset();$('accountnotice').textContent='Bạn đã đăng nhập.';await account();await history();}catch(error){$('accountnotice').textContent=error.message;}};
$('new').onclick=async()=>{if(busy)return;try{session=token?(await api('/api/account/session',{})).session_id:newId();sessionStorage.setItem('chat_session',session);$('messages').innerHTML=welcome;await account();$('query').focus();}catch(error){notice(error);}};
$('save').onclick=async()=>{try{await api('/api/account/profile',{name:$('name').value,preferences:$('preferences').value});$('accountnotice').textContent='Đã lưu hồ sơ.';}catch(error){$('accountnotice').textContent=error.message;}};
$('logout').onclick=async()=>{try{await api('/api/account/logout',{});token='';sessionStorage.removeItem('account_token');session=newId();sessionStorage.setItem('chat_session',session);$('messages').innerHTML=welcome;await account();$('accountnotice').textContent='Bạn đã đăng xuất.';}catch(error){$('accountnotice').textContent=error.message;}};
async function status(){try{const data=await api('/api/status');$('status').textContent=data.loaded?'Mình sẽ chọn tối đa 5 sản phẩm để bạn dễ cân nhắc.':'Danh sách sản phẩm đang chuẩn bị…';if(!data.loaded)setTimeout(status,2000);}catch(error){notice(error);}}status();
account().then(history).catch(error=>{if(error.status===401){token='';sessionStorage.removeItem('account_token');session=newId();sessionStorage.setItem('chat_session',session);account();$('messages').innerHTML=welcome;}else notice(error);});
