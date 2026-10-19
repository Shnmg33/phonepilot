const $ = (s, el = document) => el.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const labels = {overview:'工作台',tasks:'任务中心',schedules:'定时计划',skills:'技能记忆',devices:'设备连接',providers:'模型配置'};
const statusNames = {queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',blocked:'需要介入',cancelled:'已停止',interrupted:'已中断',active:'已启用',draft:'待审核',disabled:'已停用',online:'在线',offline:'离线'};
const kindNames = {queued:'任务排队',observe:'观察界面',plan:'动作规划',action:'执行动作',memory:'技能检索',learned:'经验总结',memory_error:'总结失败',...statusNames};
let token = sessionStorage.getItem('phonepilot-token') || '';
let state = {tasks:[],skills:[],devices:[],providers:[],schedules:[]};
let renderedTaskFingerprint = '';
const archivedTasks = new Map();
let currentPage = 'overview', filter = 'all', search = '', selectedTask = null, toastTimer, screenURL, refreshing = false;
const date = ts => ts ? new Date(ts * 1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const pill = status => `<span class="pill ${esc(status)}">${esc(statusNames[status] || status)}</span>`;
const empty = (title, text, action='') => `<div class="empty"><div class="empty-icon">◇</div><h3>${title}</h3><p>${text}</p>${action}</div>`;
const deviceName = id => state.devices.find(d=>d.id===id)?.name || id;
const providerName = id => state.providers.find(p=>p.id===id)?.name || id;
const primary = (action, text) => `<button class="primary" data-action="${action}">${text}</button>`;

function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(()=>$('#toast').classList.remove('show'),4500); }
async function api(path, options={}) {
  const response = await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json','Authorization':'Bearer '+token,...options.headers}});
  if (response.status===401) { token=''; sessionStorage.removeItem('phonepilot-token'); showLogin(); throw new Error('请重新输入管理员令牌'); }
  if (!response.ok) { const data = await response.json().catch(()=>({detail:'请求失败'})); throw new Error(typeof data.detail==='string' ? data.detail : (data.detail||[]).map(e=>`${e.loc?.slice(1).join('.')}: ${e.msg}`).join('\n')); }
  return response.headers.get('content-type')?.includes('image/') ? response.blob() : response.json();
}
const post = (path, body={}) => api(path,{method:'POST',body:JSON.stringify(body)});
function showLogin() { if (!$('#login').open) $('#login').showModal(); }
function modal(title, content) { $('#modal-title').textContent=title; $('#modal-body').innerHTML=content; if (!$('#modal').open) $('#modal').showModal(); }
function closeModal() { $('#modal').close(); if(screenURL){URL.revokeObjectURL(screenURL);screenURL=null;} }
function head(eyebrow,title,description,action='') { return `<div class="page-head"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="muted">${description}</p></div>${action}</div>`; }
function deviceOptions(selected) { return state.devices.length ? state.devices.map(d=>`<option value="${esc(d.id)}" ${d.id===selected?'selected':''}>${esc(d.name)} · ${d.online?'在线':'离线'}</option>`).join('') : '<option value="">暂无设备，请先连接桥接程序</option>'; }
function providerOptions(selected) { return state.providers.map(p=>`<option value="${esc(p.id)}" ${p.id===selected?'selected':''}>${esc(p.name)}${p.configured?'':' · 未配密钥'}</option>`).join(''); }

async function refresh(renderPage=true) {
  if (!token || refreshing) return;
  refreshing=true;
  try {
    state=await api('/state'); $('#connection').className='connection online'; $('#connection').innerHTML='<i></i>服务已连接';
    $('#nav-count').textContent=state.tasks.filter(t=>['queued','running'].includes(t.status)).length;
    if(renderPage) render();
  } catch(e) { $('#connection').className='connection'; $('#connection').innerHTML='<i></i>服务未连接'; if(renderPage && token) toast(e.message); }
  finally {refreshing=false;}
}

function render() {
  const route=location.hash.slice(1).split('/'); currentPage=labels[route[0]]?route[0]:'overview';
  $('#breadcrumb-page').textContent=labels[currentPage];
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===currentPage));
  selectedTask=currentPage==='tasks' ? route[1] : null;
  const pages={overview:overview,tasks:tasks,schedules:schedules,skills:skills,devices:devices,providers:providers};
  $('#main').innerHTML=selectedTask?taskDetail(selectedTask):pages[currentPage]();
  if(selectedTask) loadEvents(selectedTask);
}

function taskTable(rows) {
  if(!rows.length) return empty('还没有任务记录','描述你想让手机完成的事情，智能体会逐步探索并记录过程。',primary('new-task','＋ 创建第一个任务'));
  return `<div class="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>模型</th><th>创建时间</th><th></th></tr></thead><tbody>${rows.map(t=>`<tr><td class="task-cell"><a href="#tasks/${t.id}"><strong>${esc(t.goal)}</strong><small>${esc(deviceName(t.device))}</small></a></td><td>${pill(t.status)}</td><td>${esc(providerName(t.provider))}</td><td>${date(t.created)}</td><td><a class="text-link" href="#tasks/${t.id}">查看 ↗</a></td></tr>`).join('')}</tbody></table></div>`;
}

function overview() {
  const online=state.devices.filter(d=>d.online), active=state.tasks.filter(t=>['running','queued'].includes(t.status));
  const skillsActive=state.skills.filter(s=>s.status==='active').length, succeeded=state.tasks.filter(t=>t.status==='succeeded').length;
  const first=online[0]||state.devices[0];
  return head('YOUR AUTONOMOUS WORKSPACE','把手机任务，交给 AI。','安排工作，观察执行，让每一次探索沉淀为下一次的能力。',primary('new-task','＋ 新建任务'))+
  `<div class="stats">${[
    ['连接设备',online.length,'台','▯',state.devices.length?'桥接程序持续同步设备状态':'等待本地桥接程序连接'],
    ['进行中任务',active.length,'项','↗','观察、规划与操作逐步记录'],
    ['已完成任务',succeeded,'项','✓','最近 150 条任务中的完成数'],
    ['积累技能',skillsActive,'项','✧',`${state.skills.filter(s=>s.status==='draft').length} 项经验等待审核`]
  ].map(([label,value,unit,icon,foot])=>`<div class="stat"><div class="stat-top">${label}<span class="stat-icon">${icon}</span></div><div class="stat-value">${value}<small>${unit}</small></div><div class="stat-foot"><span class="dot"></span>${foot}</div></div>`).join('')}</div>
  <div class="overview-grid"><div>
    <form id="quick-task" class="task-composer"><div class="composer-top"><span class="spark">✧</span><div><h3>今天，让手机帮你做什么？</h3><p>用自然语言描述目标，AI 会自己规划步骤。</p></div></div><textarea name="goal" class="composer-input" placeholder="例如：打开系统设置，查看手机的 Android 版本，并告诉我结果。" required minlength="2" maxlength="4000" aria-label="任务目标"></textarea><div class="composer-bottom"><div class="composer-selects"><select name="device" aria-label="选择设备" required>${deviceOptions()}</select><select name="provider" aria-label="选择模型">${providerOptions('deepseek')}</select></div><button class="primary" type="submit" ${online.length?'':'disabled'}>开始执行 <span>↗</span></button></div></form>
    <section class="panel"><div class="panel-head"><h2>最近任务 <span class="muted"> / RECENT TASKS</span></h2><a href="#tasks" class="text-link">全部任务 →</a></div>${taskTable(state.tasks.slice(0,5))}</section>
    <div class="memory-banner"><span class="large-spark">✧</span><div><h3>不只是执行，更会积累经验</h3><p>把应用入口、操作路径和避坑经验，沉淀为可复用的技能。</p></div><a href="#skills" class="quiet">探索技能记忆 →</a></div>
  </div><div class="overview-side"><section class="panel"><div class="panel-head"><h2>我的设备</h2>${pill(first?.online?'online':'offline')}</div><div class="panel-body"><div class="device-summary"><span class="device-icon">▯</span><div><strong>${esc(first?.name||'等待你的第一台手机')}</strong><small>${first?esc(first.transport+' · '+first.bridge):'Android · 原生手机桥接'}</small></div></div><div class="phone"><span class="phone-symbol">⌁</span><p>${first?.online?(first.ready?'设备已就绪<br>可以安排新的任务':'设备已连接<br>等待解锁或当前操作结束'):'连接之后<br>从这里开始探索'}</p></div><button class="secondary full" data-action="${first?.online?'screen':'connect'}" data-id="${esc(first?.id||'')}">${first?.online?'查看手机屏幕 ↗':'连接设备 →'}</button><div class="device-meta"><span>出站加密连接</span><span>${first?.online?'桥接端在线':'未连接'}</span></div></div></section>
    <section class="panel notes"><div class="panel-body"><div class="section-label">THE LEARNING LOOP</div><h3>越用，越懂你的手机。</h3><p>已启用的技能会在相关任务中被检索，执行结果会回到记忆中。</p><div class="workflow"><span>观察</span><b>→</b><span>行动</span><b>→</b><span>总结</span><b>↺</b></div></div></section></div></div>`;
}

function tasks() {
  const rows=state.tasks.filter(t=>(filter==='all'||t.status===filter)&&t.goal.toLowerCase().includes(search.toLowerCase()));
  return head('TASK CENTER','任务中心','从一个目标开始，跟踪每一步观察、规划和操作。',primary('new-task','＋ 新建任务'))+
    `<div class="toolbar"><div class="filters">${[['all','全部任务'],['running','执行中'],['queued','排队中'],['succeeded','已完成'],['failed','失败'],['blocked','需要介入']].map(([v,n])=>`<button class="filter ${filter===v?'active':''}" data-action="filter" data-value="${v}">${n}</button>`).join('')}</div><input class="search" id="search" placeholder="搜索任务…" value="${esc(search)}" aria-label="搜索任务"></div><section class="panel">${taskTable(rows)}</section>`;
}

function taskDetail(id) {
  const t=state.tasks.find(x=>x.id===id)||archivedTasks.get(id);
  if(!t) {
    api('/tasks/'+encodeURIComponent(id)).then(task=>{archivedTasks.set(id,task);if(selectedTask===id)render();}).catch(e=>{if(selectedTask===id)$('#main').innerHTML=empty('无法读取任务',esc(e.message),'<a class="secondary" href="#tasks">返回任务列表</a>');});
    return empty('正在读取任务','正在从持久化记录中查找来源任务…');
  }
  renderedTaskFingerprint=JSON.stringify([t.status,t.summary,t.review,state.skills.filter(s=>s.source_task===id)]);
  return head('TASK / '+esc(id),'任务执行记录',esc(deviceName(t.device))+' · '+esc(providerName(t.provider)),['running','queued'].includes(t.status)?`<button class="danger" data-action="stop" data-id="${id}">■ 停止任务</button>`:'<a class="secondary" href="#tasks">← 返回任务</a>')+
    `<div class="detail-layout"><section class="panel"><div class="panel-head"><h2>操作时间线</h2>${pill(t.status)}</div><div class="logs" id="logs"><p class="muted">正在读取日志…</p></div></section><div><section class="panel"><div class="panel-head"><h2>任务目标</h2></div><div class="panel-body"><div class="detail-title">${esc(t.goal)}</div><p class="hint">创建于 ${date(t.created)}<br>最多 ${t.max_steps} 步 · ${t.finished?'结束于 '+date(t.finished):'结果将在结束后生成'}</p></div></section><section class="panel"><div class="panel-head"><h2>操作总结</h2></div><div class="panel-body summary-box">${esc(t.summary||'任务结束后，这里会显示结果与原因。')}${t.review?'\n\n复盘\n'+esc(t.review):''}</div></section><section class="panel"><div class="panel-head"><h2>本次沉淀的技能</h2></div><div class="panel-body">${state.skills.filter(s=>s.source_task===id).map(s=>`<button class="quiet" data-action="skill" data-id="${s.id}">✧ ${esc(s.title)} →</button>`).join('')||'<p class="muted">执行后自动提炼可复用经验；没有证据的内容不会写入技能。</p>'}</div></section></div></div>`;
}
async function loadEvents(id) {
  try {
    const events=await api(`/tasks/${id}/events`);
    if(selectedTask!==id || !$('#logs'))return;
    $('#logs').innerHTML=events.map(e=>`<div class="log"><div class="log-head"><span>${esc(kindNames[e.kind]||e.kind)}</span><time>${date(e.at)}</time></div><p>${esc(e.message)}</p>${e.detail?`<details><summary>查看详细记录</summary><pre>${esc(JSON.stringify(JSON.parse(e.detail),null,2))}</pre></details>`:''}</div>`).join('')||'<p class="muted">等待第一条执行记录。</p>';
  }catch(e){toast(e.message);}
}

function schedules() {
  return head('SCHEDULED AUTOMATIONS','让任务按时发生','支持每日定时和固定间隔；同一计划不会重复堆积未完成任务。',primary('new-schedule','＋ 创建计划'))+
  `<div class="notice">计划保存在服务器，关闭浏览器后继续生效。错过的执行时间只补触发一次；手机需保持在线并可操作。</div><section class="panel">${state.schedules.length?state.schedules.map(s=>`<div class="list-row"><div><h3>${esc(s.name)} ${pill(s.enabled?'active':'disabled')}</h3><p class="muted">${esc(s.goal)}</p><p class="hint no-margin">${s.kind==='daily'?`每天 ${esc(s.daily_time)} · ${esc(s.timezone)}`:`每 ${s.interval_seconds/60} 分钟`} · 下次 ${date(s.next_run)} · ${esc(deviceName(s.device))}</p></div><div class="row-actions"><button class="secondary" data-action="toggle-schedule" data-id="${s.id}">${s.enabled?'暂停':'启用'}</button><button class="quiet" data-action="delete-schedule" data-id="${s.id}">删除</button></div></div>`).join(''):empty('把重复的事情，交给计划','选择设备、描述目标，设置执行频率。服务器会在指定时间创建任务。',primary('new-schedule','创建第一个计划'))}</section>`;
}

function skills() {
  const rows=state.skills.filter(s=>(filter==='all'||s.status===filter)&&(s.title+s.trigger+s.app).toLowerCase().includes(search.toLowerCase()));
  return head('LONG-TERM MEMORY','每一次经验，都成为能力。','按场景检索、带证据总结、保留版本。让 AI 逐渐熟悉你的手机。',primary('new-skill','＋ 记录技能'))+
  `<div class="notice">${state.auto_activate?'自主学习已开启：成功任务提炼的技能会自动启用，失败经验保留为草稿。':'审核模式：AI 自动提炼经验为草稿，审核启用后用于后续任务。服务器可通过 AUTO_ACTIVATE_SKILLS 开启自主学习。'} 统计表示检索到该技能的任务结果，不代表技能因果效果。</div><div class="toolbar"><div class="filters">${[['all','全部技能'],['active','已启用'],['draft','待审核'],['disabled','已停用']].map(([v,n])=>`<button class="filter ${filter===v?'active':''}" data-action="filter" data-value="${v}">${n}${v==='all'?' · '+state.skills.length:''}</button>`).join('')}</div><input class="search" id="search" placeholder="搜索场景、应用或经验…" value="${esc(search)}" aria-label="搜索技能"></div>${rows.length?`<div class="cards">${rows.map(s=>`<article class="skill-card"><div class="skill-card-top"><span class="skill-mark">✧</span>${pill(s.status)}</div><h3>${esc(s.title)}</h3><p>${esc(s.trigger)}</p><div class="skill-bottom"><span>v${s.version} · 检索 ${s.uses} 次</span><button class="quiet" data-action="skill" data-id="${s.id}">查看技能 ↗</button></div></article>`).join('')}</div>`:`<section class="panel">${empty('你的经验库，从第一次探索开始','任务执行后，AI 会提炼应用入口、有效路径和失败原因。你也可以先录入已有经验。',primary('new-skill','＋ 手动记录经验'))}</section>`}`;
}

function devices() {
  return head('CONNECTED DEVICES','手机与云端，在这里连接','手机桥接应用直接访问云服务器，无需常开电脑。',primary('connect','＋ 连接设备'))+
  `<div class="notice">推荐连接：云端 AI 与控制台 ⇄ HTTPS ⇄ 手机上的 PhonePilot APK。手机只读取界面和执行动作；电脑 ADB 桥接仍可作为备用方案。</div><section class="panel">${state.devices.length?state.devices.map(d=>`<div class="list-row"><div class="device-summary no-margin"><span class="device-icon">▯</span><div><h3>${esc(d.name)} ${pill(d.online?'online':'offline')}</h3><p class="muted">${esc(d.transport)} · ${esc(d.bridge)} · ${esc(d.serial)}</p><p class="hint no-margin">最近心跳 ${date(d.last_seen)}${d.state==='unauthorized'?' · 请在手机上允许 USB 调试':''}${d.locked?' · 已锁屏，任务等待解锁':''}${d.interactive===false?' · 屏幕关闭':''}${d.busy?' · AI 正在使用此设备':''}${d.unsettled?' · 桥接命令待确认':''}</p></div></div><button class="secondary" data-action="screen" data-id="${esc(d.id)}" ${d.online?'':'disabled'}>屏幕与手动控制 ↗</button>${d.unsettled&&!d.busy?`<button class="quiet" data-action="recover-device" data-id="${esc(d.id)}">清除待确认命令</button>`:''}</div>`).join(''):empty('还没有连接的设备','在 Android 手机上安装桥接 APK，配置服务器地址并启用无障碍服务，启动后将自动出现在这里。',primary('connect','查看连接步骤'))}</section>`;
}

function providers() {
  return head('MODEL PROVIDERS','选择适合任务的大脑','支持 DeepSeek 与 OpenAI 兼容接口，可为不同任务选择不同模型。',primary('new-provider','＋ 添加接口'))+
  `<div class="notice">API Key 通过服务器环境变量配置。仅支持 OpenAI Chat Completions 兼容协议与 JSON 输出；其他厂商可接入兼容网关。只有支持图片输入的模型才能开启视觉模式。</div><div class="cards">${state.providers.map(p=>`<article class="provider-card"><div class="row-actions no-margin"><span class="skill-mark">${p.id==='deepseek'?'≈':'✳'}</span>${pill(p.configured?'active':'draft')}</div><h3>${esc(p.name)}</h3><p>${esc(p.model)}<br>${esc(p.base_url)}</p><p><code>${esc(p.key_env)}</code><br>${p.configured?'环境变量已配置':'环境变量未配置'} · ${p.vision?'截图 + 界面结构':'界面结构识别'}</p><div class="row-actions"><button class="secondary" data-action="provider" data-id="${p.id}">编辑配置</button><button class="quiet" data-action="test-provider" data-id="${p.id}">测试连接 ↗</button></div></article>`).join('')}</div>`;
}

function taskForm(schedule=false) {
  modal(schedule?'创建定时计划':'新建手机任务',`<form id="task-form" data-schedule="${schedule}">${schedule?'<label>计划名称<input name="name" placeholder="每日查看设备状态" required maxlength="100"></label>':''}<label>任务目标<textarea name="goal" placeholder="打开系统设置，查看 Android 版本，并告诉我结果。" required minlength="2" maxlength="4000"></textarea></label><div class="form-row"><label>执行设备<select name="device" required>${deviceOptions()}</select></label><label>使用模型<select name="provider">${providerOptions('deepseek')}</select></label></div><label>最大执行步数<input type="number" name="max_steps" value="25" min="1" max="100" required></label>${schedule?`<div class="form-row"><label>执行频率<select name="kind" id="schedule-kind"><option value="daily">每天定时</option><option value="interval">固定间隔</option></select></label><label id="daily-field">每天执行时间<input type="time" name="daily_time" value="09:00" required></label><label id="interval-field" hidden>间隔（分钟）<input type="number" name="interval_minutes" min="1" max="525600" value="60"></label></div><label>时区<input name="timezone" value="Asia/Shanghai" required></label>`:''}<p class="hint">手机需要保持解锁。AI 在无法识别界面或需要人工介入时停止，并保留日志。</p><p class="error-text form-error" role="alert"></p><div class="form-actions"><button class="secondary" type="button" data-action="close">取消</button><button class="primary" type="submit" ${state.devices.length?'':'disabled'}>${schedule?'创建计划':'创建并执行'} →</button></div></form>`);
}

function skillForm(id) {
  const s=state.skills.find(s=>s.id===id);
  modal(s?'技能详情与版本':'记录一条技能',`<form id="skill-form" data-id="${s?.id||''}"><label>技能名称<input name="title" value="${esc(s?.title||'')}" placeholder="例如：在设置中查找系统版本" required maxlength="150"></label><label>关联应用包名<input name="app" value="${esc(s?.app||'')}" placeholder="com.android.settings"></label><label>适用场景<textarea name="trigger" required>${esc(s?.trigger||'')}</textarea></label><label>操作步骤（每行一步）<textarea name="steps" required rows="5">${esc(s?JSON.parse(s.steps).join('\n'):'')}</textarea></label><label>注意事项与验证方式<textarea name="cautions">${esc(s?.cautions||'')}</textarea></label><label>技能状态<select name="status">${[['draft','待审核：暂不检索'],['active','已启用：在相关任务中检索'],['disabled','已停用：保留历史']].map(([v,t])=>`<option value="${v}" ${s?.status===v?'selected':''}>${t}</option>`).join('')}</select></label>${s?`<div class="skill-evidence"><span>版本 v${s.version} · 检索 ${s.uses} 次 · 成功 ${s.successes} / 失败 ${s.failures}</span></div>${s.source_task?`<p class="hint">来源任务 <a class="text-link" href="#tasks/${s.source_task}" data-action="close">${s.source_task} ↗</a><br>证据步骤：${esc(JSON.parse(s.evidence).join(', '))}</p>`:'<p class="hint">手动录入的经验</p>'}<button type="button" class="quiet" data-action="versions" data-id="${s.id}">查看历史版本 →</button>`:''}<p class="error-text form-error" role="alert"></p><div class="form-actions"><button class="secondary" type="button" data-action="close">取消</button><button class="primary" type="submit">保存技能</button></div></form>`);
}

function providerForm(id) {
  const p=state.providers.find(p=>p.id===id);
  modal(p?'编辑模型接口':'添加模型接口',`<form id="provider-form"><label>配置 ID<input name="id" value="${esc(p?.id||'')}" placeholder="my-model" pattern="[a-zA-Z0-9_-]{1,40}" ${p?'readonly':''} required></label><label>显示名称<input name="name" value="${esc(p?.name||'')}" required></label><label>API 基础地址<input name="base_url" type="url" value="${esc(p?.base_url||'https://api.deepseek.com')}" required></label><label>模型 ID<input name="model" value="${esc(p?.model||'deepseek-chat')}" required></label><label>密钥环境变量名<input name="key_env" value="${esc(p?.key_env||'CUSTOM_API_KEY')}" required pattern="[A-Z][A-Z0-9_]{0,80}_API_KEY"></label><label class="check"><input type="checkbox" name="vision" ${p?.vision?'checked':''}>发送截图给模型（需要模型支持图片输入）</label><p class="hint">填写基础地址，例如 https://api.deepseek.com，不要填写 /chat/completions。环境变量需在服务器上配置并重启进程后生效。</p><p class="error-text form-error" role="alert"></p><div class="form-actions"><button class="secondary" type="button" data-action="close">取消</button><button class="primary" type="submit">保存配置</button></div></form>`);
}

function connectHelp() {
  modal('手机直接连接服务器',`<p class="muted">推荐使用 Android 原生桥接，不需要常开电脑、Root 或日常 ADB。最低 Android 11。</p><p class="hint">1 / 安装从本项目构建的 PhonePilot 手机桥接 APK。</p><p class="hint">2 / 在手机应用中填写服务器 HTTPS 地址、固定桥接 ID（例如 iqoo）及服务器的 BRIDGE_TOKEN。无需填写模型密钥。</p><p class="hint">3 / 阅读权限说明，开启 PhonePilot 无障碍服务，勾选授权说明并启动桥接，然后返回桌面或目标应用。</p><p class="hint">4 / iQOO 用户请在系统设置中允许后台运行，并按系统实际提供的选项设置自启动、电池限制与通知权限。</p><div class="notice">手机锁屏或息屏时，新任务保持排队。应用不能解锁密码锁；系统后台限制可能中断连接。原生输入支持中文，会替换整个聚焦输入框，无需安装 ADBKeyboard。</div><p class="hint">构建和安装步骤见项目 android/README.md。已有电脑 ADB 桥接仍可使用，步骤见项目根目录 README。</p><button class="primary full" data-action="close">已了解，等待手机上线</button>`);
}

async function showScreen(id) {
  modal('手机屏幕与手动控制',`<div id="screen-stage" class="screenshot-stage"><p class="muted">正在读取手机屏幕…</p></div><p class="hint">点按截图进行点击，拖动进行滑动。原生手机桥接的文字输入会替换整个聚焦输入框。AI 执行时手动操作不可用；视觉模式可显示最近观察的截图。</p><div class="manual-keys">${[['BACK','← 返回'],['HOME','⌂ 主屏'],['APP_SWITCH','▢ 最近']].map(([key,text])=>`<button class="secondary" data-action="key" data-id="${esc(id)}" data-key="${key}">${text}</button>`).join('')}</div><form id="text-form" class="inline-form" data-id="${esc(id)}"><input name="text" placeholder="向当前输入框输入文字" maxlength="2000" required aria-label="输入文字"><button class="primary">发送</button></form><p class="error-text form-error" role="alert"></p><button class="quiet" data-action="refresh-screen" data-id="${esc(id)}">↻ 刷新屏幕</button>`);
  await refreshScreen(id);
}
async function refreshScreen(id) {
  const blob=await api(`/devices/${encodeURIComponent(id)}/screen`);
  if(!$('#screen-stage'))return;
  if(screenURL)URL.revokeObjectURL(screenURL);
  screenURL=URL.createObjectURL(blob); $('#screen-stage').innerHTML=`<img id="phone-screen" alt="手机当前屏幕，点按或拖动以操作" src="${screenURL}">`;
  const image=$('#phone-screen'); let start;
  const point=e=>{const r=image.getBoundingClientRect();const scale=Math.min(r.width/image.naturalWidth,r.height/image.naturalHeight);const w=image.naturalWidth*scale,h=image.naturalHeight*scale;return{x:Math.round((e.clientX-r.left-(r.width-w)/2)/scale),y:Math.round((e.clientY-r.top-(r.height-h)/2)/scale)};};
  image.addEventListener('pointerdown',e=>{start=point(e);image.setPointerCapture(e.pointerId);});
  image.addEventListener('pointercancel',()=>{start=null;});
  image.addEventListener('pointerup',async e=>{if(!start)return;const end=point(e),from=start;start=null;const swipe=Math.hypot(end.x-from.x,end.y-from.y)>30;try{await post(`/devices/${encodeURIComponent(id)}/action`,{type:swipe?'swipe':'tap',...from,...(swipe?{x2:end.x,y2:end.y,duration:400}:{}),reason:'控制台手动操作'});await refreshScreen(id);}catch(err){toast(err.message);}});
}

document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-action]'); if(!button)return;
  const {action,id,value,key}=button.dataset;
  try{
    if(action==='new-task')taskForm();
    else if(action==='new-schedule')taskForm(true);
    else if(action==='new-skill')skillForm();
    else if(action==='skill')skillForm(id);
    else if(action==='new-provider')providerForm();
    else if(action==='provider')providerForm(id);
    else if(action==='connect')connectHelp();
    else if(action==='close')closeModal();
    else if(action==='filter'){filter=value;render();}
    else if(action==='stop'){await post(`/tasks/${id}/stop`);toast('已请求停止；当前已发出的操作可能仍会完成');await refresh();}
    else if(action==='toggle-schedule'){await post(`/schedules/${id}/toggle`);await refresh();}
    else if(action==='delete-schedule'){if(confirm('删除此定时计划？已创建的任务会保留。')){await api(`/schedules/${id}`,{method:'DELETE'});await refresh();}}
    else if(action==='test-provider'){button.disabled=true;button.textContent='测试中…';await post(`/providers/${id}/test`);toast('模型 API 连接成功');}
    else if(action==='recover-device'){if(confirm('请先检查手机，并确认本地桥接程序没有仍在执行的操作，再清除待确认状态。是否继续？')){await post(`/devices/${encodeURIComponent(id)}/recover`);await refresh();}}
    else if(action==='screen')await showScreen(id);
    else if(action==='refresh-screen')await refreshScreen(id);
    else if(action==='key'){await post(`/devices/${encodeURIComponent(id)}/action`,{type:'key',key,reason:'控制台手动按键'});await refreshScreen(id);}
    else if(action==='versions'){const versions=await api(`/skills/${id}/versions`);modal('技能历史版本',versions.map(v=>{const s=JSON.parse(v.snapshot);return `<div class="version-entry"><strong>v${v.version} · ${date(v.at)}</strong> ${pill(s.status)}<p>${esc(s.title)}<br>${esc(s.trigger)}</p><p>${esc(JSON.parse(s.steps).map((x,i)=>`${i+1}. ${x}`).join('\n'))}</p><p>${esc(s.cautions)}</p></div>`;}).join(''));}
  }catch(err){toast(err.message);}finally{if(action==='test-provider'){button.disabled=false;button.textContent='测试连接 ↗';}}
});

document.addEventListener('submit',async e=>{
  const form=e.target;if(!['quick-task','task-form','skill-form','provider-form','text-form'].includes(form.id))return;
  e.preventDefault();const fields=Object.fromEntries(new FormData(form));const submit=$('[type=submit]',form)||$('button',form);submit.disabled=true;const error=$('.form-error',form);if(error)error.textContent='';
  try{
    if(form.id==='quick-task'||form.id==='task-form'){
      fields.max_steps=Number(fields.max_steps||25);
      if(form.dataset.schedule==='true'){fields.interval_seconds=Number(fields.interval_minutes||60)*60;delete fields.interval_minutes;await post('/schedules',fields);closeModal();location.hash='schedules';toast('定时计划已创建');}
      else{const task=await post('/tasks',fields);closeModal();location.hash='tasks/'+task.id;toast('任务已加入执行队列');}
    }else if(form.id==='skill-form'){
      fields.steps=fields.steps.split('\n').map(x=>x.trim()).filter(Boolean);const id=form.dataset.id;
      await api('/skills'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(fields)});closeModal();toast('技能已保存，新版本将用于后续任务');
    }else if(form.id==='provider-form'){fields.vision=fields.vision==='on';await api('/providers',{method:'PUT',body:JSON.stringify(fields)});closeModal();toast('模型配置已保存');}
    else if(form.id==='text-form'){await post(`/devices/${encodeURIComponent(form.dataset.id)}/action`,{type:'text',text:fields.text,reason:'控制台手动输入'});form.reset();await refreshScreen(form.dataset.id);}
    await refresh();
  }catch(err){if(error)error.textContent=err.message;else toast(err.message);}finally{submit.disabled=false;}
});

document.addEventListener('input',e=>{if(e.target.id==='search'){search=e.target.value;const pos=e.target.selectionStart;render();$('#search').focus();$('#search').setSelectionRange(pos,pos);}});
document.addEventListener('change',e=>{if(e.target.id==='schedule-kind'){$('#daily-field').hidden=e.target.value!=='daily';$('#interval-field').hidden=e.target.value!=='interval';}});
$('#login').addEventListener('cancel',e=>e.preventDefault());
$('#login-form').addEventListener('submit',async e=>{e.preventDefault();token=new FormData(e.target).get('token').trim();$('#login-error').textContent='';const button=$('button',e.target);button.disabled=true;try{state=await api('/state');sessionStorage.setItem('phonepilot-token',token);$('#login').close();e.target.reset();await refresh();}catch(err){$('#login-error').textContent=err.message;}finally{button.disabled=false;}});
$('#logout').addEventListener('click',()=>{token='';state={tasks:[],skills:[],devices:[],providers:[],schedules:[]};sessionStorage.removeItem('phonepilot-token');closeModal();render();showLogin();});
$('#close-modal').addEventListener('click',closeModal);
window.addEventListener('hashchange',()=>{filter='all';search='';render();});
function tick(){ $('#clock').textContent=new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric'}); }
tick();render();if(token)refresh();else showLogin();
setInterval(async()=>{
  if(!token||document.hidden)return;
  // Preserve form input, scroll positions, expanded logs, and open dialogs during polling.
  await refresh(false);
  if(selectedTask&&currentPage==='tasks'&&!$('#modal').open){
    const t=state.tasks.find(t=>t.id===selectedTask)||archivedTasks.get(selectedTask);
    if(t&&JSON.stringify([t.status,t.summary,t.review,state.skills.filter(s=>s.source_task===selectedTask)])!==renderedTaskFingerprint)render();
    else if(!$('#logs details[open]')){const logs=$('#logs');const scroll=logs?.scrollTop;await loadEvents(selectedTask);if(logs)logs.scrollTop=scroll;}
  }else if(!$('#modal').open&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){
    const composer=$('#quick-task');const saved=composer?Object.fromEntries(new FormData(composer)):null;
    render();
    if(saved&&$('#quick-task'))for(const [name,value] of Object.entries(saved)){const input=$(`[name="${name}"]`,$('#quick-task'));if(input&&value)input.value=value;}
  }
},4000);
