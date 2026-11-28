/* Event Run Sheet: plans sub-events as tiles, shares them live through Firebase, pops up what's needed 5 minutes
   before each one, and sends notifications. Anyone with the link can view; organisers sign in to change things.
   Settings live in config.json (Firebase web config + public push key). Firestore rules: tools/firebase/events.firestore.rules.
   Phone notifications are sent by .github/workflows/events-push.yml every 5 minutes. */
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pad=n=>String(n).padStart(2,'0');
const iso=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const ok=s=>typeof s==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(s);
const ms=s=>new Date(s).getTime();
const hm=s=>ok(s)?s.slice(11):'--:--';
const dayOf=s=>new Date(s).toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'short'});
const addMin=(s,m)=>iso(new Date(ms(s)+m*60000));
const rid=()=>Math.random().toString(36).slice(2,10);
const st=s=>s.as||s.ps, en=s=>s.ae||(s.as&&s.pe?addMin(s.pe,(ms(s.as)-ms(s.ps))/60000):s.pe)||addMin(st(s),30);
const delay=s=>s.as?Math.round((ms(s.as)-ms(s.ps))/60000):0;
const dur=x=>{x=Math.max(0,Math.round(x/1000));const h=Math.floor(x/3600),m=Math.floor(x%3600/60),s=x%60;return h?`${h}h ${pad(m)}m`:`${m}:${pad(s)}`};
const LBL={done:'Finished',live:'On now',soon:'Starting soon',up:'Upcoming'};
const ls=(k,v)=>{try{return v===undefined?localStorage.getItem(k):localStorage.setItem(k,v)}catch(e){return null}};
const S=v=>typeof v==='string'?v.slice(0,200):'';
const TZ=(()=>{try{return Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Kolkata'}catch(e){return 'Asia/Kolkata'}})();
const IOS=/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
const STANDALONE=matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;

let db=null,FS=null,AU=null,fs=null,auth=null,user=null,role='viewer',ownerEmail=null,team=[],teamUnsub=null,VAPID='';
let events=[],curId=ls('rs-ev'),canEdit=false,loaded=false,editSub=null,editEv=null,alertsOn=ls('rs-alerts')!=='off',audio=null,popItem=null,lastSig='',iRows=null,pushOn=!!ls('rs-push');
let fired=new Set();try{fired=new Set(JSON.parse(ls('rs-fired')||'[]'))}catch(e){}
const queue=[];
let notices=[],nShown=null,seenTs=+ls('rs-seen')||0,nAuto=ls('rs-nauto')!=='0';const loadT=Date.now(),popped=new Set(),mine=new Set(),nq=[];
const TPL=['Running 10 min late','All proceed to the next venue','Standby, chief guest arriving','Programme has started','Please take your seats','Dinner is served'];

/* ---------- Suggestions: built-in ideas matched to the kind of sub-event ---------- */
const LIB=[
 [/regist|check.?in|badge|help ?desk/i,['Print a spare guest list for the desk','Keep pens, tape and blank badges at the desk','Put up direction signs from the gate','Assign one volunteer for VIPs and walk-ins']],
 [/arriv|receiv|welcome|reception|chief guest|\bro\b|vip|guest of honou?r/i,['Brief the receiving party on where to stand','Keep a runner at the gate to signal the arrival','Have the bouquet or memento ready at the entrance','Clear the parking spot and route for the vehicle']],
 [/speech|address|keynote|talk|lecture|report|introduc|vote of thanks/i,['Test the podium mic and keep a spare','Keep a printed copy of the speech at the podium','Place water at the podium','Agree a time signal with the speaker']],
 [/award|prize|troph|certificate|felicit|medal|memento/i,['Arrange items in the order names will be called','Give the MC the final winners list','Assign a helper to hand items to the presenter','Mark where winners stand for photos']],
 [/lunch|dinner|breakfast|tea|coffee|meal|buffet|snack|refresh/i,['Confirm the final headcount with the caterer','Label veg and non-veg counters','Keep a separate table for the chief guest','Plan the queue so it does not block the exit']],
 [/perform|dance|music|band|song|cultural|entertain|skit|anthem|orchestra/i,['Do a sound check with the performers','Keep music files on a USB as backup','Confirm the running order with the MC','Keep the green room open with water']],
 [/photo|group pic|picture/i,['Arrange seats and standing rows beforehand','Give the photographer the shot list','Keep someone to call names in order']],
 [/setup|set up|readiness|rehears|dry run|testing|prepar|decorat/i,['Do a full dry run with the MC cues','Check power points and extension boards','Keep a spare laptop with all files','Tape down cables on walkways']],
 [/video|montage|screen|projector|slides|presentation|\bit\b|data wall/i,['Test the video on the actual screen','Keep backup copies on a pen drive','Check the video sound reaches the speakers']],
 [/depart|farewell|send.?off|closing|conclu/i,['Have the vehicle ready at the exit','Assign officers to see the guest off','Keep the path to the vehicle clear']],
 [/q ?& ?a|question|interaction|discussion|panel/i,['Keep a roaming mic ready','Have one or two questions ready in case it is quiet','Agree a hard stop time']],
 [/unveil|launch|inaugurat|lamp|ribbon|magazine/i,['Rehearse the unveiling positions','Keep scissors, lamp and matchbox ready','Cue the photographer for the moment']],
 [/announce|\bmc\b|anchor|compere|schedule of events/i,['Give the MC a printed script','Ask guests to put phones on silent','Check the mic works beforehand']],
 [/transport|bus|vehicle|pick.?up|drop|car/i,['Share the driver contact with the coordinator','Confirm the pick-up time a day before','Keep a backup vehicle on call']]
];
const GEN=['Confirm who is in charge on the day','Do a quick check 15 minutes before','Keep a printed copy of this part of the programme','Tell the MC about any change in timing'];
function ideas(s){const t=`${s.title} ${s.loc}`;const pool=[];for(const [re,l] of LIB)if(re.test(t))pool.push(...l);pool.push(...GEN);
  const have=new Set([...(s.sugg||[]),...(s.tasks||[]).map(x=>x.t),...(s.drop||[])].map(x=>x.toLowerCase()));return pool.filter(x=>!have.has(x.toLowerCase()))}

/* ---------- Data shape ---------- */
function normSub(x){x=x&&typeof x==='object'?x:{};return{id:S(x.id)||rid(),title:S(x.title)||'Untitled',loc:S(x.loc),lead:S(x.lead),ps:ok(x.ps)?x.ps:'',pe:ok(x.pe)?x.pe:'',as:ok(x.as)?x.as:'',ae:ok(x.ae)?x.ae:'',
  reqs:(Array.isArray(x.reqs)?x.reqs:[]).map(S).filter(Boolean),sugg:(Array.isArray(x.sugg)?x.sugg:[]).map(S).filter(Boolean).slice(0,8),drop:(Array.isArray(x.drop)?x.drop:[]).map(S).filter(Boolean).slice(-30),
  tasks:(Array.isArray(x.tasks)?x.tasks:[]).map(t=>({id:S(t?.id)||rid(),t:S(t?.t),done:!!t?.done})).filter(t=>t.t)}}
const norm=(id,d)=>({id,name:S(d?.name)||'Untitled event',venue:S(d?.venue),tz:S(d?.tz)||TZ,created:+d?.created||0,subs:(Array.isArray(d?.subs)?d.subs:[]).map(normSub).filter(s=>s.ps)});
const cur=()=>events.find(e=>e.id===curId)||events[0];
const sorted=ev=>[...(ev?.subs||[])].sort((a,b)=>ms(st(a))-ms(st(b)));
function status(s,now=Date.now()){const a=ms(st(s)),b=ms(en(s));return now>=b?'done':now>=a?'live':a-now<=5*60000?'soon':'up'}
function toast(m){const t=$('#toast');t.textContent=m;t.style.display='block';clearTimeout(toast.h);toast.h=setTimeout(()=>t.style.display='none',3200)}
const note=m=>$('#note').textContent=m;
const clone=o=>JSON.parse(JSON.stringify(o));
const denied=e=>/permission/i.test(e?.code||'')||e?.code==='invalid_argument';

/* ---------- Firebase adapter (same small surface the page uses everywhere) ---------- */
function mkDb(){
  const wrap=s=>({docs:s.docs.map(d=>({id:d.id,exists:true,data:()=>d.data()})),metadata:{fromCache:s.metadata.fromCache}});
  const col=(name,q=[])=>({
    orderBy:(f,dir)=>col(name,[...q,FS.orderBy(f,dir)]),
    limit:n=>col(name,[...q,FS.limit(n)]),
    doc:id=>{const r=id?FS.doc(fs,name,id):FS.doc(FS.collection(fs,name));return{id:r.id,set:d=>FS.setDoc(r,d),delete:()=>FS.deleteDoc(r)}},
    onSnapshot:(next,err)=>FS.onSnapshot(q.length?FS.query(FS.collection(fs,name),...q):FS.collection(fs,name),s=>next(wrap(s)),err)
  });
  return{collection:n=>col(n)};
}

let q=Promise.resolve();
function save(ev){
  ev.tz=ev.tz||TZ;
  const i=events.findIndex(e=>e.id===ev.id);if(i<0)events.unshift(ev);else events[i]=ev;curId=ev.id;ls('rs-ev',ev.id);render();
  if(!db){toast('Not connected: this change is not saved.');return}
  const{id,...body}=ev;body.updated=Date.now();
  q=q.then(()=>db.collection('events').doc(id).set(body)).catch(e=>{if(denied(e)){canEdit=false;toast('Only organisers can change the schedule.');render()}else toast('Could not save. Check your connection and try again.')});
}

/* ---------- Rendering ---------- */
function render(){
  const ev=cur();
  const L0=e=>sorted(e),rng=e=>{const l=L0(e);if(!l.length)return'No sub-events yet';const x=dayOf(st(l[0])),y=dayOf(st(l[l.length-1]));return x===y?x:x+' to '+y};
  $('#evs').innerHTML=(events.length||canEdit)?events.map(e=>{const t=e.subs.flatMap(s=>s.tasks);return`<button class="ev" data-a="pick" data-e="${esc(e.id)}" aria-current="${e===ev}"><b>${esc(e.name)}</b><span>${esc(rng(e))}</span><span>${e.subs.length} sub-event${e.subs.length===1?'':'s'} · ${t.filter(x=>x.done).length}/${t.length} tasks done</span></button>`}).join('')+(canEdit&&db?`<button class="ev add" data-a="imp"><b>+ Add schedule</b><span>Type or paste a programme</span></button><button class="ev add" data-a="newEv"><b>+ Blank event</b><span>Build it tile by tile</span></button>`:''):'';
  renderBell();
  $('#role').textContent=role==='owner'?'Owner · can edit':role==='organiser'?'Organiser · can edit':user&&!user.isAnonymous?'Signed in · view only':'Organiser sign in';
  $('#evName').textContent=ev?ev.name:'Event run sheet';
  const L=sorted(ev);
  $('#evSub').textContent=ev?[ev.venue,rng(ev)].filter(Boolean).join(' · '):(loaded?'No events yet':'Loading the schedule…');
  const live=location.hash==='#live';
  $('#plan').hidden=live;$('#live').hidden=!live;
  $('#tPlan').toggleAttribute('aria-current',!live);$('#tLive').toggleAttribute('aria-current',live);
  (live?$('#tLive'):$('#tPlan')).setAttribute('aria-current','page');
  renderPlan(ev,L);renderLive(ev,L);
}

function renderPlan(ev,L){
  if(!ev){$('#plan').innerHTML=loaded&&db?`<div class="empty"><h2>No events yet</h2><p>${canEdit?'Add a schedule or create a blank event to start planning.':'An organiser has not added an event yet. Organisers: tap “Organiser sign in” at the top.'}</p>${canEdit?'<button class="btn pri" data-a="imp">Add schedule</button>':''}</div>`:'';return}
  const tk=L.flatMap(s=>s.tasks),dn=tk.filter(t=>t.done).length,mv=L.filter(s=>delay(s)).length,now=Date.now(),nx=L.find(s=>ms(st(s))>now);
  let h=`<div class="figs"><div><b>${L.length}</b><span>sub-events</span></div><div><b>${dn}/${tk.length}</b><span>tasks completed</span></div><div><b>${mv}</b><span>rescheduled</span></div><div><b>${nx?hm(st(nx)):'—'}</b><span>${nx?'next: '+esc(nx.title):'nothing upcoming'}</span></div></div>`;
  if(canEdit)h+=`<div class="row tools"><button class="btn pri" data-a="newSub">+ Sub-event</button><button class="btn" data-a="imp">Add schedule</button><button class="btn" data-a="editEv">Edit event</button><label><input type="checkbox" id="ripple"${ls('rs-rip')==='1'?' checked':''}>Quick shifts move later items too</label></div>`;
  if(!L.length)h+=`<div class="empty"><p>No sub-events yet.${canEdit?' Add one or paste a timeline.':''}</p></div>`;
  let d='';const days=[];for(const s of L){const k=dayOf(st(s));if(k!==d){days.push({k,items:[]});d=k}days[days.length-1].items.push(s)}
  for(const g of days)h+=`<div class="day"><h2>${esc(g.k)}</h2><span>${g.items.length} sub-event${g.items.length>1?'s':''}</span></div><div class="grid">${g.items.map(tile).join('')}</div>`;
  $('#plan').innerHTML=h;
}
const taskLi=t=>`<li class="${t.done?'ok':''}"><button class="task" data-a="tog" data-t="${esc(t.id)}" aria-pressed="${t.done}"${canEdit?'':' disabled'}><i class="box">${t.done?'✓':''}</i><span>${esc(t.t)}</span></button></li>`;
function tile(s){
  const tk=s.tasks,todo=tk.filter(t=>!t.done),done=tk.filter(t=>t.done),pc=tk.length?Math.round(done.length/tk.length*100):0,dl=delay(s),k=status(s);
  return `<article class="tile ${k}" data-s="${esc(s.id)}" id="s-${esc(s.id)}">
  <div class="tt"><span class="t big">${hm(st(s))}</span><span class="t">– ${hm(en(s))}</span><span class="pill ${k}">${LBL[k]}</span></div>
  <h3>${esc(s.title)}</h3>
  ${s.loc||s.lead?`<p class="meta">${[s.loc,s.lead&&'In charge: '+s.lead].filter(Boolean).map(esc).join(' · ')}</p>`:''}
  ${dl?`<p class="moved">${dl>0?'Delayed':'Moved earlier'} ${Math.abs(dl)} min · planned ${hm(s.ps)}</p>`:''}
  <div class="prog"><div class="bar"><i style="width:${pc}%"></i></div><span>${done.length}/${tk.length} done</span></div>
  <p class="lbl">To do</p><ul class="tasks">${todo.map(taskLi).join('')||'<li class="none">Nothing left to do</li>'}</ul>
  ${done.length?`<p class="lbl">Completed</p><ul class="tasks">${done.map(taskLi).join('')}</ul>`:''}
  ${s.reqs.length?`<div class="req"><p class="lbl">Required at start</p><ul>${s.reqs.map(r=>`<li>${esc(r)}</li>`).join('')}</ul></div>`:''}
  ${s.sugg.length||canEdit?`<div class="sug"><p class="lbl" style="margin:0">Suggestions</p>${s.sugg.length?`<ul>${s.sugg.map((x,i)=>`<li><span>${esc(x)}</span>${canEdit?`<button class="mini" data-a="sAdd" data-i="${i}">+ Task</button><button class="mini" data-a="sDrop" data-i="${i}" aria-label="Dismiss suggestion">✕</button>`:''}</li>`).join('')}</ul>`:'<p class="hint" style="margin:4px 0 8px">Ideas for this kind of sub-event.</p>'}${canEdit?`<button class="mini" data-a="suggest">${s.sugg.length?'More ideas':'Suggest ideas'}</button>`:''}</div>`:''}
  ${canEdit?`<div class="ops"><button class="btn" data-a="shift" data-m="-5" aria-label="Move 5 minutes earlier">−5</button><button class="btn" data-a="shift" data-m="5" aria-label="Delay 5 minutes">+5</button><button class="btn" data-a="shift" data-m="15" aria-label="Delay 15 minutes">+15 min</button><button class="btn hot" data-a="del">Delete</button><button class="btn pri" data-a="edit">Edit</button></div>`:''}
  </article>`;
}

function renderLive(ev,L){
  const now=Date.now();lastSig=Math.floor(now/20000)+'';
  if(!ev){$('#live').innerHTML='<div class="empty"><p>No event to manage yet.</p></div>';return}
  const on=L.filter(s=>status(s,now)==='live'),nx=L.find(s=>ms(st(s))>now);
  const pend=s=>s.tasks.filter(t=>!t.done);
  const card=(s,next)=>`<div class="card${next?' nx':''}"><p class="lbl">${next?'Up next':'On now'} · ${hm(st(s))}–${hm(en(s))}</p><h3>${esc(s.title)}</h3>
   <div class="cd" data-cd="${next?ms(st(s)):ms(en(s))}" data-pre="${next?'in ':''}" data-post="${next?'':' left'}"></div>
   ${s.loc||s.lead?`<p class="meta">${[s.loc,s.lead&&'In charge: '+s.lead].filter(Boolean).map(esc).join(' · ')}</p>`:''}
   ${s.reqs.length?`<p class="lbl">Required</p><p style="margin:0">${s.reqs.map(esc).join(', ')}</p>`:''}
   ${pend(s).length?`<p class="lbl" style="color:var(--hot)">${pend(s).length} task${pend(s).length>1?'s':''} still open</p>`:''}</div>`;
  $('#live').innerHTML=`<div class="live-top"><div><p class="lbl">Time now</p><div class="clock" id="clk"></div>
   <p class="hint" style="margin:10px 0 14px">5 minutes before each sub-event a reminder pops up here with what's required and any open tasks. Turn on phone alerts to get them even when the app is closed.</p>
   <div class="row"><button class="btn${pushOn?' pri':''}" data-a="push" aria-pressed="${pushOn}">Phone alerts ${pushOn?'on':'off'}</button><button class="btn${alertsOn?' pri':''}" data-a="alerts" aria-pressed="${alertsOn}">Pop-ups ${alertsOn?'on':'off'}</button><button class="btn${audio?' pri':''}" data-a="sound" aria-pressed="${!!audio}">Sound ${audio?'on':'off'}</button><button class="btn" data-a="test">Preview alert</button></div></div>
   <div class="cards">${on.map(s=>card(s,false)).join('')}${nx?card(nx,true):''}${!on.length&&!nx?'<div class="card"><h3>All sub-events are finished</h3></div>':''}</div></div>
   <h2 style="margin-bottom:10px">Running order</h2>
   <ol class="sched">${L.map(s=>{const k=status(s,now),dl=delay(s);return `<li class="${k}"><time>${hm(st(s))}</time><div><h3>${esc(s.title)} <span class="pill ${k}" style="font-family:Inter">${LBL[k]}</span></h3>
   <p>${esc([hm(st(s))+'–'+hm(en(s)),s.loc,s.lead].filter(Boolean).join(' · '))}${dl?` · <span style="color:var(--hot)">${dl>0?'+':''}${dl} min vs plan</span>`:''} · ${s.tasks.filter(t=>t.done).length}/${s.tasks.length} tasks</p></div></li>`}).join('')}</ol>`;
  tick();
}

function tick(){
  const now=Date.now();
  const c=$('#clk');if(c)c.textContent=new Date(now).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  document.querySelectorAll('[data-cd]').forEach(e=>e.textContent=e.dataset.pre+dur(+e.dataset.cd-now)+e.dataset.post);
  if(Math.floor(now/20000)+''!==lastSig)render();
  checkAlerts(now);
}

/* ---------- 5-minute pop-ups (on any device with the app open) ---------- */
function checkAlerts(now){
  if(!alertsOn)return;
  for(const ev of events)for(const s of ev.subs){const a=ms(st(s)),k=ev.id+'|'+s.id+'|'+st(s);
    if(now>=a-5*60000&&now<a&&!fired.has(k)){fired.add(k);queue.push({ev:ev.id,s:s.id})}}
  ls('rs-fired',JSON.stringify([...fired].slice(-300)));
  if(!popItem&&queue.length)showPop(queue.shift());
  if(popItem){const s=findSub(popItem);if(s)$('#popCd').textContent=ms(st(s))>now?dur(ms(st(s))-now):'Now'}
}
const findSub=p=>events.find(e=>e.id===p.ev)?.subs.find(x=>x.id===p.s);
function showPop(p){
  const ev=events.find(e=>e.id===p.ev),s=findSub(p);if(!s)return;popItem=p;
  const pend=s.tasks.filter(t=>!t.done);
  $('#popB').innerHTML=`<p class="lbl">${esc(ev.name)} · ${hm(st(s))}–${hm(en(s))}</p><h2 id="popT">${esc(s.title)}</h2>
  ${s.loc||s.lead?`<p class="meta">${[s.loc,s.lead&&'In charge: '+s.lead].filter(Boolean).map(esc).join(' · ')}</p>`:''}
  <p class="lbl">Required</p>${s.reqs.length?`<ul>${s.reqs.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`:'<p class="hint">Nothing listed.</p>'}
  ${pend.length?`<p class="lbl" style="color:var(--hot)">Still to do</p><ul>${pend.map(t=>`<li>${esc(t.t)}</li>`).join('')}</ul>`:'<p class="hint">All tasks completed.</p>'}`;
  $('#pop').classList.add('on');$('#popOk').focus();beep();try{navigator.vibrate?.([200,100,200])}catch(e){}
  checkAlerts(Date.now());
}
function closePop(){$('#pop').classList.remove('on');popItem=null;if(queue.length)showPop(queue.shift())}
function beep(){if(!audio)return;try{[0,.35].forEach(t=>{const o=audio.createOscillator(),g=audio.createGain();o.frequency.value=880;g.gain.setValueAtTime(.25,audio.currentTime+t);g.gain.exponentialRampToValueAtTime(.001,audio.currentTime+t+.3);o.connect(g).connect(audio.destination);o.start(audio.currentTime+t);o.stop(audio.currentTime+t+.3)})}catch(e){}}

/* ---------- Sub-event editor ---------- */
function openSub(s){
  editSub=s?s.id:null;const ev=cur();$('#dSubT').textContent=s?'Edit sub-event':'New sub-event';
  const last=sorted(ev).pop();const dflt=last?en(last):iso(new Date(Math.ceil(Date.now()/3600000)*3600000));
  $('#sTitle').value=s?.title||'';$('#sLoc').value=s?.loc||'';$('#sLead').value=s?.lead||'';
  $('#sPs').value=s?.ps||dflt;$('#sPe').value=s?.pe||(s?'':addMin(dflt,30));$('#sAs').value=s?.as||'';$('#sAe').value=s?.ae||'';$('#sRip').checked=false;
  $('#sTasks').value=(s?.tasks||[]).map(t=>t.t).join('\n');$('#sReqs').value=(s?.reqs||[]).join('\n');
  $('#sDel').hidden=!s;$('#sDel').textContent='Delete';$('#dSub').showModal();
}
$('#fSub').addEventListener('submit',e=>{e.preventDefault();
  const ev=clone(cur());const old=ev.subs.find(x=>x.id===editSub);
  const lines=v=>v.split('\n').map(x=>x.trim()).filter(Boolean).map(x=>x.slice(0,200));
  const s=normSub({id:editSub||rid(),title:$('#sTitle').value.trim(),loc:$('#sLoc').value.trim(),lead:$('#sLead').value.trim(),ps:$('#sPs').value,pe:$('#sPe').value,as:$('#sAs').value,ae:$('#sAe').value,reqs:lines($('#sReqs').value),sugg:old?.sugg||[],drop:old?.drop||[],
    tasks:lines($('#sTasks').value).map(t=>{const o=old?.tasks.find(x=>x.t===t);return o||{id:rid(),t,done:false}})});
  if(!s.ps){toast('Add a planned start time.');return}
  if(s.as===s.ps)s.as='';if(s.ae&&s.ae===s.pe&&!s.as)s.ae='';
  if(!old&&!s.sugg.length)s.sugg=ideas(s).slice(0,3);
  if(old&&$('#sRip').checked){const m=(ms(st(s))-ms(st(old)))/60000;if(m)for(const x of ev.subs)if(x.id!==s.id&&ms(st(x))>=ms(st(old)))shiftSub(x,m)}
  if(old)ev.subs[ev.subs.indexOf(old)]=s;else ev.subs.push(s);
  if(old)autoNote(s,Math.round((ms(st(s))-ms(st(old)))/60000),$('#sRip').checked);
  save(ev);$('#dSub').close();toast('Saved');
});
$('#sDel').addEventListener('click',e=>{if(e.target.textContent!=='Tap again to delete'){e.target.textContent='Tap again to delete';return}
  const ev=clone(cur());ev.subs=ev.subs.filter(x=>x.id!==editSub);save(ev);$('#dSub').close();toast('Sub-event deleted')});
function shiftSub(x,m){const a=addMin(st(x),m),b=addMin(en(x),m);x.as=a===x.ps?'':a;x.ae=(!x.as&&b===x.pe)?'':b}

const newId=()=>db?db.collection('events').doc().id:rid();
function openEv(ev){editEv=ev?ev.id:null;$('#dEvT').textContent=ev?'Edit event':'New event';$('#eName').value=ev?.name||'';$('#eVenue').value=ev?.venue||'';$('#eDel').hidden=!ev;$('#eDel').textContent='Delete event';$('#dEv').showModal()}
$('#fEv').addEventListener('submit',e=>{e.preventDefault();
  const base=editEv?clone(cur()):{id:newId(),created:Date.now(),subs:[]};
  base.name=$('#eName').value.trim().slice(0,120);base.venue=$('#eVenue').value.trim().slice(0,120);save(base);$('#dEv').close()});
$('#eDel').addEventListener('click',e=>{if(e.target.textContent!=='Tap again to delete'){e.target.textContent='Tap again to delete';return}
  const id=editEv;events=events.filter(x=>x.id!==id);curId=events[0]?.id||null;render();$('#dEv').close();
  if(db)q=q.then(()=>db.collection('events').doc(id).delete()).catch(()=>toast('Could not delete. Try again.'))});

/* ---------- Reading a typed or pasted schedule ---------- */
const MON={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
const TM=String.raw`(\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?|\d{1,2}\s*[ap]\.?m\.?|\d{4}\s*(?:h(?:rs?|ours)?\b)?)`;
const LINE=new RegExp(`^${TM}\\s*(?:h(?:rs?|ours)?\\b)?(?:\\s*(?:-|to|till|until)\\s*${TM})?\\s*(?:h(?:rs?|ours)?\\b)?\\s*[-:,.)|]?\\s+(.+)$`,'i');
function t24(tok){if(!tok)return'';const t=tok.toLowerCase().replace(/\s+/g,'').replace(/h(rs?|ours)?$/,'');let h,m=0;
  const ap=/([ap])\.?m\.?$/.exec(t),core=t.replace(/[ap]\.?m\.?$/,'');
  if(/^\d{4}$/.test(core)){h=+core.slice(0,2);m=+core.slice(2)}else{const p=core.split(/[:.]/);h=+p[0];m=+(p[1]||0)}
  if(ap){if(h===12)h=0;if(ap[1]==='p')h+=12}
  return h<24&&m<60?pad(h)+':'+pad(m):''}
function dateLine(l){const t=l.toLowerCase().replace(/,/g,' ').replace(/\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b/g,'').replace(/(\d)(st|nd|rd|th)\b/g,'$1').replace(/\s+/g,' ').trim();let m;
  if((m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(t)))return`${m[1]}-${m[2]}-${m[3]}`;
  if((m=/^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2,4})$/.exec(t)))return`${m[3].length===2?'20'+m[3]:m[3]}-${pad(+m[2])}-${pad(+m[1])}`;
  if((m=/^(\d{1,2}) ?-?([a-z]{3})[a-z]* ?-?(\d{4})?$/.exec(t))&&MON[m[2]])return`${m[3]||new Date().getFullYear()}-${pad(MON[m[2]])}-${pad(+m[1])}`;
  if((m=/^([a-z]{3})[a-z]* (\d{1,2}) ?(\d{4})?$/.exec(t))&&MON[m[1]])return`${m[3]||new Date().getFullYear()}-${pad(MON[m[1]])}-${pad(+m[2])}`;
  return''}
const TCELL=new RegExp(`^${TM}\\s*(?:h(?:rs?|ours)?\\b)?(?:\\s*(?:-|to|till|until)\\s*${TM}\\s*(?:h(?:rs?|ours)?\\b)?)?$`,'i');
function dateIn(l){const t=l.toLowerCase().replace(/(\d)(st|nd|rd|th)\b/g,'$1');let m;
  if((m=/\b(\d{4})-(\d{2})-(\d{2})\b/.exec(t)))return`${m[1]}-${m[2]}-${m[3]}`;
  if((m=/\b(\d{1,2})[\/.](\d{1,2})[\/.](\d{4})\b/.exec(t)))return`${m[3]}-${pad(+m[2])}-${pad(+m[1])}`;
  if((m=/\b(\d{1,2})[\s\-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-,]*(\d{4})\b/.exec(t)))return`${m[3]}-${pad(MON[m[2]])}-${pad(+m[1])}`;
  if((m=/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})[\s,]+(\d{4})\b/.exec(t)))return`${m[3]}-${pad(MON[m[1]])}-${pad(+m[2])}`;
  return''}
function parseText(txt,date){const gs=[{name:'',rows:[]}];let d=date,last=null;
  for(const raw of txt.replace(/\r/g,'').split('\n')){
    let l=raw.replace(/[–—]/g,'-').replace(/^[|\s]+|[|\s]+$/g,'').trim();if(!l)continue;
    l=l.replace(/^\(?\d{1,3}[.)]?\s*(?:\||\t)\s*/,'').replace(/^\(?\d{1,3}[.)]\s+(?=\d)/,'');
    if(l.includes('\t')){const c=l.split('\t').map(x=>x.trim()).filter(Boolean),i=c.findIndex(x=>TCELL.test(x));
      if(i>=0){const two=c[i+1]&&TCELL.test(c[i+1])&&!/[-–]|to/i.test(c[i]);l=`${c[i]}${two?' - '+c[i+1]:''} ${c.slice(i+(two?2:1)).join(' | ')}`}
      else l=c.join(' ')}
    const dl=dateLine(l);if(dl){d=dl;continue}
    const bul=/^[-•*·]\s*(.+)$/.exec(l);
    if(bul&&last){last.tasks.push(bul[1].slice(0,200));continue}
    const need=/^(?:need(?:ed|s)?|req(?:uired|uirement)?s?|bring)\s*[:\-]\s*(.+)$/i.exec(l);
    if(need&&last){last.reqs.push(...need[1].split(/[,;]/).map(x=>x.trim()).filter(Boolean).map(x=>x.slice(0,200)));continue}
    const m=LINE.exec(l);
    if(!m||!t24(m[1])){
      if((l.match(/\b(ser|s\.? ?no|sl|time|timings?|events?|activity|activities|venue|location|place|responsib\w*|in charge|remarks?|duration|detail\w*)\b/gi)||[]).length>=2&&l.split(/\s+/).length<=10)continue;   // a table's header row
      const di=dateIn(l);if(di)d=di;
      const g=gs[gs.length-1],nm=l.replace(/[:\-|]+$/,'').trim().slice(0,120);if(g.rows.length)gs.push({name:nm,rows:[]});else if(!g.name)g.name=nm;last=null;continue}
    const parts=m[3].split('|').map(x=>x.trim());
    last={a:`${d}T${t24(m[1])}`,b:m[2]&&t24(m[2])?`${d}T${t24(m[2])}`:'',title:parts[0].replace(/^[-:]\s*/,'').slice(0,120),loc:(parts[1]||'').slice(0,80),lead:(parts[2]||'').slice(0,80),tasks:[],reqs:[],sugg:[]};
    if(parts[3]){const n=parts[3].replace(/^need(?:ed|s)?\s*:?/i,'');last.reqs.push(...n.split(/[,;]/).map(x=>x.trim()).filter(Boolean))}
    gs[gs.length-1].rows.push(last)}
  return gs.filter(g=>g.rows.length)}
/* Uploaded files: Word, Excel, PDF and text are read in the browser; photos and scanned PDFs go through
   on-device text recognition (Tesseract). The text lands in the box for the organiser to check. */
const LIBS={zip:'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',xlsx:'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js',
  pdf:'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js',pdfw:'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js',ocr:'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js'};
const loadJs=(u,g)=>window[g]?Promise.resolve():new Promise((r,j)=>{const s=document.createElement('script');s.src=u;s.onload=r;s.onerror=()=>j(new Error('Could not load the file reader. Check your internet and try again.'));document.head.append(s)});
function docxText(xml){const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',d=new DOMParser().parseFromString(xml,'application/xml'),out=[];
  const pt=p=>{let s='';const walk=n=>{for(const c of n.childNodes){if(c.namespaceURI!==W)continue;const k=c.localName;if(k==='t')s+=c.textContent;else if(k==='tab')s+='\t';else if(k==='br'||k==='cr')s+=' ';else walk(c)}};walk(p);return s};
  const block=n=>{for(const c of n.childNodes){if(c.namespaceURI!==W)continue;const k=c.localName;
    if(k==='p')out.push(pt(c));
    else if(k==='tbl'){for(const tr of c.childNodes){if(tr.localName!=='tr')continue;const cells=[];for(const tc of tr.childNodes)if(tc.localName==='tc')cells.push([...tc.childNodes].filter(x=>x.localName==='p').map(pt).join(' ').replace(/\s+/g,' ').trim());out.push(cells.join('\t'))}}
    else if(k==='sdt'||k==='sdtContent')block(c)}};
  block(d.getElementsByTagNameNS(W,'body')[0]||d);return out.join('\n')}
const toCanvas=f=>new Promise((res,rej)=>{const u=URL.createObjectURL(f),im=new Image();
  im.onload=()=>{const k=Math.min(1,2400/Math.max(im.naturalWidth,im.naturalHeight)),c=document.createElement('canvas');c.width=Math.round(im.naturalWidth*k);c.height=Math.round(im.naturalHeight*k);c.getContext('2d').drawImage(im,0,0,c.width,c.height);URL.revokeObjectURL(u);res(c)};
  im.onerror=()=>{URL.revokeObjectURL(u);rej(new Error('This photo can’t be opened here. Take a screenshot of it and upload that instead.'))};im.src=u});
async function ocr(srcs,stat){await loadJs(LIBS.ocr,'Tesseract');const out=[];
  for(let i=0;i<srcs.length;i++){const c=srcs[i] instanceof Blob?await toCanvas(srcs[i]):srcs[i];
    const r=await Tesseract.recognize(c,'eng',{logger:m=>{if(m.status==='recognizing text')stat(`Reading the picture${srcs.length>1?` (page ${i+1} of ${srcs.length})`:''}… ${Math.round(m.progress*100)}%`);else if(/load/.test(m.status||''))stat('Getting the text reader ready (first time only)…')}});
    out.push(r.data.text)}
  return out.join('\n')}
async function fileText(f,stat){const n=f.name.toLowerCase();
  if(/\.docx$/.test(n)){stat('Reading the Word file…');await loadJs(LIBS.zip,'JSZip');const z=await JSZip.loadAsync(f),x=z.file('word/document.xml');if(!x)throw new Error('This Word file looks damaged.');return docxText(await x.async('string'))}
  if(/\.doc$/.test(n))throw new Error('Old .doc files can’t be read. Save it as .docx or PDF, or copy and paste the text.');
  if(/\.(xlsx|xls|ods)$/.test(n)){stat('Reading the spreadsheet…');await loadJs(LIBS.xlsx,'XLSX');const wb=XLSX.read(await f.arrayBuffer());return wb.SheetNames.map(s=>XLSX.utils.sheet_to_csv(wb.Sheets[s],{FS:'\t',blankrows:false})).join('\n')}
  if(/\.pdf$/.test(n)||f.type==='application/pdf'){stat('Reading the PDF…');await loadJs(LIBS.pdf,'pdfjsLib');pdfjsLib.GlobalWorkerOptions.workerSrc=LIBS.pdfw;
    const pdf=await pdfjsLib.getDocument({data:await f.arrayBuffer()}).promise,lines=[];
    for(let i=1;i<=Math.min(pdf.numPages,20);i++){const tc=await (await pdf.getPage(i)).getTextContent(),rows=new Map();
      for(const it of tc.items){if(!it.str||!it.str.trim())continue;const y=Math.round(it.transform[5]/3);if(!rows.has(y))rows.set(y,[]);rows.get(y).push({x:it.transform[4],w:it.width,s:it.str})}
      [...rows.entries()].sort((a,b)=>b[0]-a[0]).forEach(([,its])=>{its.sort((a,b)=>a.x-b.x);let s='',end=null;for(const t of its){if(end!==null)s+=t.x-end>12?'\t':t.x-end>1?' ':'';s+=t.str;end=t.x+t.w}lines.push(s)})}
    let text=lines.join('\n');
    if(text.replace(/\s/g,'').length<20){const pages=[];for(let i=1;i<=Math.min(pdf.numPages,3);i++){const pg=await pdf.getPage(i),v=pg.getViewport({scale:2}),c=document.createElement('canvas');c.width=v.width;c.height=v.height;await pg.render({canvasContext:c.getContext('2d'),viewport:v}).promise;pages.push(c)}text=await ocr(pages,stat)}
    return text}
  if(f.type.startsWith('image/')||/\.(jpe?g|png|webp|heic|heif|gif|bmp)$/.test(n))return ocr([f],stat);
  if(f.type.startsWith('text/')||/\.(txt|csv|tsv|md)$/.test(n))return f.text();
  throw new Error('This file type can’t be read. Use Word (.docx), Excel, PDF, text or a photo.')}
$('#iFile').addEventListener('change',async e=>{const f=e.target.files[0];e.target.value='';if(!f)return;
  const stat=m=>$('#iStat').textContent=m,btn=$('#iGo'),lab=$('#iFileL');btn.disabled=true;lab.style.opacity=.5;lab.style.pointerEvents='none';
  try{const text=String(await fileText(f,stat)||'').replace(/\u00a0/g,' ').replace(/[ ]{2,}/g,' ').trim();
    if(!text){stat('No text found in that file. Try another file, or type the programme.');return}
    const box=$('#iText');box.value=(box.value.trim()?box.value.trim()+'\n':'')+text;resetImp();
    const gs=parseText(box.value,$('#iDate').value||iso(new Date()).slice(0,10));showRows(gs);
    stat(gs.length?`${$('#iStat').textContent} The text from ${f.name} is in the box below; fix anything misread, then tap the button.`:`Text from ${f.name} is in the box below, but no lines with times were found. Check it, fix the times (like 1700h or 17:00), then tap Read schedule.`)}
  catch(err){stat(err?.message&&!/^[A-Z_]+$/.test(err.message)?err.message:'Could not read that file. Try again, or type the programme.')}
  finally{btn.disabled=false;lab.style.opacity='';lab.style.pointerEvents=''}});
const gName=(g,i)=>g.name||`Event ${events.length+i+1}`;
function showRows(gs){iRows=gs;const n=gs.reduce((s,g)=>s+g.rows.length,0),newEv=$('#iMode').value==='new';
  $('#iPrev').innerHTML=gs.map((g,i)=>`<li><h4>${newEv?'New event: ':''}${esc(gName(g,i))}</h4><ol style="margin:0;padding-inline-start:22px">${g.rows.map(r=>`<li><b>${esc(r.a.slice(8,10)+'/'+r.a.slice(5,7))} ${hm(r.a)}${r.b?'–'+hm(r.b):''}</b> ${esc(r.title)}${r.loc?' · '+esc(r.loc):''}${r.tasks.length+r.reqs.length?` <span class="hint">(${r.tasks.length} tasks, ${r.reqs.length} needed)</span>`:''}</li>`).join('')}</ol></li>`).join('');
  $('#iStat').textContent=n?`Found ${gs.length>1?gs.length+' events with ':''}${n} sub-event${n>1?'s':''}. Check the list, then add.`:'No lines with times found. Start each line with a time, like 19:30 or 7:30 pm or 1930h.';
  $('#iGo').textContent=!n?'Read schedule':newEv?(gs.length>1?`Create ${gs.length} events`:'Create event'):`Add ${n} to ${cur()?.name||'event'}`}
function resetImp(){iRows=null;$('#iPrev').innerHTML='';$('#iStat').textContent='';$('#iGo').textContent='Read schedule'}
['#iText','#iDate'].forEach(s=>$(s).addEventListener('input',resetImp));
$('#iMode').addEventListener('change',()=>{if(iRows)showRows(iRows)});
$('#fImp').addEventListener('submit',e=>{e.preventDefault();
  const date=$('#iDate').value,txt=$('#iText').value.trim();if(!date)return;
  if(!iRows){if(!txt){$('#iStat').textContent='Type or paste a schedule first.';return}showRows(parseText(txt,date));return}
  const mode=$('#iMode').value,gs=iRows;
  for(const g of gs)g.rows.forEach((r,i,rows)=>{if(!ok(r.b)||ms(r.b)<=ms(r.a))r.b=rows[i+1]&&ms(rows[i+1].a)>ms(r.a)?rows[i+1].a:addMin(r.a,30)});
  const mk=r=>{const s=normSub({id:rid(),title:r.title,loc:r.loc,lead:r.lead,ps:r.a,pe:r.b,tasks:r.tasks.map(t=>({id:rid(),t,done:false})),reqs:r.reqs});s.sugg=ideas(s).slice(0,3);return s};
  let msg;
  if(mode==='new'){const now=Date.now(),made=gs.map((g,i)=>({id:newId(),name:gName(g,i),venue:'',tz:TZ,created:now+gs.length-i,subs:g.rows.map(mk)}));
    for(const ev of [...made].reverse())save(ev);curId=made[0].id;ls('rs-ev',curId);render();msg=made.length>1?`${made.length} events created`:`${made[0].name} created`}
  else{const ev=clone(cur());let up=0,add=0;
    for(const r of gs.flatMap(g=>g.rows)){
      const ex=mode==='act'&&ev.subs.find(x=>x.title.toLowerCase()===r.title.toLowerCase());
      if(ex){ex.as=r.a===ex.ps?'':r.a;ex.ae=r.b===ex.pe&&!ex.as?'':r.b;if(r.loc)ex.loc=r.loc;up++}else{ev.subs.push(mk(r));add++}}
    save(ev);msg=`${up?up+' updated, ':''}${add} added`}
  $('#dImp').close();$('#iText').value='';resetImp();toast(msg)});

/* ---------- Notifications ---------- */
const when=t=>{const d=new Date(t),td=new Date();return(d.toDateString()===td.toDateString()?'':d.toLocaleDateString(undefined,{day:'numeric',month:'short'})+' ')+pad(d.getHours())+':'+pad(d.getMinutes())};
const wa=n=>'https://wa.me/?text='+encodeURIComponent(`${n.level==='urgent'?'URGENT: ':''}${n.evName?n.evName+' — ':''}${n.text}${n.to?' (For: '+n.to+')':''}`);
function renderBell(){const u=notices.filter(n=>n.at>seenTs).length,b=$('#bell');b.hidden=!db;b.innerHTML='Notifications'+(u?`<b>${u}</b>`:'');b.setAttribute('aria-label',`Notifications, ${u} unread`)}
function renderNotes(){
  $('#nCompose').hidden=!canEdit;$('#nSend').hidden=!canEdit;$('#nAuto').checked=nAuto;$('#nPush').textContent=`Phone alerts ${pushOn?'on':'off'}`;
  $('#nTpl').innerHTML=TPL.map(t=>`<button type="button" class="mini" data-tpl="${esc(t)}">${esc(t)}</button>`).join('');
  $('#nHint').textContent='Pops up at once for everyone with the app open. Phones with phone alerts on also get it within about 5 minutes, even with the app closed. Share on WhatsApp reaches anyone else.';
  $('#nList').innerHTML=notices.length?notices.map(n=>`<li><div class="row"><span class="lv ${n.level}">${n.level==='urgent'?'Urgent':'Notice'}</span><span class="meta">${esc(when(n.at))}${n.evName?' · '+esc(n.evName):''}${n.to?' · For: '+esc(n.to):''}</span></div>
    <p>${esc(n.text)}</p><div class="row"><a href="${esc(wa(n))}" target="_blank" rel="noopener">Share on WhatsApp</a>${canEdit?`<button type="button" class="mini" data-a="nDel" data-n="${esc(n.id)}">Delete</button>`:''}</div></li>`).join(''):'<li class="hint">No notifications yet.</li>'}
function openNotes(){renderNotes();$('#dNote').showModal();markSeen()}
function markSeen(){const m=Math.max(seenTs,...notices.map(n=>n.at));if(m>seenTs){seenTs=m;ls('rs-seen',m)}renderBell()}
function sendNotice(text,level='info',to=''){
  text=String(text).trim().slice(0,280);if(!text||!db)return Promise.resolve(false);const ev=cur();
  const ref=db.collection('notices').doc();mine.add(ref.id);
  return ref.set({text,level,to:String(to).trim().slice(0,60),ev:ev?.id||'',evName:ev?.name||'',at:Date.now()}).then(()=>true,e=>{toast(denied(e)?'Only organisers can send notifications.':'Could not send. Check your connection.');return false})}
function showNote(n){nShown=n;const b=$('#nb');b.className='on '+n.level;
  b.innerHTML=`<p class="lbl" style="margin:0">${n.level==='urgent'?'Urgent · ':''}${esc(when(n.at))}${n.evName?' · '+esc(n.evName):''}</p><p class="msg">${esc(n.text)}</p>${n.to?`<p class="meta">For: ${esc(n.to)}</p>`:''}
  <div class="dact" style="margin-top:6px"><button class="btn" data-a="notes">All notifications</button><button class="btn pri" data-a="nOk">OK</button></div>`;
  beep();try{navigator.vibrate?.(n.level==='urgent'?[300,100,300,100,300]:[200])}catch(e){}}
function nextNote(){const n=nShown;nShown=null;$('#nb').className='';if(n&&n.at>seenTs){seenTs=n.at;ls('rs-seen',n.at);renderBell()}if(nq.length)showNote(nq.shift())}
$('#nTpl').addEventListener('click',e=>{const t=e.target.closest('[data-tpl]');if(t){$('#nText').value=t.dataset.tpl;$('#nText').focus()}});
$('#nAuto').addEventListener('change',e=>{nAuto=e.target.checked;ls('rs-nauto',nAuto?'1':'0')});
$('#fNote').addEventListener('submit',async e=>{e.preventDefault();if(!canEdit)return;const t=$('#nText').value.trim();if(!t){toast('Write a message first');return}
  $('#nSend').disabled=true;const ok=await sendNotice(t,$('#nLvl').value,$('#nTo').value);$('#nSend').disabled=false;
  if(ok){$('#nText').value='';$('#nTo').value='';$('#nLvl').value='info';toast('Sent to everyone')}});
const autoNote=(s,m,rip)=>{if(nAuto&&canEdit&&m)sendNotice(`${s.title} ${m>0?'delayed':'moved earlier'} by ${Math.abs(m)} min. Now starts ${hm(st(s))}.${rip?' Later items moved too.':''}`,'info')};

/* ---------- Phone alerts (web push) ---------- */
const b64u=s=>{const p='='.repeat((4-s.length%4)%4),r=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(r,c=>c.charCodeAt(0))};
function help(html){$('#helpBody').innerHTML=html;$('#dHelp').showModal()}
async function savePush(sub){
  if(!auth.currentUser)await AU.signInAnonymously(auth);
  const j=sub.toJSON(),uid=auth.currentUser.uid;
  await FS.setDoc(FS.doc(fs,'push',uid),{endpoint:j.endpoint,p256dh:j.keys.p256dh,auth:j.keys.auth,tz:TZ,on:true,at:Date.now()});
  ls('rs-push',uid);pushOn=true}
async function togglePush(){
  if(!fs){toast('Not connected yet');return}
  if(pushOn){try{const reg=await navigator.serviceWorker.getRegistration();const s=await reg?.pushManager.getSubscription();await s?.unsubscribe();
      const id=ls('rs-push');if(id&&auth.currentUser?.uid===id)await FS.deleteDoc(FS.doc(fs,'push',id))}catch(e){}
    ls('rs-push','');pushOn=false;render();if($('#dNote').open)renderNotes();toast('Phone alerts off');return}
  if(IOS&&!STANDALONE){help(`<h2>Add it to your Home Screen first</h2><p>On iPhone, alerts only work from the app icon:</p><ol><li>Tap the <b>Share</b> button in Safari.</li><li>Choose <b>Add to Home Screen</b>, then <b>Add</b>.</li><li>Open <b>Run Sheet</b> from the new icon and tap <b>Phone alerts</b> again.</li></ol><p class="hint">Needs iOS 16.4 or later.</p>`);return}
  if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){help('<h2>Not available here</h2><p>This browser can’t receive phone alerts. Try Chrome on Android, or Safari on iPhone after adding the app to your Home Screen.</p>');return}
  try{const perm=await Notification.requestPermission();
    if(perm!=='granted'){help('<h2>Notifications are blocked</h2><p>Allow notifications for this site in your browser or phone settings, then tap Phone alerts again.</p>');return}
    const reg=await navigator.serviceWorker.ready;let sub=await reg.pushManager.getSubscription();
    if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64u(VAPID)});
    await savePush(sub);render();if($('#dNote').open)renderNotes();toast('Phone alerts on')}
  catch(e){toast(/admin-restricted|operation-not-allowed/.test(e?.code||'')?'Phone alerts need Anonymous sign-in switched on in Firebase.':'Could not turn on phone alerts. Try again.')}}
async function keepPush(){   // a phone can change its push address; save the new one quietly
  try{if(!pushOn||Notification.permission!=='granted')return;const reg=await navigator.serviceWorker.ready;let sub=await reg.pushManager.getSubscription();
    if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64u(VAPID)});
    if(!auth.currentUser||auth.currentUser.uid===ls('rs-push'))await savePush(sub)}catch(e){}}

/* ---------- Organiser sign-in and team ---------- */
const AERR={'auth/invalid-credential':'Email or password is wrong.','auth/wrong-password':'Email or password is wrong.','auth/user-not-found':'No account with that email. Tap Create account.','auth/email-already-in-use':'That email already has an account. Tap Sign in.','auth/weak-password':'Use at least 6 characters for the password.','auth/invalid-email':'That email address doesn’t look right.','auth/too-many-requests':'Too many tries. Wait a few minutes and try again.','auth/operation-not-allowed':'Email sign-in is switched off in Firebase (setup step 3).','auth/network-request-failed':'No connection. Check your internet and try again.','auth/missing-password':'Enter your password.'};
const aerr=e=>{$('#accErr').textContent=AERR[e?.code]||'Something went wrong. Try again.'};
function renderAcc(){
  if(!$('#dAcc').open)return;$('#accErr').textContent='';const u=user&&!user.isAnonymous?user:null;let h;
  if(!fs)h='<h2>Not connected</h2><p>The app is not set up yet, or there is no connection.</p>';
  else if(!u)h=`<h2>Organiser sign in</h2><p class="hint">Only organisers need an account. Everyone else can just use the link.</p>
    <label class="fl">Email<input type="email" id="aEm" autocomplete="email"></label><label class="fl">Password<input type="password" id="aPw" autocomplete="current-password" minlength="6"></label>
    <div class="row"><button type="button" class="btn pri" data-a="signin">Sign in</button><button type="button" class="btn" data-a="signup">Create account</button></div>
    <button type="button" class="linkbtn" data-a="reset">Forgot password?</button>`;
  else if(!u.emailVerified)h=`<h2>Check your email</h2><p>We sent a link to <b>${esc(u.email)}</b>. Open it to confirm your address, then come back and tap the button below.</p><p class="hint">It comes from noreply@…firebaseapp.com. Check spam or All mail.</p>
    <div class="row"><button type="button" class="btn pri" data-a="verified">I’ve confirmed it</button><button type="button" class="btn" data-a="resend">Send again</button><button type="button" class="btn" data-a="signout">Sign out</button></div>`;
  else{h=`<h2>${role==='owner'?'Owner':role==='organiser'?'Organiser':'Signed in'}</h2><p>${esc(u.email)}</p>`;
    if(!ownerEmail)h+=`<p>This app has no owner yet. The owner adds and removes organisers.</p><button type="button" class="btn pri" data-a="claim">Make me the owner</button>`;
    else if(role==='viewer')h+=`<p>You can view everything. To edit, ask the owner to add <b>${esc(u.email)}</b> as an organiser, then tap Refresh.</p><button type="button" class="btn" data-a="refreshRole">Refresh</button>`;
    if(role==='owner')h+=`<h3 style="margin-top:8px">Organisers</h3><p class="hint">Organisers can edit, reschedule and send notifications. They sign in here with the same email.</p>
      <ul class="team">${team.length?team.map(em=>`<li><span>${esc(em)}</span><button type="button" class="mini" data-a="teamDel" data-em="${esc(em)}">Remove</button></li>`).join(''):'<li class="hint">No organisers yet.</li>'}</ul>
      <div class="row" style="flex-wrap:nowrap"><input type="email" id="tEm" placeholder="name@example.com" autocomplete="off"><button type="button" class="btn pri" data-a="teamAdd">Add</button></div>`;
    h+=`<button type="button" class="btn" data-a="signout" style="justify-self:start">Sign out</button>`}
  $('#accBody').innerHTML=h}
async function refreshRole(){
  canEdit=false;role='viewer';
  try{const o=await FS.getDoc(FS.doc(fs,'config','owner'));ownerEmail=o.exists()?String(o.data().email||'').toLowerCase():null}catch(e){}
  const em=user&&!user.isAnonymous&&user.emailVerified?String(user.email||'').toLowerCase():'';
  if(em&&ownerEmail===em){role='owner';canEdit=true}
  else if(em){try{const d=await FS.getDoc(FS.doc(fs,'organisers',em));if(d.exists()){role='organiser';canEdit=true}}catch(e){}}
  if(role==='owner'&&!teamUnsub)teamUnsub=FS.onSnapshot(FS.collection(fs,'organisers'),s=>{team=s.docs.map(d=>d.id).sort();renderAcc()},()=>{});
  if(role!=='owner'&&teamUnsub){teamUnsub();teamUnsub=null;team=[]}
}
async function accAction(a,b){
  const em=()=>($('#aEm')?.value||'').trim(),pw=()=>$('#aPw')?.value||'';
  try{
    if(a==='signin'){await AU.signInWithEmailAndPassword(auth,em(),pw())}
    if(a==='signup'){const c=await AU.createUserWithEmailAndPassword(auth,em(),pw());await AU.sendEmailVerification(c.user)}
    if(a==='reset'){if(!em()){$('#accErr').textContent='Type your email above first.';return}await AU.sendPasswordResetEmail(auth,em());toast('Password reset email sent')}
    if(a==='resend'){await AU.sendEmailVerification(auth.currentUser);toast('Sent again')}
    if(a==='verified'){await auth.currentUser.reload();await auth.currentUser.getIdToken(true);user=auth.currentUser;if(!user.emailVerified){$('#accErr').textContent='Not confirmed yet. Open the link in the email first.';return}}
    if(a==='signout'){await AU.signOut(auth)}
    if(a==='claim'){await FS.setDoc(FS.doc(fs,'config','owner'),{email:user.email.toLowerCase(),at:Date.now()})}
    if(a==='teamAdd'){const v=($('#tEm').value||'').trim().toLowerCase();if(!/^[^\s@\/]+@[^\s@\/]+\.[^\s@\/]+$/.test(v)){$('#accErr').textContent='Enter a full email address.';return}await FS.setDoc(FS.doc(fs,'organisers',v),{at:Date.now()});toast('Organiser added')}
    if(a==='teamDel'){if(!b.dataset.armed){b.dataset.armed='1';b.textContent='Tap again';return}await FS.deleteDoc(FS.doc(fs,'organisers',b.dataset.em))}
    if(['verified','claim','refreshRole','signin'].includes(a)){await refreshRole();render()}
    renderAcc();
  }catch(e){if(/permission/i.test(e?.code||''))$('#accErr').textContent=a==='claim'?'Someone already owns this app.':'Not allowed.';else aerr(e)}}

/* ---------- Clicks ---------- */
document.addEventListener('click',e=>{
  if(e.target.matches('[data-close]')){e.target.closest('dialog').close();return}
  const b=e.target.closest('[data-a]');if(!b)return;const a=b.dataset.a,sid=b.closest('[data-s]')?.dataset.s,ev=cur();
  if(['signin','signup','reset','resend','verified','signout','claim','teamAdd','teamDel','refreshRole'].includes(a)){accAction(a,b);return}
  if(a==='acc'){$('#dAcc').showModal();renderAcc()}
  if(a==='push')togglePush();
  if(a==='tog'&&canEdit){const c=clone(ev),t=c.subs.find(x=>x.id===sid)?.tasks.find(x=>x.id===b.dataset.t);if(t){t.done=!t.done;save(c)}}
  if(a==='shift'){const c=clone(ev),s=c.subs.find(x=>x.id===sid),m=+b.dataset.m,from=ms(st(s));
    if($('#ripple')?.checked){for(const x of c.subs)if(x.id!==sid&&ms(st(x))>=from)shiftSub(x,m)}shiftSub(s,m);save(c);autoNote(s,m,!!$('#ripple')?.checked);toast(`${s.title} ${m>0?'delayed':'moved earlier'} ${Math.abs(m)} min`)}
  if(a==='suggest'){const c=clone(ev),s=c.subs.find(x=>x.id===sid);if(!s)return;const more=ideas(s).slice(0,3);if(!more.length){toast('No more ideas for this one');return}s.sugg=[...s.sugg,...more].slice(-8);save(c)}
  if(a==='sAdd'||a==='sDrop'){const c=clone(ev),s=c.subs.find(x=>x.id===sid),i=+b.dataset.i,v=s?.sugg[i];if(v==null)return;s.sugg.splice(i,1);if(a==='sAdd')s.tasks.push({id:rid(),t:v,done:false});else s.drop=[...s.drop,v].slice(-30);save(c)}
  if(a==='notes'){if(nShown)nextNote();openNotes()}
  if(a==='nOk')nextNote();
  if(a==='nDel'){if(!b.dataset.armed){b.dataset.armed='1';b.textContent='Tap again';return}const id=b.dataset.n;if(db)db.collection('notices').doc(id).delete().catch(()=>toast('Could not delete'))}
  if(a==='del'){if(!b.dataset.armed){b.dataset.armed='1';b.textContent='Tap again to delete';setTimeout(()=>{if(b.isConnected){delete b.dataset.armed;b.textContent='Delete'}},4000);return}
    const c=clone(ev),s=c.subs.find(x=>x.id===sid);c.subs=c.subs.filter(x=>x.id!==sid);save(c);toast(`Deleted ${s?.title||'sub-event'}`)}
  if(a==='edit')openSub(ev.subs.find(x=>x.id===sid));
  if(a==='newSub')openSub(null);
  if(a==='newEv')openEv(null);
  if(a==='pick'){curId=b.dataset.e;ls('rs-ev',curId);render();$('#evs').querySelector('[aria-current=true]')?.scrollIntoView({block:'nearest',inline:'nearest'})}
  if(a==='editEv')openEv(ev);
  if(a==='imp'){$('#iDate').value=iso(new Date()).slice(0,10);$('#iMode').innerHTML='<option value="new">A new event (separate tiles)</option>'+(ev?`<option value="plan">More sub-events in ${esc(ev.name)}</option><option value="act">Actual times for ${esc(ev.name)}</option>`:'');resetImp();$('#dImp').showModal()}
  if(a==='alerts'){alertsOn=!alertsOn;ls('rs-alerts',alertsOn?'on':'off');render()}
  if(a==='sound'){if(audio){audio.close?.();audio=null}else{try{audio=new (window.AudioContext||window.webkitAudioContext)();beep()}catch(x){toast('Sound is not available here')}}render()}
  if(a==='test'){const L=sorted(ev),now=Date.now(),s=L.find(x=>ms(st(x))>now)||L[L.length-1];if(s)showPop({ev:ev.id,s:s.id});else toast('Add a sub-event first')}
});
document.addEventListener('change',e=>{if(e.target.id==='ripple')ls('rs-rip',e.target.checked?'1':'0')});
$('#popOk').addEventListener('click',closePop);
$('#popGo').addEventListener('click',()=>{const p=popItem;closePop();if(p){curId=p.ev;location.hash='#planning';render();setTimeout(()=>document.getElementById('s-'+p.s)?.scrollIntoView({behavior:'smooth',block:'center'}),60)}});
addEventListener('keydown',e=>{if(e.key==='Escape'&&popItem)closePop()});
addEventListener('hashchange',render);
render();setInterval(tick,1000);

/* ---------- Start: config, Firebase, live data ---------- */
(async()=>{
  if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js').catch(()=>{});
  let cfg=null;try{cfg=await (await fetch('config.json',{cache:'no-cache'})).json()}catch(e){}
  if(!cfg?.apiKey||/PASTE/.test(cfg.apiKey)||!cfg.projectId){loaded=true;
    $('#plan').innerHTML=`<div class="empty setup" style="text-align:start"><h2>Almost ready</h2><p>This app needs its Firebase project connected before anyone can use it. The setup steps are in the chat where it was built (paste the Firebase web config into events/config.json).</p></div>`;
    $('#evSub').textContent='Setup needed';return}
  VAPID=cfg.vapidPublicKey||'';
  const timer=setTimeout(()=>{if(!loaded)note('Can’t reach the schedule yet. It will appear as soon as the connection returns.')},10000);
  try{const B='https://www.gstatic.com/firebasejs/10.14.1/';
    const [A,Au,F]=await Promise.all([import(B+'firebase-app.js'),import(B+'firebase-auth.js'),import(B+'firebase-firestore.js')]);
    const app=A.initializeApp(cfg);FS=F;AU=Au;fs=F.getFirestore(app);auth=Au.getAuth(app);db=mkDb()}
  catch(e){clearTimeout(timer);loaded=true;note('Could not load the app. Check your connection and reload.');render();return}
  db.collection('notices').orderBy('at','desc').limit(50).onSnapshot(snap=>{
    notices=snap.docs.map(d=>{const x=d.data()||{};return{id:d.id,text:String(x.text??'').slice(0,280),level:x.level==='urgent'?'urgent':'info',to:S(x.to).slice(0,60),evName:S(x.evName),at:+x.at||0}}).filter(n=>n.text);
    const floor=Math.max(seenTs,loadT-10*60000);
    for(const n of [...notices].reverse())if(n.at>floor&&!popped.has(n.id)&&!mine.has(n.id)){popped.add(n.id);nq.push(n)}
    if(!nShown&&nq.length)showNote(nq.shift());
    renderBell();if($('#dNote').open){renderNotes();markSeen()}
  },()=>{});
  db.collection('events').onSnapshot(snap=>{
    if(!snap.metadata.fromCache){loaded=true;clearTimeout(timer);note('')}
    events=snap.docs.map(d=>norm(d.id,d.data())).sort((a,b)=>b.created-a.created);loaded=loaded||events.length>0;render();
  },e=>{clearTimeout(timer);loaded=true;note(denied(e)?'The Firebase rules are not published yet (setup step 4).':'Live updates stopped. Reload the page to reconnect.');render()});
  AU.onAuthStateChanged(auth,async u=>{user=u;await refreshRole();render();renderAcc();keepPush()});
})();
