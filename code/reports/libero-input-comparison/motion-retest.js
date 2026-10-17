'use strict';
const names={full:'保留误差＋RGB',marker:'删XYZ＋目标标记',axes:'删XYZ＋标记与轴图例'};
const tasks={1098:'开中层抽屉',1144:'碗放炉灶',1163:'酒瓶放柜顶',1202:'开抽屉并放碗',1252:'碗放柜顶',1296:'推盘到炉前',1335:'奶酪放碗',1383:'转炉灶旋钮',1423:'碗放盘',1458:'酒瓶放架'};
const $=id=>document.getElementById(id);
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let examples=[],condition='axes';
async function progress(){
 try{const res=await fetch('motion-progress.json',{cache:'no-store'});if(!res.ok)throw Error('结果快照暂不可用');const d=await res.json(),c=d.conditions;
 $('run-stamp').textContent='上次同步：'+new Date(d.updated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · 实际运行回合统计';
 $('run-cards').innerHTML=Object.keys(names).map(k=>{const original=c[k]||{completed:0,native:0,joint:0,categories:{}},r=original.effective||original;return `<article class="run-card"><h2>${names[k]}</h2><p>已结束 / 计划</p><strong>${r.completed} / 30</strong><p>原生成功 ${r.native} · 程序也完整完成 ${r.joint}</p><p>当前接口/格式故障 ${r.categories.transport_or_schema_failure||0} · 启动故障 ${r.categories.environment_or_startup_failure||0}</p>${original.transport_replacements?`<p>原批：原生 ${original.native}、完整 ${original.joint} / 30；接口中断 ${original.categories.transport_or_schema_failure||0}</p><p>独立连接补跑 ${original.transport_replacements.completed}；全部原始尝试均保留</p>`:''}</article>`;}).join('');
 const selected=Object.values(c).map(r=>r.effective||r),total=selected.reduce((s,r)=>s+r.completed,0),faults=selected.reduce((s,r)=>s+(r.categories.transport_or_schema_failure||0)+(r.categories.environment_or_startup_failure||0)+(r.categories.external_termination||0),0),attempts=Object.values(c).reduce((s,r)=>s+(r.attempted_total||r.completed),0);$('run-state').textContent=total===90&&faults===0?'本轮90个固定配对回合已完整结束（共'+attempts+'次原生尝试，含保留的连接中断）。主数字仅替换明确连接中断；正常失败没有重跑。':'当前：'+total+' / 90个配对回合已结束，其中接口/启动/外部中断'+faults+'个；共'+attempts+'次原生尝试。连接补齐情况与原批结果分列。';
 $('run-tasks').innerHTML=Object.keys(tasks).map(t=>'<tr><td>'+t+' · '+tasks[t]+'</td>'+Object.keys(names).map(k=>{const group=c[k]?.effective||c[k],r=group?.per_task[t];return '<td>'+(r?r.native+' / '+r.joint+' / '+r.completed:'尚未结束')+'</td>';}).join('')+'</tr>').join('');
 }catch(e){$('run-stamp').textContent=e.message;}
}
function sample(){
 const r=examples.find(x=>x.condition===condition);if(!r)return;
 $('sample-select').innerHTML=Object.keys(names).filter(k=>examples.some(r=>r.condition===k)).map(k=>`<button data-sample="${k}" class="${condition===k?'active':''}">${names[k]}</button>`).join('');
 for(const b of document.querySelectorAll('[data-sample]'))b.onclick=()=>{condition=b.dataset.sample;sample();};
 $('sample-questions').innerHTML='<p class="part-label">本轮实际XYZ问题原文</p>'+r.questions.filter(q=>['x','y','z'].includes(q.name)).map(q=>'<p class="sample-prose">'+escape(q.instructions)+'</p>').join('');
 $('sample-images').innerHTML=r.images.map(v=>`<figure><a href="motion-sample/${escape(v.src)}" target="_blank" rel="noopener"><img src="motion-sample/${escape(v.src)}" alt="本轮真实输入 ${escape(v.camera)}"></a><figcaption>${escape(v.camera)} · 点击原尺寸查看</figcaption></figure>`).join('');
 $('sample-trace').textContent=JSON.stringify(r.trajectory_audit||[],null,2);$('sample-motion').textContent=r.motion_description;$('sample-state').textContent=JSON.stringify({state:r.state,context:r.context},null,2);$('sample-response').textContent=JSON.stringify(r.response,null,2);$('sample-download').href='motion-sample/'+r.download;$('sample-source').textContent='真实来源：'+r.source;
}
async function loadSample(){try{const res=await fetch('motion-sample/sample.json',{cache:'no-store'});if(!res.ok)return;examples=(await res.json()).records;if(!examples.some(r=>r.condition===condition))condition=examples[0]?.condition;sample();}catch(e){$('sample-source').textContent='样例尚未同步：'+e.message;}}
progress();loadSample();setInterval(progress,30000);
