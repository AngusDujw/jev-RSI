'use strict';
const data=window.COMPARISON;
const records=Object.fromEntries(data.records.map(r=>[r.id,r]));
const baseline=records.jev;
let selected='waypoint',question='x',rawTab='state',rawRight='';
const $=id=>document.getElementById(id);
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json=v=>JSON.stringify(v,null,2);
const labels={x:'X方向',y:'Y方向',z:'Z方向',gripper:'夹爪',transition:'阶段切换'};
const words={negative:'负向',hold:'保持',positive:'正向',open:'张开',close:'闭合',keep:'保持上次命令',continue_phase:'继续本阶段',advance:'进入下一阶段',reobserve:'重新观察',stop:'停止'};
function diffText(a,b){
  const x=a.match(/\S+\s*/g)||[],y=b.match(/\S+\s*/g)||[];
  const dp=Array.from({length:x.length+1},()=>Array(y.length+1).fill(0));
  for(let i=x.length-1;i>=0;i--)for(let j=y.length-1;j>=0;j--)dp[i][j]=x[i]===y[j]?1+dp[i+1][j+1]:Math.max(dp[i+1][j],dp[i][j+1]);
  let left='',right='',i=0,j=0;
  while(i<x.length||j<y.length){if(i<x.length&&j<y.length&&x[i]===y[j]){left+=escape(x[i]);right+=escape(y[j]);i++;j++;}
    else if(i<x.length&&(j===y.length||dp[i+1][j]>=dp[i][j+1]))left+='<del>'+escape(x[i++])+'</del>';
    else right+='<ins>'+escape(y[j++])+'</ins>';}
  return [left,right];
}
function getQuestion(record){return record.questions.find(q=>q.name===question);}
function explanation(record){
  if(question==='gripper')return '根据当前阶段决定夹爪张开、闭合或保持。这里展示的是原始英文问题，没有用中文解释替换模型输入。';
  if(question==='transition')return record.id==='waypoint'||record.id==='raw'?'这一组也改写了阶段切换问题；所以旧消融不只是把XYZ误差换成图像。':'读取当前阶段条件和反馈，判断继续、切换、重新观察或停止。';
  if(record.id==='jev')return '读程序已算好的「目标−当前」误差，选正向、负向或保持；不是让Jev自己看图求坐标。';
  if(record.id==='full')return '这一题仍直接给数值误差和正负阈值规则；模型另外收到了两张图像。';
  return '这一题已不提供XYZ数值，改成要求根据图像、标定和机器人状态选方向。这是旧实验真实用过的长版问题。';
}
function pane(record,copy){
  const q=getQuestion(record),answer=record.answers[question],axes=record.state.translation_axes;
  let axisHTML='';
  for(const a of ['x','y','z']){
    const value=axes?.[a]?.goal_minus_current_mm;
    axisHTML+=value===undefined?`<div class="axis removed"><small>${a.toUpperCase()} / mm</small><b>未提供</b><em>XYZ反馈已删除</em></div>`:`<div class="axis"><small>${a.toUpperCase()} / mm</small><b>${value>0?'+':''}${value.toFixed(2)}</b><em>目标 − 当前</em></div>`;
  }
  let cameras='';
  if(!record.views.length)cameras='<div class="no-image"><strong>没有图像传给Jev</strong><p>相机图像由前端算法处理。Jev收到的是处理后的误差、阶段条件和反馈。</p><div class="pipeline">图像 → 处理程序 → 数值 → Jev</div></div>';
  else cameras='<div class="cameras">'+record.views.map(v=>`<figure class="camera"><button class="image-open" data-src="${escape(v.src)}" data-caption="${escape(v.camera+' · '+v.width+'×'+v.height+' · 真实输入PNG')}" aria-label="放大${escape(v.camera)}"><img src="${escape(v.src)}" alt="${escape(record.title+'实际输入：'+v.camera)}"><span class="zoom-label">点击放大 ↗</span></button><figcaption>${escape(v.camera)}<br>${v.camera==='agentview'?'固定外部相机':'随手臂运动的腕相机'} · step ${v.observation_counter}</figcaption></figure>`).join('')+'</div><p class="camera-description">'+(record.id==='waypoint'?'白圈＝实测控制点；黄叉＝前端计算的本阶段目标。标记图仍包含处理后的目标信息。':'实际发送的原始RGB；无深度图，未在网页中补画任何标记。')+'</p>';
  const probs=answer?.probabilities||{};
  return `<div class="pane-head"><div><h2>${escape(record.title)}</h2><p>${escape(record.summary)}</p></div><span class="tag">${escape(record.model)}</span></div>
  <div class="part-label">INPUT / 这个决策点的XYZ反馈</div><div class="axis-row">${axisHTML}</div><p class="tolerance">${record.id==='jev'||record.id==='full'?'Hold容差：4mm · 到位容差：8mm':'仍保留容差：4mm / 8mm，但没有XYZ数值'} · 图像输入：${record.views.length}张</p>
  <div class="part-label">QUESTION / ${escape(labels[question])} · 实际问题原文</div><div class="question-copy" lang="en">${copy}</div><p class="explanation">中文解释：${escape(explanation(record))}</p>
  <div class="choices">${q.choices.map(c=>`<div class="choice">${escape(c.value)}<span>${escape(c.description)}</span></div>`).join('')}</div>
  <div class="answer"><span class="answer-label">真实回答</span><b>${escape(answer?.choice||'未返回')}</b><span>${escape(words[answer?.choice]||'')}</span><small>confidence ${answer?.confidence??'—'}</small></div>
  <div class="probabilities">${Object.entries(probs).map(([k,v])=>`<span>${escape(k)} ${(v*100).toFixed(0)}%</span>`).join('')}</div>
  <div class="part-label">IMAGES / 模型实际收到的图像</div>${cameras}`;
}
function fields(){
  const r=records[selected];
  const rows=[['XYZ数值误差','translation_axes','提供：+119.57 / −0.84 / −90.14 mm',r.state.translation_axes?'提供，同原Jev':'删除'],
    ['XYZ方向文字','translation_axes.*.relation','提供：坐标更高 / 容差内 / 更低',r.state.translation_axes?'提供，同原Jev':'删除'],
    ['原阶段合同','phase_contract','提供：接近源物上方、夹爪张开，到位后切阶段',r.state.phase_contract?'提供，原文可在下方展开':'删除，改为概括性的阶段目标'],
    ['相机图像','input_image','0张',`${r.views.length}张${selected==='waypoint'?'，附控制点/目标标记':'原始RGB'}`],
    ['标定与机器人状态','camera_views / measured_robot','本次请求没有完整K/T及关节状态', '新增：相机K/T、EEF位姿、关节与夹爪状态'],
    ['最近动作记录','recent_actions','提供，本次为空列表',Object.hasOwn(r.state,'recent_actions')?'保留，本次为空列表':'删除'],
    ['问题措辞','questions','原Jev问题',`改写了：${r.changed_questions.map(x=>labels[x]||x).join('、')}`]];
  $('field-comparison').innerHTML='<table class="field-table"><thead><tr><th>输入 / 字段</th><th>原Jev</th><th>'+escape(r.title)+'</th></tr></thead><tbody>'+rows.map(([title,key,a,b])=>`<tr><td><b>${title}</b><br><code>${key}</code></td><td>${a}</td><td class="${b.startsWith('删除')?'status-removed':'status-kept'}">${escape(b)}</td></tr>`).join('')+'</tbody></table><details class="field-detail"><summary>查看实际删除 / 新增的顶层字段名</summary><p>删除字段</p><div class="chips">'+r.removed_keys.map(k=>'<span class="chip">'+escape(k)+'</span>').join('')+'</div><p>新增字段</p><div class="chips">'+r.added_keys.map(k=>'<span class="chip">'+escape(k)+'</span>').join('')+'</div></details>';
}
function rawContent(r){
  if(rawTab==='state')return r.state;
  if(rawTab==='questions')return r.questions;
  if(rawTab==='response')return r.response;
  if(rawTab==='text')return r.id==='jev'?{state:r.state,questions:r.questions}:r.text_parts;
  return {source_run:r.source,files:r.sources,init:r.init,stage:r.stage,decision:r.decision};
}
function raw(){
  const r=records[selected];
  $('raw-left').textContent=json(rawContent(baseline));rawRight=json(rawContent(r));$('raw-right').textContent=rawRight;
  $('raw-right-title').textContent=r.title;
  $('left-download').href=baseline.sources['request.json'].file;$('right-download').href=r.sources['request.json'].file;
  $('raw-note').textContent=rawTab==='text'?'文本按实际请求中的内容顺序展示。英文文字是实际输入；本页中文导读没有发送给模型。':'下载链接保留完整实际请求，包括多模态base64图像。原Jev下载文件从归档JSON值重新排版；provider文件按原始字节保存。';
  for(const b of document.querySelectorAll('[data-raw]'))b.classList.toggle('active',b.dataset.raw===rawTab);
}
function render(){
  const r=records[selected],a=getQuestion(baseline).instructions,b=getQuestion(r).instructions;
  const texts=$('diff').checked?diffText(a,b):[escape(a),escape(b)];
  $('left-pane').innerHTML=pane(baseline,texts[0]);$('right-pane').innerHTML=pane(r,texts[1]);
  for(const button of document.querySelectorAll('[data-condition]')){const active=button.dataset.condition===selected;button.classList.toggle('active',active);button.setAttribute('aria-pressed',active);}
  for(const button of document.querySelectorAll('[data-question]')){const active=button.dataset.question===question;button.classList.toggle('active',active);button.setAttribute('aria-pressed',active);}
  fields();raw();
  for(const button of document.querySelectorAll('.image-open'))button.onclick=()=>{$('large-image').src=button.dataset.src;$('large-image').alt=button.dataset.caption;$('large-caption').textContent=button.dataset.caption;$('image-dialog').showModal();};
}
$('conditions').innerHTML=['full','waypoint','raw'].map((id,i)=>`<button class="condition" data-condition="${id}" aria-pressed="false"><span class="index">0${i+1} / ${id==='full'?'RGB + XYZ':id==='waypoint'?'RGB + MARKERS':'RAW RGB'}</span>${escape(records[id].title.replace('Luna · ',''))}</button>`).join('');
$('question-buttons').innerHTML=Object.keys(labels).map(id=>`<button class="question-button" data-question="${id}" aria-pressed="false">${escape(labels[id])}</button>`).join('');
$('raw-tabs').innerHTML=[['state','输入字段'],['questions','全部问题'],['text','全部文本'],['response','真实回答'],['source','来源文件']].map(([id,label])=>`<button class="raw-tab" data-raw="${id}">${label}</button>`).join('');
for(const b of document.querySelectorAll('[data-condition]'))b.onclick=()=>{selected=b.dataset.condition;render();};
for(const b of document.querySelectorAll('[data-question]'))b.onclick=()=>{question=b.dataset.question;render();};
for(const b of document.querySelectorAll('[data-raw]'))b.onclick=()=>{rawTab=b.dataset.raw;raw();};
$('diff').onchange=render;
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(rawRight);$('copy-status').textContent='已复制';}catch{$('copy-status').textContent='复制不可用，可在下方选中文字';}setTimeout(()=>$('copy-status').textContent='',2500);};
$('close-image').onclick=()=>$('image-dialog').close();
$('image-dialog').onclick=e=>{if(e.target===$('image-dialog'))$('image-dialog').close();};
$('provenance').textContent=json({audit:data.audit,sources:data.records.map(r=>({condition:r.title,source:r.source,init:r.init,decision:r.decision,source_request_sha256:r.source_request_sha256,source_response_sha256:r.source_response_sha256,files:r.sources,images:r.views.map(v=>({camera:v.camera,sha256:v.sha256,observation_counter:v.observation_counter})),later_episode_error:r.result.error}))});
render();
