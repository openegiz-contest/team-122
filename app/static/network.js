'use strict';
const $=id=>document.getElementById(id),fmt=(x,d=2)=>x==null?'—':Number(x).toFixed(d);
let state,selected=null,busy=false,pending=null;
const pos={V1:[45,95],V2:[210,95],V5:[405,95],V7:[635,95],V8:[855,95],V3:[45,340],V4:[210,340],V6:[405,340],V9:[635,340],V10:[855,340]};
const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,6500);}
async function command(data,path='/api/command'){
 if(pending)return;
 pending={waiting:true};document.body.classList.add('command-pending');$('command-status').textContent='Отправляем команду…';
 try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(120000)});const v=await r.json();if(!r.ok)throw Error(v.error);
 pending={experiment:v.experiment_id,revision:v.revision,started:Date.now()};$('command-status').textContent='Команда принята · ожидаем состояние из платформы';await refresh();
 }catch(e){pending=null;document.body.classList.remove('command-pending');$('command-status').textContent='Ошибка команды';toast(e.message);}
}

function render(s){
 if(pending?.experiment){
  if(s.experiment_id===pending.experiment&&s.revision>=pending.revision){pending=null;document.body.classList.remove('command-pending');$('command-status').textContent='Применено · подтверждено '+s.connection.source;}
  else if(Date.now()-pending.started>20000){pending=null;document.body.classList.remove('command-pending');$('command-status').textContent='Нет подтверждения · проверьте связь';toast('Команда принята сервером, но новое состояние не получено из Ditto за 20 с.');}
  else return;
 }
 state=s;
 $('sample-age').textContent=`Снимок ${Math.max(0,Date.now()/1000-s.wall_time).toFixed(1)} с назад · ревизия ${s.revision}`;
 if(document.activeElement!==$('seed'))$('seed').value=s.seed;
 document.body.classList.toggle('simulation-paused',s.paused);
 $('run-note').textContent=s.paused?'Модель на паузе · перенос метана и ремонт остановлены':`Модель работает · ${s.speed} секунд за шаг`;
document.body.classList.remove('data-stale');$('connection').textContent=s.connection.source;$('connection').className='badge';
 $('clock').textContent=`${Math.floor(s.time/60).toString().padStart(2,'0')}:${Math.floor(s.time%60).toString().padStart(2,'0')}`;
 $('pause').textContent=s.paused?'Продолжить':'Пауза';$('speed').value=s.speed;$('horizon').value=s.horizon_s;
 $('flow').textContent=fmt(s.air.q.e1+s.air.q.e3,1);$('methane').textContent=s.conflict?'Конфликт':`${fmt(s.estimate.V7.low)}–${fmt(s.estimate.V7.high)}`;
 $('availability').textContent=`${s.quality.used_channels.length} / 8`;$('width').textContent=fmt(s.width,3);
 $('mission-status').textContent=s.conflict?'Конфликт гипотез':`${s.candidate_count} / ${s.hypothesis_count} гипотез`;
 $('notice').textContent=s.conflict?'Измерения несовместимы с набором траекторий. Прогноз и рекомендации приостановлены; показана полная модельная оболочка.':'Воздушная сеть рассчитана. Диапазоны метана ограничены выбранными гипотезами; это не гарантия включения истинного состояния.';
 $('notice').className='notice'+(s.conflict?' error':'');
 for(const k of ['fan_a','fan_b','resistance_e6','gas'])if(document.activeElement!==$(k))$(k).value=s.params[k];
 drawNetwork();drawChart(s.series||[]);
 $('balance').textContent=`ΔQ ${s.air.continuity_residual_m3s.toExponential(1)} м³/с · ΔP ${s.air.energy_residual_pa.toExponential(1)} Па`;
 $('process-summary').textContent=`Мощность при η=0,72 (допущение): ${fmt(s.air.power_kw,0)} кВт. Невязка баланса CH₄: ${s.mass_balance.mass_residual_m3==null?'—':s.mass_balance.mass_residual_m3.toExponential(1)} м³.`;
 $('rankings').innerHTML=s.rankings.length?s.rankings.map((r,i)=>`<div class="rank-item ${i===0?'rank-first':''}"><div class="rank-top"><b>${esc(s.sensors[r.sensor].name)}</b><strong>${fmt(r.score,4)}</strong></div><small>Ожидаемое ΔW ${fmt(r.gain,4)} п.п. · ${r.repair_s} с · стоимость ${r.cost}</small><button data-restore="${r.sensor}" ${s.sensors[r.sensor].repair_due!=null?'disabled':''}>${s.sensors[r.sensor].repair_due!=null?(s.paused?'Ремонт ждёт продолжения':'Ремонт выполняется'):'Восстановить'}</button></div>`).join(''):`<div class="rank-empty">${s.conflict?'Сначала устраните конфликт модели и измерений.':'Нет недоступных каналов или полезного разделения гипотез.'}</div>`;
 $('decision').textContent=s.last_decision?`Последний выбор: ${s.last_decision.sensor}; ожидаемое ΔW ${fmt(s.last_decision.expected_gain,4)}. Фактическое ΔW к тому же горизонту: ${fmt(s.last_decision.actual_gain,4)}. Завершение ремонта: ${fmt(s.last_decision.repair_due,0)} с.`:'Стоимость и время ремонта — допущения опыта.';
 $('sensors').innerHTML=Object.entries(s.sensors).map(([k,v])=>`<div class="sensor-row ${!v.usable?'failed':''}"><div><b>${esc(v.name)}</b><small>${esc(v.quality)} · возраст ${fmt(v.age_s,0)} с${v.repair_due!=null?' · ремонт до '+v.repair_due+' с':''}</small></div><strong>${fmt(s.readings[k])} ${esc(v.unit)}</strong><button data-sensor="${k}" data-action="${v.usable?'fail':'restore'}" ${v.repair_due!=null?'disabled':''}>${v.usable?'Отключить':'Ремонт'}</button></div>`).join('');
 if(!$('scenarios').children.length)$('scenarios').innerHTML=Object.entries(s.scenarios).map(([k,v])=>`<button data-scenario="${k}"><b>${esc(v[0])}</b><span>${esc(v[1])}</span></button>`).join('');
 $('event-log').innerHTML=s.events.map(e=>`<li>${fmt(e.time,0)} с · ${esc(e.text)}</li>`).join('');
 $('comparison').textContent=(s.checkpoint?`От t=${s.checkpoint.time} с: `+Object.entries(s.flow_changes).map(([k,v])=>`${k}: ${v>=0?'+':''}${fmt(v,1)} м³/с`).join(' · ')+'. Изменение метана: '+['V5','V6','V7','V9'].map(n=>`${n}: ${fmt(s.truth.gas_pct[n]-s.checkpoint.gas_pct[n],3)} п.п.`).join(' · '):'Зафиксируйте «до» или запустите сценарий.')+' Прогноз через '+s.horizon_s+' с: '+(s.conflict?'недоступен':Object.entries(s.forecast).filter(([n])=>['V5','V6','V7','V9'].includes(n)).map(([n,b])=>`${n}: ${fmt(b.low,3)}–${fmt(b.high,3)}%`).join(' · '));
 if(selected)detail(selected);
}
function drawFlatNetwork(){const s=state;let out='<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="none" stroke="#75d8d1" stroke-width="1.4"/></marker></defs>';
 for(const [id,e] of Object.entries(s.objects).filter(([,v])=>v.kind==='airway'||v.kind==='fan-airway')){let [a,b]=[pos[e.from],pos[e.to]],q=s.air.q[id];if(q<0)[a,b]=[b,a];const dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy),x1=a[0]+dx/len*24,y1=a[1]+dy/len*24,x2=b[0]-dx/len*24,y2=b[1]-dy/len*24,mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2;
 const changed=Math.abs(s.flow_changes[id])>.1;const closed=e.state.closed;
 out+=`<g data-object="${id}" tabindex="0" role="button" aria-label="Ветвь ${id}" style="cursor:pointer"><path d="M${x1} ${y1}L${x2} ${y2}" class="tunnel" style="${changed?'stroke:#5b5037':''}"/><path d="M${x1} ${y1}L${x2} ${y2}" class="${closed?'':'arrow-line'}" stroke="${closed?'#f28080':'#75d8d1'}"/><text x="${mx+(id==='e5'?30:0)}" y="${my-22}" text-anchor="middle" fill="#edf4f3" font-size="14">${id}${e.kind==='fan-airway'?' ◉':''}</text><text x="${mx+(id==='e5'?58:0)}" y="${my+33}" text-anchor="middle" fill="#77e2ce" font-size="12">${closed?'ЗАКРЫТО':fmt(Math.abs(q),1)+' м³/с'}</text></g>`;
 }
 for(const [n,[x,y]] of Object.entries(pos)){const est=s.estimate[n],c=s.truth.gas_pct[n],sensor=s.sensors['c_'+n];out+=`<g data-object="${n}" tabindex="0" role="button" aria-label="Узел ${n}" style="cursor:pointer"><circle cx="${x}" cy="${y}" r="22" fill="#14343e" stroke="${sensor&&!sensor.usable?'#f28080':'#77e2ce'}"/><text x="${x}" y="${y+5}" text-anchor="middle" fill="#edf4f3" font-size="13">${n}</text><text x="${x}" y="${y+62}" text-anchor="middle" fill="#eac077" font-size="12">${est?`${fmt(est.low)}–${fmt(est.high)}%`:''}</text>${$('showTruth').checked&&c!=null?`<text x="${x}" y="${y+80}" text-anchor="middle" fill="#90a7b4" font-size="11">эталон ${fmt(c,3)}%</text>`:''}</g>`;}
 $('network').innerHTML=out;
}
function detail(id){selected=id;const o=state.objects[id],v=o.state||{};
 const row=(name,value)=>`<div><span>${name}</span><strong>${value}</strong></div>`;
 let body='';
 if(o.kind==='airway'||o.kind==='fan-airway')body=row('Связь',`${o.from} → ${o.to}`)+row('Расход',fmt(v.flow_m3_s,1)+' м³/с')+row('Изменение от «до»',fmt(state.flow_changes[id],1)+' м³/с')+row('Длина / сечение',`${fmt(o.length,0)} м / ${fmt(o.area,1)} м²`)+row('Скорость воздуха',fmt(Math.abs(v.flow_m3_s)/o.area,2)+' м/с')+row('Геометрический объём',fmt(o.spatial.volume_m3,0)+' м³')+row('Сторона условного квадрата',fmt(o.spatial.square_section_side_m,2)+' м')+row('Длина XYZ / ошибка',fmt(o.spatial.length_m,0)+' м / '+fmt(o.spatial.length_error_m,6)+' м')+row('Сопротивление',fmt(v.resistance,5)+' Па·с²/м⁶')+(o.kind==='fan-airway'?row('Скорость / напор',`${fmt(v.speed_factor*100,0)}% / ${fmt(v.head_pa,0)} Па`):'');
 else if(o.kind==='sensor')body=row('Измеряет',esc(o.target))+row('Показание',fmt(v.reading)+' '+esc(o.unit))+row('Качество',esc(v.quality))+row('Возраст',fmt(v.age_s,0)+' с');
 else body=row('Связанные ветви',o.links.map(esc).join(' · '))+row('Давление',fmt(v.pressure_pa,0)+' Па')+(v.estimate?row('Оценка CH₄',`${fmt(v.estimate.low,3)}–${fmt(v.estimate.high,3)}%`)+row('Объём смешения',fmt(o.volume_m3,0)+' м³'):'');
 if(o.spatial?.xyz_m)body+=row('Локальные XYZ, м',o.spatial.xyz_m.map(x=>fmt(x,0)).join(' / '));
 body+=row('Происхождение координат','Условная реконструкция');
 $('object-detail').innerHTML=`<div class="detail-heading"><b>${esc(id)} <small>${esc(o.kind)}</small></b><span>Объект цифрового двойника</span></div><div class="detail-grid">${body}</div><details><summary>Источник и все параметры</summary><pre>${esc(JSON.stringify(o,null,2))}</pre></details>`;
}

function drawChart(rows){if(rows.length<2){$('chart').innerHTML='';return;}const max=Math.max(.1,...rows.map(r=>Math.max(r.gas.V7,r.estimate.V7.high)))*1.1;const x=i=>50+i*930/(rows.length-1),y=v=>155-135*v/max;
 const path=key=>rows.map((r,i)=>`${i?'L':'M'}${x(i)},${y(key(r))}`).join(' ');
 $('chart').innerHTML=`<text x="3" y="20" fill="#90a7b4">${fmt(max)}%</text><text x="3" y="155" fill="#90a7b4">0%</text><path d="${path(r=>r.estimate.V7.high)}" stroke="#eac077" fill="none"/><path d="${path(r=>r.estimate.V7.low)}" stroke="#eac077" fill="none"/><path d="${path(r=>r.gas.V7)}" stroke="#77e2ce" stroke-dasharray="5 5" fill="none"/><text x="50" y="176" fill="#90a7b4">${fmt(rows[0].t,0)} с</text><text x="920" y="176" fill="#90a7b4">${fmt(rows.at(-1).t,0)} с</text>`;
}
async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/state',{signal:AbortSignal.timeout(8000)});const s=await r.json();if(!r.ok)throw Error(s.error||'Источник недоступен');render(s);}catch(e){if(pending?.started&&Date.now()-pending.started>20000){pending=null;document.body.classList.remove('command-pending');$('command-status').textContent='Нет подтверждения · связь с платформой потеряна';}document.body.classList.add('data-stale');$('connection').textContent='Нет данных';$('connection').className='badge error';$('notice').textContent=e.message;$('notice').className='notice error';}finally{busy=false;}}
document.addEventListener('click',e=>{const b=e.target.closest('button');if(b?.dataset.scenario)command({action:'scenario',name:b.dataset.scenario});if(b?.dataset.restore)command({action:'restore',sensor:b.dataset.restore});if(b?.dataset.sensor)command({action:b.dataset.action,sensor:b.dataset.sensor});const o=e.target.closest('[data-object]');if(o)detail(o.dataset.object);});
$('network').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.dataset.object){e.preventDefault();detail(e.target.dataset.object);}});
for(const id of ['pause','checkpoint','reset'])$(id).onclick=()=>command({action:id});
$('new-seed').onclick=()=>command({action:'reset',seed:Number($('seed').value)});
for(const id of ['speed','horizon'])$(id).onchange=()=>command({action:id,value:Number($(id).value)});
for(const id of ['fan_a','fan_b','resistance_e6','gas'])$(id).onchange=()=>command({action:'parameter',name:id,value:Number($(id).value)});
$('showTruth').onchange=()=>state&&drawNetwork();$('import-choose').onclick=()=>$('import-file').click();
$('import-file').onchange=async()=>{const f=$('import-file').files[0];if(!f)return;try{if(f.size>2*1024*1024)throw Error('Файл больше 2 МБ');const data=JSON.parse(await f.text());await command(data,'/api/replay');}catch(e){toast(e.message);}finally{$('import-file').value='';}};
for(const id of ['map-view','map-layer','height-scale','camera-angle'])$(id).onchange=()=>state&&drawNetwork();
refresh();setInterval(refresh,1500);
// Presentation coordinates are illustrative; hydraulic lengths stay in the model.
const isoPos={V1:[120,245],V2:[280,310],V5:[440,375],V7:[600,440],V8:[760,505],V3:[330,120],V4:[490,185],V6:[650,250],V9:[810,315],V10:[970,380]};
function isoBox(x,y,w,d,h,roof='#dfc28a',left='#8a714c',right='#b19361'){
 return `<path d="M${x-w},${y}l${w},${d}v${-h}l${-w},${-d}Z" fill="${left}"/><path d="M${x},${y+d}l${w},${-d}v${-h}l${-w},${d}Z" fill="${right}"/><path d="M${x-w},${y-h}l${w},${-d} ${w},${d} ${-w},${d}Z" fill="${roof}"/>`;
}
function drawNetwork(){
 const svg=$('network');
 if(['metric','plan','profile'].includes($('map-view').value)){drawMetricNetwork();return;}
 if($('map-view').value==='flat'){svg.setAttribute('viewBox','0 0 900 470');drawFlatNetwork();return;}
 svg.setAttribute('viewBox','0 0 1100 660');const s=state;
 let out=`<defs><linearGradient id="earth" x2="0" y2="1"><stop stop-color="#cab180"/><stop offset="1" stop-color="#9c8156"/></linearGradient><linearGradient id="leftRock" x2="0" y2="1"><stop stop-color="#8c7048"/><stop offset=".5" stop-color="#5e503d"/><stop offset="1" stop-color="#303848"/></linearGradient><pattern id="surfaceGrid" width="30" height="30" patternUnits="userSpaceOnUse" patternTransform="matrix(1 .406 -.7 .42 0 0)"><path d="M30 0H0V30" fill="none" stroke="#fbe5b1" stroke-opacity=".12"/></pattern><filter id="softGlow"><feGaussianBlur stdDeviation="5"/></filter><filter id="sceneShadow" x="-30%" y="-30%" width="160%" height="180%"><feGaussianBlur stdDeviation="18"/></filter><marker id="isoArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4 0 8" fill="none" stroke="#92fff0" stroke-width="1.5"/></marker></defs>
 <path d="M50 330L340 150 1050 440 760 620Z" fill="#000a19" opacity=".8" filter="url(#sceneShadow)"/>
 <path d="M50 245L760 535V610L50 320Z" fill="url(#leftRock)"/>
 <path d="M760 535L1050 355V430L760 610Z" fill="#6e5b40"/>
 <path d="M50 267L760 557 1050 377M50 290L760 580 1050 400M50 309L760 599 1050 419" fill="none" stroke="#b19a6b" stroke-opacity=".25" stroke-width="4"/>
 <path d="M50 245L340 65 1050 355 760 535Z" fill="url(#earth)" stroke="#e7c995" stroke-width="2"/>
 <path d="M50 245L340 65 1050 355 760 535Z" fill="url(#surfaceGrid)"/>`;
 // Deterministic rock fragments, outside the two main corridors.
 for(let i=0;i<44;i++){const u=((i*37)%100)/100,v=((i*61)%100)/100,x=80+680*u+245*v,y=245+277*u-150*v;out+=`<ellipse cx="${x}" cy="${y}" rx="${2+i%3}" ry="2" fill="#6c573b" opacity=".45"/>`;}
 const edges=Object.entries(s.objects).filter(([,v])=>v.kind==='airway'||v.kind==='fan-airway');
 for(const [id,e] of edges){const a=isoPos[e.from],b=isoPos[e.to],q=s.air.q[id],closed=e.state.closed,changed=Math.abs(s.flow_changes[id])>.1;
  const path=`M${a[0]},${a[1]}L${b[0]},${b[1]}`;
  out+=`<g data-object="${id}" tabindex="0" role="button" aria-label="Ветвь ${id}, ${fmt(Math.abs(q),1)} кубометров в секунду"><title>${id}: ${e.from} → ${e.to}</title><path d="${path}" fill="none" stroke="#6b583f" stroke-width="35"/><path d="${path}" fill="none" stroke="#172c38" stroke-width="25"/><path d="${path}" fill="none" stroke="${closed?'#ff7e78':changed?'#ffd786':'#70f2d7'}" stroke-width="11" opacity=".3" filter="url(#softGlow)"/>`;
  if(!closed){const aa=q>=0?a:b,bb=q>=0?b:a;out+=`<path d="M${aa[0]},${aa[1]}L${bb[0]},${bb[1]}" class="iso-flow"/><path d="M${aa[0]*.4+bb[0]*.6},${aa[1]*.4+bb[1]*.6}L${aa[0]*.3+bb[0]*.7},${aa[1]*.3+bb[1]*.7}" fill="none" stroke="#92fff0" stroke-width="2" marker-end="url(#isoArrow)"/>`;}
  else {const x=(a[0]+b[0])/2,y=(a[1]+b[1])/2;out+=`<path d="M${x-12} ${y-14}L${x+12} ${y+14}M${x+12} ${y-14}L${x-12} ${y+14}" stroke="#ff827d" stroke-width="7"/>`;}
  out+='</g>';
 }
 // Objects rendered back to front. Every label is bound to the same Ditto catalog.
 for(const [n,[x,y]] of Object.entries(isoPos).sort((a,b)=>a[1][1]-b[1][1])){
  const fan=n==='V8'||n==='V10',inlet=n==='V1'||n==='V3',est=s.estimate[n],sensor=s.sensors['c_'+n];
  const color=sensor&&!sensor.usable?'#ff8d87':'#70f2d7';
  out+=`<g data-object="${fan?(n==='V8'?'e8':'e9'):n}" tabindex="0" role="button" aria-label="${fan?'Вентилятор '+(n==='V8'?'A':'B'):'Узел '+n}"><ellipse cx="${x}" cy="${y+8}" rx="42" ry="17" fill="#142b36" opacity=".25"/>`;
  if(fan){out+=isoBox(x,y,40,17,54,'#f4ce7e','#9e7b42','#c8a25c');out+=`<circle cx="${x+19}" cy="${y-25}" r="19" fill="#132a36" stroke="#f1d99c" stroke-width="3"/><g transform="translate(${x+19} ${y-25})"><g class="fan-rotor" style="animation-duration:${2/(n==='V8'?s.params.fan_a:s.params.fan_b)}s"><path d="M0 0C-23-21 9-21 0 0C28-9 18 20 0 0C-6 28-27 2 0 0" fill="#8be7d9"/></g></g>`;}
  else if(inlet){out+=isoBox(x,y,27,13,35,'#cbd4d2','#617e86','#8fa7ad');out+=`<path d="M${x+4} ${y+4}v-23l18-9v24Z" fill="#142b38"/>`;}
  else {out+=isoBox(x,y,20,9,10,'#d3c09a','#7b725c','#ab9570');out+=`<circle cx="${x}" cy="${y-14}" r="6" fill="${color}"/><circle cx="${x}" cy="${y-14}" r="12" fill="${color}" opacity=".25" filter="url(#softGlow)"/>`;}
  const ly=y-(fan?91:inlet?69:61),title=fan?(n==='V8'?'Вентилятор A':'Вентилятор B'):inlet?'Приток · '+n:n;
  out+=`<path d="M${x} ${ly+27}V${y-20}" stroke="#d7e9df" stroke-opacity=".5"/><rect x="${x-66}" y="${ly}" width="132" height="${est?44:27}" rx="6" fill="#0c2132" stroke="${selected===n?'#fff0bb':'#3f6067'}"/><circle cx="${x-54}" cy="${ly+13}" r="3" fill="${color}"/><text x="${x-44}" y="${ly+17}" fill="#edf4f3" font-size="12">${title}</text>${est?`<text x="${x-53}" y="${ly+34}" fill="#f5d79a" font-size="11">${s.conflict?'конфликт':fmt(est.low)+'–'+fmt(est.high)+'% CH₄'}</text>`:''}`;
  if($('showTruth').checked&&s.truth.gas_pct[n]!=null)out+=`<text x="${x}" y="${y+42}" text-anchor="middle" fill="#132635" font-weight="600" font-size="11">эталон ${fmt(s.truth.gas_pct[n],3)}%</text>`;
  out+='</g>';
 }
 for(const [id,e] of edges){const a=isoPos[e.from],b=isoPos[e.to],x=(a[0]+b[0])/2,y=(a[1]+b[1])/2+19,q=s.air.q[id],sensor=s.sensors['q_'+id];
  out+=`<g data-object="${sensor?'sensor-q_'+id:id}" tabindex="0" role="button" aria-label="${sensor?'Датчик расхода ':'Поток '}${id}"><rect x="${x-57}" y="${y}" width="114" height="23" rx="5" fill="#102b3c" stroke="#476573"/><circle cx="${x-46}" cy="${y+11}" r="3" fill="${sensor&&!sensor.usable?'#ff8d87':'#70f2d7'}"/><text x="${x-36}" y="${y+15}" fill="#e3efec" font-size="10">${id} · ${e.state.closed?'ЗАКРЫТО':fmt(Math.abs(q),1)+' м³/с'}</text></g>`;
 }
 out+=`<text x="55" y="36" fill="#7a98ae" font-size="11" letter-spacing="3">GUCHENG / VENTILATION NETWORK</text><text x="55" y="638" fill="#83a2b5" font-size="12">● Бирюзовый — воздушный путь · Красный — отказ / закрытие · Золотой — изменение расхода</text>`;
 const focus=document.activeElement?.closest('[data-object]')?.dataset.object;
 svg.innerHTML=out;if(focus)svg.querySelector(`[data-object="${focus}"]`)?.focus();
}

function drawMetricNetwork(){
 const s=state,svg=$('network'),view=$('map-view').value,layer=$('map-layer').value;
 const exaggeration=Number($('height-scale').value),angle=Number($('camera-angle').value)*Math.PI/180;
 const projectRaw=([x,y,z])=>view==='plan'?[x,-y]:view==='profile'?[x,-z]:[x*Math.cos(angle)-y*Math.sin(angle),(x*Math.sin(angle)+y*Math.cos(angle))*.5-z*.866*exaggeration];
 const nodes=Object.entries(s.objects).filter(([,o])=>o.kind==='boundary'||o.kind==='mixing-node');
 const raw=nodes.map(([,o])=>projectRaw(o.spatial.xyz_m)),xs=raw.map(p=>p[0]),ys=raw.map(p=>p[1]);
 const lo=[Math.min(...xs),Math.min(...ys)],hi=[Math.max(...xs),Math.max(...ys)],scale=Math.min(740/(hi[0]-lo[0]),410/Math.max(500,hi[1]-lo[1]));
 const project=p=>{const [x,y]=projectRaw(p);return [550+(x-(lo[0]+hi[0])/2)*scale,315+(y-(lo[1]+hi[1])/2)*scale];};
 const point=p=>project(p).join(',');const path=points=>'M'+points.map(point).join('L');
 const edges=Object.entries(s.objects).filter(([,o])=>o.kind==='airway'||o.kind==='fan-airway');
 const minp=Math.min(...Object.values(s.air.pressure)),maxv=Math.max(...edges.map(([id,o])=>Math.abs(s.air.q[id])/o.area));
 const color=(id,o)=>{if(o.state.closed)return '#ff887c';let f=0;
  if(layer==='velocity')f=Math.abs(s.air.q[id])/o.area/maxv;
  else if(layer==='pressure')f=Math.abs(s.air.pressure[o.from])/Math.max(1,Math.abs(minp));
  else if(layer==='methane'){if(s.conflict)return '#88949e';const q=s.air.q[id],e=s.estimate[q>=0?o.to:o.from]||s.estimate[q>=0?o.from:o.to];f=Math.min(1,(e?.high||0)/1);}
  else return Math.abs(s.flow_changes[id])>.1?'#efc982':'#75e4d2';
  return `hsl(${175-f*145} 65% 65%)`;
 };
 let out=`<defs><marker id="metric-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4 0 8" fill="none" stroke="#eafff4" stroke-width="1.5"/></marker><linearGradient id="metricRock" x2="0" y2="1"><stop stop-color="#c4a976"/><stop offset="1" stop-color="#655b4b"/></linearGradient></defs>`;
 const corners=[[-2400,-500,-500],[8400,-500,-500],[8400,4410,-500],[-2400,4410,-500]];
 if(view==='metric'){
  const bottom=corners.map(([x,y,z])=>[x,y,z-180]);
  for(let i=0;i<4;i++)out+=`<path d="${path([corners[i],corners[(i+1)%4],bottom[(i+1)%4],bottom[i]])}Z" fill="url(#metricRock)" stroke="#6c604a" opacity=".75"/>`;
 }
 out+=`<path d="${path(corners)}Z" fill="#a28e6640" stroke="#c5ae77" stroke-opacity=".5"/>`;
 for(let x=-2000;x<=8000;x+=1000)out+=`<path d="${path([[x,-500,-500],[x,4410,-500]])}" stroke="#b4d2db" opacity=".12" fill="none"/>`;
 for(let y=0;y<=4000;y+=1000)out+=`<path d="${path([[-2400,y,-500],[8400,y,-500]])}" stroke="#b4d2db" opacity=".12" fill="none"/>`;
 if(view!=='plan'){
  const top=corners.map(([x,y])=>[x,y,0]);out+=`<path d="${path(top)}Z" fill="none" stroke="#7694ad" stroke-dasharray="5 8" opacity=".5"/>`;
 }
 for(const [id,o] of edges){const [a,b]=o.spatial.centerline_m,p1=project(a),p2=project(b),q=s.air.q[id],c=color(id,o),closed=o.state.closed;
  const d=path([a,b]),selectedEdge=selected===id,stroke=8+Math.sqrt(o.area)*.5;
  out+=`<g data-object="${id}" role="button" tabindex="0" aria-label="Выработка ${id}, длина ${o.length} метров"><title>${id}: ${o.length} м; ${o.area} м²; Q=${fmt(q,1)} м³/с</title><path d="${d}" stroke="${selectedEdge?'#fff0bd':'#102638'}" stroke-width="${stroke+7}" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${c}" stroke-width="${stroke}" stroke-linecap="round" opacity=".72"/>`;
  if(!closed&&Math.hypot(p1[0]-p2[0],p1[1]-p2[1])>12){const aa=q>=0?p1:p2,bb=q>=0?p2:p1;out+=`<path d="M${aa}L${bb}" class="iso-flow"/><path d="M${aa[0]*.55+bb[0]*.45},${aa[1]*.55+bb[1]*.45}L${aa[0]*.45+bb[0]*.55},${aa[1]*.45+bb[1]*.55}" stroke="#fff" marker-end="url(#metric-arrow)"/>`;}
  const x=(p1[0]+p2[0])/2,y=(p1[1]+p2[1])/2;
  const value=closed?'ЗАКРЫТО':layer==='velocity'?fmt(Math.abs(q)/o.area,2)+' м/с':layer==='pressure'?fmt(s.air.pressure[o.from],0)+' Па':layer==='methane'?fmt((s.estimate[q>=0?o.to:o.from]||s.estimate[q>=0?o.from:o.to])?.high,3)+'% верх':fmt(Math.abs(q),1)+' м³/с';
  const shaft=a[0]===b[0]&&a[1]===b[1],offset=shaft?(id==='e1'||id==='e3'?-90:90):view==='metric'&&id==='e5'?-85:0;
  const labelY=shaft?y-35:view==='profile'?y+({e2:0,e4:65,e5:130,e6:0,e7:65}[id]||0):y;
  out+=`<rect x="${x-68+offset}" y="${labelY+15}" width="136" height="34" rx="5" fill="#0a2032" stroke="${c}" stroke-opacity=".5"/><text x="${x+offset}" y="${labelY+29}" text-anchor="middle" fill="#e8f1f1" font-size="11">${id} · ${fmt(o.length/1000,1)} км · ${fmt(o.area,1)} м²</text><text x="${x+offset}" y="${labelY+42}" text-anchor="middle" fill="${c}" font-size="11">${value}</text></g>`;
 }
 for(const [id,o] of nodes){const p=project(o.spatial.xyz_m),boundary=o.kind==='boundary',isFan=id==='V8'||id==='V10';
  const sx=p[0],sy=p[1],est=s.estimate[id],fault=s.sensors['c_'+id]&&!s.sensors['c_'+id].usable;
  const dy=view==='plan'&&boundary?-31:view==='profile'&&id==='V6'?75:view==='metric'&&['V2','V4','V7','V9'].includes(id)?60:0;
  out+=`<g data-object="${id}" tabindex="0" role="button" aria-label="Узел ${id}, глубина ${-o.spatial.xyz_m[2]} метров"><circle cx="${sx}" cy="${sy}" r="${boundary?9:7}" fill="${fault?'#c96463':boundary?'#d2ba82':'#11394b'}" stroke="#d8e8df"/>`;
  if(isFan)out+=`<path d="M${sx-5} ${sy-5}l10 10m0-10l-10 10" stroke="#19374b" stroke-width="2"/>`;
  out+=`<text x="${sx+(view==='metric'&&['V3','V10'].includes(id)?-70:0)}" y="${sy-16+dy}" text-anchor="middle" fill="#f1eee4" font-size="12" font-weight="600">${id}${boundary?' · 0 м':' · −500 м'}</text>`;
  if(est)out+=`<text x="${sx}" y="${sy-31+dy}" text-anchor="middle" fill="#ebd19b" font-size="11">${s.conflict?'конфликт':fmt(est.low,2)+'–'+fmt(est.high,2)+'% CH₄'}</text>`;
  if($('showTruth').checked&&s.truth.gas_pct[id]!=null)out+=`<text x="${sx}" y="${sy+24+dy}" text-anchor="middle" fill="#cce8e1" font-size="10">эталон ${fmt(s.truth.gas_pct[id],3)}%</text>`;
  out+='</g>';
 }
 for(const [id,o] of Object.entries(s.objects).filter(([,o])=>o.kind==='sensor')){const [x,y]=project(o.spatial.xyz_m),ok=o.state.usable;out+=`<g data-object="${id}" tabindex="0" role="button" aria-label="Датчик ${esc(o.name)}"><rect x="${x-4}" y="${y-4}" width="8" height="8" fill="${ok?'#92f9da':'#ff817c'}" stroke="#0a2032"/><title>${esc(o.name)} · ${ok?'свежий':'недоступен'}</title></g>`;}
 if(view==='plan'||view==='profile')out+=`<path d="M70 570h${1000*scale}m0-5v10M70 565v10" stroke="#dae8e2"/><text x="70" y="593" fill="#a8c2d0" font-size="12">1 км · ось X</text>`;
 out+=`<text x="55" y="36" fill="#8daabd" font-size="12">${view==='plan'?'ПЛАН X/Y':view==='profile'?'ПРОФИЛЬ X/Z · координата Y свёрнута':'МЕТРИЧЕСКАЯ РЕКОНСТРУКЦИЯ XYZ'}</text><text x="55" y="621" fill="#aec1ce" font-size="11">Длины и площади — источник · XYZ, отметки 0 / −500 м и форма сечения — допущения</text><text x="55" y="640" fill="#8daabd" font-size="11">${view==='metric'?'Вертикальный масштаб ×'+exaggeration+' · горизонтальные размеры согласованы':'Проекция в метрах'} · Толщина линий и датчики увеличены для читаемости</text>`;
 svg.setAttribute('viewBox','0 0 1100 660');svg.innerHTML=out;
 $('spatial-summary').textContent='9 из 9 длин совпадают с источником · '+fmt(edges.reduce((sum,[,o])=>sum+o.length,0)/1000,2)+' км выработок · отметка −500 м условная. Цвет: '+$('map-layer').selectedOptions[0].textContent+'.';
}

async function loadUtility(){try{
 const r=await fetch('/api/utility');const report=await r.json();if(!r.ok)throw Error(report.error);
 const show=()=>{const group=$('utility-group').value,g=report.groups[group];
 const pct=x=>x==null?'—':fmt(x*100,1)+'%';
 const names={proposed:'Прогноз / стоимость',simple:'Текущий разброс',methane_priority:'Приоритет метана',fastest:'Самый быстрый ремонт',random_exact:'Случайный · точное среднее',no_repair:'Не ремонтировать',oracle:'Оракул · недоступный эталон'};
 $('utility-results').innerHTML=`<p>${g.cases} случаев · ${g.prior_conflicts} конфликтов до выбора · сравнение на ${g.evaluated} случаях.</p><div class="table-wrap"><table><thead><tr><th>Стратегия</th><th>W после, п.п.</th><th>ΔW / стоимость</th><th>Включение эталона</th><th>Конфликт после</th></tr></thead><tbody>${Object.entries(g.strategies).map(([key,v])=>`<tr><td>${names[key]}</td><td>${fmt(v.remaining_width,4)}</td><td>${fmt(v.gain_per_cost,4)}</td><td>${pct(v.contains_truth)}</td><td>${pct(v.conflict)}</td></tr>`).join('')}</tbody></table></div><p>Приоритет метана имеет больший средний выигрыш на стоимость в этом наборе. Универсальное превосходство прогнозного выбора не подтверждено.</p><p>Против текущего разброса по ΔW / стоимости: ${g.comparisons.simple.gain_per_cost.wins} побед, ${g.comparisons.simple.gain_per_cost.ties} равенств, ${g.comparisons.simple.gain_per_cost.losses} поражений.</p><p class="tiny">${group==='off_grid'?'Вне сетки узкий диапазон может быть ошибочным. Смотрите включение эталона и конфликты, а не только W.':'Даже полное включение эталона в этих опытах не даёт гарантии для шахты.'} Случайная стратегия усреднена по всем доступным каналам; стоимость и время ремонта учтены. Это синтетическая проверка без настройки метода по её результатам.</p>`;
 };$('utility-group').onchange=show;show();
 }catch(e){$('utility-results').textContent='Отчёт проверки недоступен: '+e.message;}}

loadUtility();
