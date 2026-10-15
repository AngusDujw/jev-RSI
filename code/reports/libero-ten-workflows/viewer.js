'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const cases = window.CASES;
  let current, selected = 0, filter = 'all', raw = 'request';
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const pretty = value => JSON.stringify(value, null, 2);
  const stageOf = d => d.request.state.stage || d.request.state.operation;
  const stageName = name => {
    const key = name.split(':').at(-1);
    return ({observe:'观察',select_handle:'选把手',prepare:'准备推头',select:'选择候选',approach:'靠近',align:'对齐',contact:'接触',descend:'下降',grasp:'闭爪抓取',test_lift:'试抬',lift:'抬升',carry:'搬运',orient_receiver:'接收姿态对齐',lower:'下降放置',release:'释放',retreat:'退离',pull:'外拉',turn:'转动',verify:'验证',clear_opening:'让开开口',retry:'重试',recover_up:'恢复抬升',recover_open:'恢复张爪',push:'推移',finish_attempt:'结束尝试'})[key] || key;
  };
  function task(id) {
    current = cases.find(c => c.id === +id) || cases[0]; selected = 0; filter = 'all'; raw = 'request';
    history.replaceState(null, '', '#task='+current.id);
    document.querySelectorAll('.task').forEach(b => { const on = +b.dataset.id === current.id; b.classList.toggle('active',on); b.setAttribute('aria-pressed',on); });
    $('title').textContent = current.id+' / '+current.title;
    $('family').textContent = current.method.family;
    $('public-task').textContent = current.decisions[0].request.state.task;
    $('status').textContent = current.id===1202 ? '成功示例 · 尚未稳定' : '固定版五个未见初态 5/5';
    $('status').classList.toggle('warn',current.id===1202);
    $('metrics').replaceChildren();
    [[current.result.jev_calls,'本回合 Jev 调用'],[current.result.native_steps,'原生执行步'],[current.stages.length,'出现的阶段'],[current.duration+'s','快照拼接视频']].forEach(([v,k])=>{ const box=el('div',undefined,'metric');box.append(el('b',String(v)),el('span',k));$('metrics').append(box); });
    $('aim').textContent=current.method.aim; $('steps').replaceChildren();
    current.method.steps.forEach((s,i)=>{const li=el('li');li.append(el('em',String(i+1).padStart(2,'0')),el('span',s));$('steps').append(li);});
    $('prior').textContent=current.method.prior;
    $('source-files').replaceChildren();
    current.method.files.forEach(f=>{const a=el('a',f+' ↗');a.href='../../scripts/'+f;$('source-files').append(a);});
    $('commit').textContent='源回合策略 commit: '+(current.commit || '见原始 manifest')+'；主分支源码可能晚于该冻结版，请以此 commit / SHA256 为准。';
    $('video').src=current.video;
    $('video').poster=current.shots.at(-1).src;
    $('video-note').textContent='init '+current.init+' · 官方 success=true / program_finished=true。按20Hz仿真时间拼接快照，省去模型等待。'+(current.id===1098?'仅9个观测时刻，属于阶段关键帧录像。':'并非连续逐帧录屏。');
    $('stages').replaceChildren();$('stage-filter').replaceChildren(new Option('全部阶段','all'));
    current.stages.forEach(s=>{const b=el('button',undefined,'stage-btn');b.dataset.stage=s.name;b.append(el('span',stageName(s.name)),el('small',s.name+' · '+s.count));b.onclick=()=>{filter=s.name;$('stage-filter').value=filter;setDecision(s.first);};$('stages').append(b);$('stage-filter').append(new Option(stageName(s.name)+' / '+s.name,s.name));});
    $('shots').replaceChildren();current.shots.forEach(s=>{const f=el('figure');const img=el('img');img.src=s.src;img.alt=current.title+'，native tick '+s.tick;img.loading='lazy';f.append(img,el('figcaption','tick '+s.tick+' / '+s.original));$('shots').append(f);});
    $('evidence').replaceChildren();current.evidence.forEach(e=>{const d=el('details');d.append(el('summary',e.name),el('pre',pretty(e.data)));$('evidence').append(d);});
    $('result').textContent=pretty(current.result);$('run-path').textContent='源回合：code/runs/'+current.source_run;
    setDecision(0);
  }
  function setDecision(index) {
    selected=Math.max(0,Math.min(current.decisions.length-1,index));
    const d=current.decisions[selected];
    if(filter!=='all'&&d.stage!==filter){filter='all';$('stage-filter').value=filter;}
    $('decision').replaceChildren();current.decisions.forEach((x,i)=>{if(filter==='all'||x.stage===filter)$('decision').append(new Option(x.id+' / '+stageName(x.stage),String(i)));});$('decision').value=String(selected);
    const state=d.request.state; const s=current.stages.find(s=>s.name===stageOf(d));
    $('contract-title').textContent=stageName(s.name)+' / '+s.name;
    $('contract').textContent=state.stage_contract||state.phase_contract||state.operation_contract||'该请求无合同字段';
    document.querySelectorAll('.stage-btn').forEach(b=>{const on=b.dataset.stage===s.name;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});
    $('trace-meta').textContent=(selected+1)+' / '+current.decisions.length+' · '+d.id;
    $('axes').replaceChildren();Object.entries(state.translation_axes||{}).forEach(([axis,v])=>{const tr=el('tr');[axis,String(v.goal_minus_current_mm),v.relation].forEach(t=>tr.append(el('td',t)));$('axes').append(tr);});
    $('answers').replaceChildren();Object.entries(d.response.answers||{}).forEach(([k,v])=>{const b=el('span',undefined,'answer');b.append(el('span',k+' →'),el('b',v.choice));$('answers').append(b);});
    const u=d.response.usage||{};$('model').textContent=(d.response.model||'')+' · 输入 '+(u.input_tokens??'未记录')+' tokens · 输出 '+(u.output_tokens??'未记录')+' tokens';
    const visible=current.decisions.map((x,i)=>({x,i})).filter(({x})=>filter==='all'||x.stage===filter).map(({i})=>i); const p=visible.indexOf(selected);$('prev').disabled=p<=0;$('next').disabled=p>=visible.length-1;
    renderRaw();
  }
  function renderRaw() {
    const d=current.decisions[selected];$('raw').textContent=pretty(d[raw]);$('raw').scrollTop=0;
    document.querySelectorAll('[data-raw]').forEach(b=>{const on=b.dataset.raw===raw;b.classList.toggle('active',on);b.setAttribute('aria-selected',on);});
    $('hash').textContent=raw==='execution'?'branches.jsonl 中匹配该 decision_id 的真实执行记录；空数组表示无匹配，绝不推测补写。':'原始文件 SHA256: '+d[raw+'_sha256'];
    $('source').href=raw==='execution'?'../../runs/'+current.source_run+'/episode/branches.jsonl':d.source+raw+'.json';
  }
  cases.forEach(c=>{const b=el('button',undefined,'task');b.dataset.id=c.id;b.append(el('span','GOAL '+c.id),el('strong',c.title));b.onclick=()=>task(c.id);$('task-nav').append(b);});
  $('total').textContent=cases.reduce((n,c)=>n+c.decisions.length,0)+' 组原始 Jev 输入 / 输出';
  $('stage-filter').onchange=()=>{filter=$('stage-filter').value;setDecision(current.decisions.findIndex(d=>filter==='all'||d.stage===filter));};
  $('decision').onchange=()=>setDecision(+$('decision').value);
  ['prev','next'].forEach(id=>$(id).onclick=()=>{const options=[...$('decision').options].map(o=>+o.value);const p=options.indexOf(selected);if(options[p+(id==='prev'?-1:1)]!==undefined)setDecision(options[p+(id==='prev'?-1:1)]);});
  document.querySelectorAll('[data-raw]').forEach(b=>b.onclick=()=>{raw=b.dataset.raw;renderRaw();});
  $('download').onclick=()=>{const url=URL.createObjectURL(new Blob([pretty(current.decisions[selected][raw])],{type:'application/json'}));const a=el('a');a.href=url;a.download='goal'+current.id+'-'+current.decisions[selected].id+'-'+raw+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  task(new URLSearchParams(location.hash.slice(1)).get('task'));
})();
