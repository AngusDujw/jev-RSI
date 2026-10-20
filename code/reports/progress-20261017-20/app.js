'use strict';
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ledger = document.querySelector('#ledger');
let rows = [], day = 'all';
const statusClass = s => ({'完成':'success','失败':'failure','中断':'warning','待定':'pending'}[s] || '');
function render() {
  const query = document.querySelector('#search').value.trim().toLowerCase();
  const filtered = rows.filter(r => (day === 'all' || r.day === day) && JSON.stringify(r).toLowerCase().includes(query));
  document.querySelector('#result-count').textContent = `${filtered.length} 组实验与诊断记录 / 共 ${rows.length} 组 · 来源编号不跨工作树合并`;
  ledger.innerHTML = filtered.map(r => `<details class="experiment"><summary><span class="day">10.${esc(r.day)}</span><span><span class="track-label">${esc(r.track)}</span><span class="name">${esc(r.name)}</span></span><span class="tag ${statusClass(r.state)}">${esc(r.state)}</span><span class="toggle" aria-hidden="true">+</span></summary><div class="experiment-content"><p><b>条件 / 做了什么</b>${esc(r.setup)}</p><p><b>真实结果</b>${esc(r.result)}</p><p><b>可以得出的结论</b>${esc(r.conclusion)}</p><p class="boundary"><b>不能省略的边界</b>${esc(r.boundary)}</p><p class="source">来源：${esc(({multimodal:'多模态工作树',robodojo:'RoboDojo 工作树',main:'主分支'})[r.source])} / ${r.ids.map(id => `EXP-2026W${r.week}-${id}`).join(' · ')}<br><a href="sources/${r.source}-2026-W${r.week}.md" target="_blank" rel="noreferrer">打开该来源周志 ↗</a></p></div></details>`).join('') || '<p>没有匹配记录，请更换日期或关键词。</p>';
}
if (window.REPORT_DATA) {rows=window.REPORT_DATA.experiments;document.querySelector('#cutoff').textContent=window.REPORT_DATA.cutoff;render();} else {ledger.innerHTML='<p role="alert">数据未加载，请检查同目录 data.js 是否完整。</p>';}
document.querySelectorAll('[data-day]').forEach(button => button.addEventListener('click', () => {day=button.dataset.day;document.querySelectorAll('[data-day]').forEach(b => {b.classList.toggle('active',b===button);b.setAttribute('aria-pressed', String(b===button));});render();}));
document.querySelector('#search').addEventListener('input',render);
document.querySelector('#rotation-videos').innerHTML = [[1383,'旋钮','340 / 370 / 355 总步'],[1458,'酒瓶上架','517 / 559 / 526 总步'],[1335,'奶酪盒入碗','381 / 348 / 349 总步']].map(([id,name,steps]) => `<article class="media-card"><video controls preload="metadata" poster="assets/rotation-${id}-visual-image-0.png" src="assets/rotation-${id}-policy-replay.mp4"></video><div class="media-copy"><span class="tag success">辅助条件 · 3/3</span><h3>${name} / Goal ${id}</h3><p>${steps}<br>保存的策略观测拼接；含算法反馈。</p></div></article>`).join('');
document.querySelector('#input-images').innerHTML = [['full','保留显式 XYZ + RGB','原生 27/30 · 完整 26/30'],['marker','目标标记，去显式 XYZ','原生 1/30 · 完整 0/30'],['axes','标记 + 世界轴，去显式 XYZ','原生 0/30 · 完整 0/30']].map(([key,title,result]) => `<figure><button class="zoom" data-img="assets/${key}-agentview.png" data-caption="${title} · 实际首帧"><img loading="lazy" src="assets/${key}-agentview.png" alt="${title}的实际输入"></button><figcaption><b>${title}</b><br>${result}</figcaption></figure>`).join('');
const choices=[];
for (const task of ['stack_blocks','classify_objects']) for(let trial=1;trial<=5;trial++) choices.push({task,trial,layout:(trial-1)%2});
document.querySelector('#robo-choices').innerHTML = choices.map((c,i) => `<button data-episode="${i}" class="${i===0?'active':''}" aria-pressed="${i===0}">${c.task==='stack_blocks'?'叠块':'分类'} · trial ${c.trial}${c.task==='stack_blocks'&&c.trial===4?' / 格式拒绝':''}</button>`).join('');
function episodeCaption(c){return `${c.task==='stack_blocks'?'叠块':'分类'} / trial${c.trial} / layout${c.layout} · ${c.task==='stack_blocks'&&c.trial===4?'115步，多旋转输出被固定接口拒绝，非完整原生终局。':(c.task==='stack_blocks'?'550':'1100')+'步，完整原生失败。'}`;}
document.querySelector('#robo-caption').textContent=episodeCaption(choices[0]);
document.querySelector('#robo-choices').addEventListener('click',e => {const b=e.target.closest('[data-episode]');if(!b)return;const c=choices[Number(b.dataset.episode)];const v=document.querySelector('#robo-video');v.pause();v.src=`assets/decisions-${c.task}-trial${c.trial}-layout${c.layout}.mp4`;v.load();document.querySelectorAll('[data-episode]').forEach(el=>{el.classList.toggle('active',el===b);el.setAttribute('aria-pressed',String(el===b));});document.querySelector('#robo-caption').textContent=episodeCaption(c);});
const box=document.querySelector('#lightbox');
document.addEventListener('click',e=>{const b=e.target.closest('[data-img]');if(!b)return;const img=document.querySelector('#large-image');img.src=b.dataset.img;img.alt=b.dataset.caption;document.querySelector('#large-caption').textContent=b.dataset.caption;box.showModal();});
document.querySelector('#close-lightbox').addEventListener('click',()=>box.close());
box.addEventListener('click',e=>{if(e.target===box)box.close();});
document.querySelector('#print').addEventListener('click',()=>{document.querySelectorAll('details.experiment').forEach(el=>el.open=true);window.print();});
