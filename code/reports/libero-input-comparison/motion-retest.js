'use strict';
const names={full:'保留误差＋RGB',marker:'删XYZ＋目标标记',axes:'删XYZ＋标记与轴图例'};
const tasks={1098:'开中层抽屉',1144:'碗放炉灶',1163:'酒瓶放柜顶',1202:'开抽屉并放碗',1252:'碗放柜顶',1296:'推盘到炉前',1335:'奶酪放碗',1383:'转炉灶旋钮',1423:'碗放盘',1458:'酒瓶放架'};
const $=id=>document.getElementById(id);
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let examples=[],condition='axes';
async function progress(){
 try{const res=await fetch('motion-progress.json',{cache:'no-store'});if(!res.ok)throw Error('结果快照暂不可用');const d=await res.json(),c=d.conditions;
 $('run-stamp').textContent='上次同步：'+new Date(d.updated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · 实际运行回合统计';
 $('run-cards').innerHTML=Object.keys(names).map(k=>{const r=c[k]||{completed:0,native:0,joint:0,categories:{}};return `<article class="run-card"><h2>${names[k]}</h2><p>已结束 / 计划</p><strong>${r.completed} / 30</strong><p>原生成功 ${r.native} · 程序也完整完成 ${r.joint}</p><p>接口/格式故障 ${r.categories.transport_or_schema_failure||0} · 启动故障 ${r.categories.environment_or_startup_failure||0}</p></article>`;}).join('');
 const total=Object.values(c).reduce((s,r)=>s+r.completed,0);$('run-state').textContent=total===90?'本轮90个固定回合已结束。原生成功与程序完整完成分列；没有重跑已回答的正常失败。':'正在运行：'+total+' / 90个回合已结束。下面是当前快照，不是最终成功率。';
 $('run-tasks').innerHTML=Object.keys(tasks).map(t=>'<tr><td>'+t+' · '+tasks[t]+'</td>'+Object.keys(names).map(k=>{const r=c[k]?.per_task[t];return '<td>'+(r?r.native+' / '+r.joint+' / '+r.completed:'尚未结束')+'</td>';}).join('')+'</tr>').join('');
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
