'use strict';
const state = {envs:[], selected:null, session:null, runs:[], filter:'all', timer:null, selectedRun:null, busy:false, runsSignature:null};
const $ = (s)=>document.querySelector(s);
const esc = (v)=>String(v??'').replace(/[&<>"']/g,(ch)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let toastTimer;
function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),4000);}
async function api(path,method='GET',data){const r=await fetch(path,{method,credentials:'same-origin',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});let payload={};try{payload=await r.json();}catch{}if(!r.ok){if(r.status===401 && path!=='/api/login'){showLogin();}throw Error(typeof payload.detail==='string'?payload.detail:(JSON.stringify(payload.detail)||r.statusText));}return payload;}
function showLogin(){
  if(state.session){
    navigator.sendBeacon(`/api/sessions/${state.session.id}/stop`,new Blob());
    state.session=null;
  }
  $('#stream').src='';
  $('#stream').style.display='none';
  $('#placeholder').style.display='flex';
  $('#loginCover').hidden=false;
  $('#application').hidden=true;
  clearInterval(state.timer);
  state.timer=null;
}
function showApp(){$('#loginCover').hidden=true;$('#application').hidden=false;}
function iconFor(e){if(e.id.startsWith('fetch:'))return '🦾';if(e.id.startsWith('custom:'))return '⚙';return ({'Locomotion':'◈','Control':'◉','Manipulation':'◎','Humanoid':'♙'})[e.category]||'⌘';}
function renderCategoryTabs(){const categories=[...new Set(state.envs.map(e=>e.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));const label=(c)=>({'Locomotion':'运动','Control':'控制','Manipulation':'机械臂','Humanoid':'人形','Fetch Robotics':'Fetch 机器人','Custom Control':'自定义控制','Custom Scene':'自定义场景','Custom':'自定义'})[c]||c;$('#categoryTabs').innerHTML=[['all','全部'],...categories.map(c=>[c,label(c)])].map(([key,name])=>`<button data-filter="${esc(key)}" class="${state.filter===key?'active':''}" aria-pressed="${state.filter===key?'true':'false'}">${esc(name)}</button>`).join('');}
function renderEnvs(){
 const query=$('#search').value.toLowerCase().trim();
 const items=state.envs.filter(e=>(state.filter==='all'||e.category===state.filter)&&(`${e.name} ${e.id} ${e.library}`.toLowerCase().includes(query)));
 $('#envCounter').textContent=state.envs.length;
 $('#librarySummary').textContent=`${state.envs.filter(e=>e.installed).length} / ${state.envs.length} 可用`;
 $('#envResultSummary').textContent=`当前显示 ${items.length} / ${state.envs.length} 个环境`;
 $('#envList').innerHTML=items.map(e=>`<button type="button" class="env-card ${e.id===state.selected?.id?'active':''} ${!e.installed?'disabled':''}" data-env="${esc(e.id)}" aria-pressed="${e.id===state.selected?.id?'true':'false'}" aria-label="${esc(e.name)}，${e.installed?'可用':'未安装依赖'}" ${!e.installed?'disabled title="需安装可选依赖"':''}><span class="env-icon" aria-hidden="true">${iconFor(e)}</span><span class="env-info"><strong>${esc(e.name)}</strong><small>${esc(e.id.replace(/^gym:/,''))}</small></span><span class="env-status ${!e.installed?'missing':''}" aria-hidden="true">${e.installed?'●':'◌'}</span></button>`).join('')||'<div class="empty-runs" role="status">没有匹配的环境。可清空搜索或切换类别。</div>';
}
function renderProblems(problems){const el=$('#catalogProblems');if(!problems.length){el.hidden=true;el.textContent='';return;}el.hidden=false;el.textContent=`环境目录问题 ${problems.length} 项：`+problems.slice(0,5).map(p=>`${p.id} · ${p.reason}`).join('；')+(problems.length>5?' …':'');}
async function refreshCatalog(){const payload=await api('/api/catalog');const list=payload.environments;state.envs=list;renderProblems(payload.problems||[]);renderCategoryTabs();renderEnvs();if(state.selected){const updated=list.find(e=>e.id===state.selected.id);if(updated)state.selected=updated;}if(!state.selected){const pick=list.find(e=>e.id==='gym:Hopper-v5'&&e.installed)||list.find(e=>e.installed);if(pick)await selectEnv(pick.id);}}
function updateStepFeedback(){
 const raw=$('#timesteps').value, count=Number(raw);
 const valid=raw.trim()!==''&&Number.isInteger(count)&&count>=1000&&count<=5000000;
 const note=$('#stepFeedback'),input=$('#timesteps');
 input.setAttribute('aria-invalid',String(!valid));
 note.classList.toggle('is-error',!valid);
 note.textContent=valid?'已设置 '+count.toLocaleString('zh-CN')+' 步':'请输入 1,000 至 5,000,000 之间的整数步数';
 document.querySelectorAll('[data-steps]').forEach(button=>button.setAttribute('aria-pressed',String(valid&&Number(button.dataset.steps)===count)));
 const e=state.selected;
 $('#startTraining').disabled=!valid||!e||e.trainable===false||state.busy;
 return valid;
}
function renderDriverState(mode){
 const random=mode==='random',policy=mode==='policy';
 $('#randomBtn').classList.toggle('active',random);
 $('#policyBtn').classList.toggle('active',policy);
 $('#randomBtn').setAttribute('aria-pressed',String(random));
 $('#policyBtn').setAttribute('aria-pressed',String(policy));
 $('#driverHelp').textContent=policy?'当前为策略模型驱动；仅能回放与所选环境匹配的已完成模型。':'随机驱动仅用于演示和环境健康检查，不代表训练效果。';
}
function updateTelemetry(s){
 const valid=s&&typeof s==='object';
 const subs=valid&&Number.isFinite(Number(s.subscribers))?Number(s.subscribers):null;
 const frame=valid&&Number.isFinite(Number(s.fps))&&Number(s.fps)>0?Number(s.fps):null;
 const width=valid&&Number.isFinite(Number(s.width))&&Number(s.width)>0?Number(s.width):null;
 const height=valid&&Number.isFinite(Number(s.height))&&Number(s.height)>0?Number(s.height):null;
 const resolution=width&&height?width+' × '+height:'—';
 $('#viewerSubscribers').textContent=subs===null?'—':String(subs);
 $('#viewerRender').textContent=!valid?'未启动':s.render_requested?'正在请求渲染':'按需待机';
 $('#viewerFps').textContent=frame===null?'—':frame+' FPS（目标）';
 $('#viewerDimensions').textContent=resolution;
 $('#viewResolution').textContent=resolution==='—'?'等待会话数据':resolution;
 $('#viewerHelp').textContent=!valid?'选择环境后，面板会显示实际会话订阅者数和渲染请求状态。':
   subs===0?'当前没有画面订阅者；渲染应处于按需待机，物理步进仍可继续。':
   '画面订阅与渲染状态来自服务器会话快照，并非浏览器实测帧率。';
}
function updateDetails(){const e=state.selected;$('#selectedTitle').textContent=e?.name||'选择一个环境开始';$('#selectedSub').textContent=e?e.id+' / '+e.category:'点击左侧环境启动仿真';$('#envId').textContent=e?.id||'—';$('#envLibrary').textContent=e?.library||'—';$('#envTraining').textContent=e?(e.trainable===false?'仅演示':'PPO / SAC'):'—';updateStepFeedback();$('#resetBtn').disabled=!state.session;$('#pauseBtn').disabled=!state.session;}
async function stopCurrent(){const old=state.session;state.session=null;$('#stream').src='';$('#stream').style.display='none';$('#placeholder').style.display='flex';$('#liveIndicator').className='live-indicator off';$('#liveIndicator').innerHTML='<span aria-hidden="true"></span> 未启动';updateTelemetry(null);renderDriverState(null);if(old){try{await api(`/api/sessions/${old.id}/stop`,'POST');}catch(e){console.warn(e);}}}
async function selectEnv(id){const e=state.envs.find(x=>x.id===id);if(!e||!e.installed||state.busy)return;state.busy=true;state.selected=e;renderEnvs();updateDetails();renderRuns();$('#placeholder').innerHTML='<div class="placeholder-mark">M<span>·</span></div><strong>正在启动仿真进程...</strong><small>首次运行可能需要载入模型和 OpenGL 渲染器</small>';try{await stopCurrent();const sess=await api('/api/sessions','POST',{env_id:id});state.session=sess;$('#stream').src=`/api/sessions/${sess.id}/stream`;$('#stream').style.display='block';$('#placeholder').style.display='none';renderDriverState('random');updateTelemetry(sess);$('#pauseBtn').textContent='Ⅱ 暂停';$('#liveIndicator').className='live-indicator';$('#liveIndicator').innerHTML='<span aria-hidden="true"></span> 启动中';updateDetails();}catch(err){toast('启动失败：'+err.message);$('#placeholder').style.display='flex';}finally{state.busy=false;updateStepFeedback();}}
async function command(path,data){if(!state.session)return;try{await api(`/api/sessions/${state.session.id}/${path}`,'POST',data);}catch(e){toast(e.message);}}
async function syncSession(){
 if(!state.session)return;
 try{
  const s=await api(`/api/sessions/${state.session.id}`);
  const indicator=$('#liveIndicator');
  const label=s.paused?'已暂停':s.state==='ready'?'运行中':s.state==='error'?'异常':s.state==='starting'?'启动中':String(s.state||'unknown').toUpperCase();
  indicator.className='live-indicator '+(s.state==='error'?'error':s.paused?'paused':'');
  indicator.innerHTML='<span aria-hidden="true"></span> '+esc(label);
  $('#mStatus').textContent=s.paused?'PAUSED':s.state==='ready'?'RUNNING':String(s.state||'UNKNOWN').toUpperCase();
  $('#mSteps').textContent=Number(s.steps||0).toLocaleString('zh-CN');
  $('#mEpisodes').textContent=Number(s.episodes||0).toLocaleString('zh-CN');
  const reward=Number(s.reward);
  $('#mReward').textContent=s.reward===null||s.reward===undefined||!Number.isFinite(reward)?'—':reward.toFixed(4);
  $('#pauseBtn').textContent=s.paused?'▶ 继续':'Ⅱ 暂停';
  if(s.error){$('#viewerNotice').textContent=s.error;$('#viewerNotice').classList.add('is-error');}
  else{$('#viewerNotice').textContent='随机动作只用于环境健康检查。训练完成后，点击对应模型的「回放」即可切换到策略驱动。';$('#viewerNotice').classList.remove('is-error');}
  renderDriverState(s.mode);
  updateTelemetry(s);
 }catch(e){console.warn(e);$('#viewerRender').textContent='状态暂不可用';}
}
function renderRuns(){const related=state.runs.filter(r=>!state.selected||r.env_id===state.selected.id);$('#runList').innerHTML=related.length?related.map(r=>{const ratio=Math.max(0,Math.min(100,100*Number(r.completed_steps||0)/Number(r.timesteps||1)));return `<div class="run-card"><div class="run-top"><strong>${esc(r.algorithm)} <small>#${esc(r.id.slice(0,7))}</small></strong><span class="pill ${esc(r.status)}">${esc(r.status)}</span></div><p>${esc(r.env_id)} · ${Number(r.completed_steps||0).toLocaleString()} / ${Number(r.timesteps).toLocaleString()} 步</p><progress class="bar" value="${ratio.toFixed(1)}" max="100"></progress><div class="run-actions"><button data-log="${esc(r.id)}">日志</button>${r.status==='completed'&&state.selected?.id===r.env_id?`<button data-replay="${esc(r.id)}">▶ 策略回放</button>`:''}${['starting','running'].includes(r.status)?`<button data-cancel="${esc(r.id)}">取消训练</button>`:''}</div>${r.average_reward!==null?`<p>平均奖励 / 评估：${Number(r.average_reward).toFixed(2)}</p>`:''}</div>`;}).join(''):'<div class="empty-runs">当前环境尚无训练记录</div>';}
async function refreshRuns(){try{state.runs=(await api('/api/training')).runs;renderRuns();}catch(e){console.warn(e);}}
function selectedAlgorithm(){return document.querySelector('input[name="algo"]:checked')?.value||'PPO';}
async function init(){showApp();await refreshCatalog();await refreshRuns();if(!state.timer){state.timer=setInterval(async()=>{if(document.hidden)return;await Promise.all([syncSession(),refreshRuns()]);},2400);}}
$('#loginForm').addEventListener('submit',async(e)=>{e.preventDefault();$('#loginError').textContent='';try{await api('/api/login','POST',{password:$('#password').value});$('#password').value='';await init();}catch(err){$('#loginError').textContent=err.message;}});
$('#logoutBtn').addEventListener('click',async()=>{await stopCurrent();try{await api('/api/logout','POST');}catch{}showLogin();});
$('#refreshBtn').addEventListener('click',()=>refreshCatalog().catch(e=>toast(e.message)));
$('#runsRefresh').addEventListener('click',()=>refreshRuns());
$('#search').addEventListener('input',renderEnvs);
$('#categoryTabs').addEventListener('click',(e)=>{const button=e.target.closest('button[data-filter]');if(!button)return;state.filter=button.dataset.filter;renderCategoryTabs();renderEnvs();});
$('#envList').addEventListener('click',(e)=>{const b=e.target.closest('button[data-env]');if(b)selectEnv(b.dataset.env);});
$('#randomBtn').addEventListener('click',()=>command('driver',{mode:'random'}));
$('#policyBtn').addEventListener('click',()=>{const models=state.runs.filter(r=>r.status==='completed'&&r.env_id===state.selected?.id);if(models.length)command('driver',{mode:'policy',run_id:models[0].id});else toast('当前环境尚无已训练成功的模型。请先训练 PPO 或 SAC。');});
$('#resetBtn').addEventListener('click',()=>command('reset'));
$('#pauseBtn').addEventListener('click',async()=>{if(!state.session)return;let s=await api(`/api/sessions/${state.session.id}`);await command('pause',{paused:!s.paused});});
$('#startTraining').addEventListener('click',async()=>{if(!state.selected)return;const count=Number($('#timesteps').value);if(!Number.isInteger(count)||count<1000||count>5000000){toast('步数必须是 1,000 至 5,000,000 的整数');return;}try{const run=await api('/api/training','POST',{env_id:state.selected.id,algorithm:selectedAlgorithm(),timesteps:count});toast('训练任务已启动：'+run.id.slice(0,8));await refreshRuns();}catch(err){toast('训练失败：'+err.message);}});
$('#runList').addEventListener('click',async(e)=>{const btn=e.target.closest('button');if(!btn)return;try{if(btn.dataset.replay){if(!state.session){toast('请先启动环境');return;}await command('driver',{mode:'policy',run_id:btn.dataset.replay});toast('模型加载请求已发送');}if(btn.dataset.log){const result=await api(`/api/training/${btn.dataset.log}/log`);$('#logText').textContent=result.text||'(暂无输出)';$('#logDialog').showModal();}if(btn.dataset.cancel){if(!confirm('确定停止当前训练吗？'))return;await api(`/api/training/${btn.dataset.cancel}/cancel`,'POST');await refreshRuns();}}catch(err){toast(err.message);}});
$('#closeLog').addEventListener('click',()=>$('#logDialog').close());
$('#stream').addEventListener('error',()=>{if(state.session)toast('暂未收到视频帧，请检查仿真状态和 OpenGL 配置');});
window.addEventListener('pagehide',()=>{if(state.session)navigator.sendBeacon(`/api/sessions/${state.session.id}/stop`,new Blob());});
(async()=>{try{await api('/api/me');await init();}catch{showLogin();}})();
