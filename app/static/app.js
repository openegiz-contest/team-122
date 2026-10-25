const $=selector=>document.querySelector(selector);
const fmt=(value,digits=2)=>value===null||value===undefined?'—':Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const range=(value,digits=2)=>`${fmt(value.low,digits)}–${fmt(value.high,digits)}`;
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state=null,experimentId=null,selectedZone=null,pending=null,sensorRowsBuilt=false;
const positions={qt:[136,220],qa:[332,100],ca:[558,133],qb:[332,340],cb:[558,308]};
const qualityNames={fresh:'свежее',failed:'канал отключён',waiting:'ожидание показания',delayed:'задержанное',stale:'устаревшее'};

function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,5000);}
function setInput(id,value){const element=$(id);if(document.activeElement!==element)element.value=value;}
async function command(data){
  try{
    const response=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Команда отклонена');
    await poll();
  }catch(error){toast(error.message);}
}

$('#map-sensors').innerHTML=Object.entries(positions).map(([key,[x,y]])=>`<g class="sensor-marker" data-sensor="${key}" transform="translate(${x} ${y})" tabindex="0" role="button" aria-label="Переключить датчик ${key.toUpperCase()}"><circle r="15"/><text y="3">${key.toUpperCase()}</text></g>`).join('');
function toggleSensor(key){if(state)command({action:state.sensors[key].failed||!state.sensors[key].usable?'restore':'fail',sensor:key});}
$('#map-sensors').addEventListener('click',event=>{const target=event.target.closest('[data-sensor]');if(target)toggleSensor(target.dataset.sensor);});
$('#map-sensors').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();const target=event.target.closest('[data-sensor]');if(target)toggleSensor(target.dataset.sensor);}});

function buildSensorRows(s){
  $('#sensors').innerHTML=Object.entries(s.sensors).map(([key,sensor])=>`<div id="row-${key}" class="sensor-row"><div class="sensor-description"><b>${escapeHTML(sensor.name)}</b><small>Допуск ±${fmt(sensor.tolerance)} ${escapeHTML(sensor.unit)}</small><small id="quality-${key}"></small></div><div class="sensor-values"><strong id="reading-${key}">—</strong><small id="age-${key}"></small></div><div class="sensor-actions"><button data-toggle="${key}" aria-label="Отключить ${key.toUpperCase()}">Откл.</button><label class="cost-label">Стоимость<input type="number" data-cost="${key}" id="cost-${key}" min="0.1" max="100" step="0.1" aria-label="Условная стоимость ${key.toUpperCase()}"></label></div></div>`).join('');
  sensorRowsBuilt=true;
}
function renderSensorSettings(){
  if(!state||$('#sensor-settings').contains(document.activeElement))return;
  const key=$('#sensor-choice').value,sensor=state.sensors[key];
  $('#sensor-noise').value=sensor.noise;$('#sensor-delay').value=sensor.delay_s;$('#sensor-frozen').checked=sensor.frozen;
  $('#sensor-settings-note').textContent=`Единица шума: ${sensor.unit}. Допуск наблюдателя ±${fmt(sensor.tolerance)}. Восстановление снимает шум, задержку, зависание и заданное смещение канала.`;
}
function renderObject(){
  if(!state||!selectedZone)return;
  const e=state.estimate,key='c'+selectedZone,q='q'+selectedZone;
  $('#object-detail').textContent=`Участок ${selectedZone.toUpperCase()} · синтетический объём ${selectedZone==='a'?'1800':'2400'} м³. Оценка потока: ${range(e[q],1)} м³/с; CH₄: ${range(e[key])}% об. Связи: вентилятор → участок → возврат. Оценка условна относительно границ модели.`;
}
function renderRankings(s){
  const panel=$('#rankings');
  if(s.conflict){panel.innerHTML='<div class="rank-empty">Есть зафиксированное противоречие модели и измерений. Рекомендации приостановлены. Проверьте канал и допущения; восстановление канала или явный перезапуск заново инициализирует наблюдатель.</div>';return;}
  if(!s.rankings.length){panel.innerHTML='<div class="rank-empty">Все текущие измерения свежие. Начните опыт с потери или задержки канала.</div>';return;}
  const maximum=Math.max(1e-9,...s.rankings.map(row=>row.score));
  const zero=maximum<=1e-9?'<p class="tiny">Для текущей ширины CH₄ восстановление этих каналов не даёт немедленного выигрыша. Это ограничение выбранной задачи, а не бесполезность расходомеров вообще.</p>':'';
  panel.innerHTML=zero+s.rankings.map((row,i)=>`<div class="rank-item ${i===0&&row.score>1e-9?'rank-first':''}"><div class="rank-top"><span>${i+1}. ${escapeHTML(s.sensors[row.sensor].name)}</span><strong>${fmt(row.score,3)}</strong></div><div class="rank-bar"><i style="width:${100*row.score/maximum}%"></i></div><small class="tiny">Модельное сокращение: ${fmt(row.gain,3)} п.п.<br>Диапазон выигрыша по условным вариантам: ${fmt(row.worst_gain,3)}–${fmt(row.best_gain,3)} п.п.<br>Стоимость: ${fmt(row.cost,1)} усл. ед.</small><p class="tiny">${row.reason==='direct_current_methane_interval'?'Свежий замер непосредственно ограничивает концентрацию в этой зоне.':'В этом наблюдателе новый расход не уточняет прошлое состояние метана мгновенно.'}</p><button data-restore="${row.sensor}">Восстановить измерение ${row.sensor.toUpperCase()}</button></div>`).join('');
}
function renderComparison(s){
  const point=s.checkpoint;
  $('#comparison').textContent=point?`От контрольной точки ${fmt(point.time,0)} с: W ${fmt(point.width,3)} → ${fmt(s.width,3)} п.п.; изменение оценки общего расхода ${fmt(s.estimate.qt.mean-point.estimate.qt.mean,1)} м³/с. Физика и неопределённость показаны раздельно.`:'Нажмите «Зафиксировать до», затем измените условия и восстановите измерение.';
  const decision=s.last_decision;
  $('#last-decision').textContent=decision?(decision.before_conflict||decision.after_conflict?`Восстановление ${decision.sensor.toUpperCase()} в ${fmt(decision.time,0)} с включало противоречивую оценку. Изменение W после переинициализации не считается подтверждённой информационной пользой.`:`Восстановление ${decision.sensor.toUpperCase()} в ${fmt(decision.time,0)} с: модель ожидала ${fmt(decision.expected_gain,3)} п.п.; фактически W изменилось с ${fmt(decision.before_width,3)} до ${fmt(decision.after_width,3)} п.п. Сокращение ${fmt(decision.actual_gain,3)} п.п. при стоимости ${fmt(decision.cost,1)}.`):'';
}
function render(s){
  if(!s.quality||!s.mission)throw Error('Сервер использует предыдущую версию модели. Перезапустите локальный стенд.');
  state=s;document.body.classList.remove('data-stale');
  if(experimentId!==s.experiment_id){experimentId=s.experiment_id;selectedZone=null;$('#object-detail').textContent='Выберите прямоугольник A или B, чтобы увидеть параметры участка.';}
  const e=s.estimate,used=s.quality.used_channels;
  $('#clock').textContent=`${String(Math.floor(s.time/60)).padStart(2,'0')}:${String(Math.floor(s.time%60)).padStart(2,'0')}`;
  $('#flow').textContent=s.sensors.qt.usable?fmt(s.readings.qt,1):range(e.qt,1);
  $('#flow-note').textContent=s.sensors.qt.usable?'м³/с · свежее измерение QT':'м³/с · текущая оценка, не старое QT';
  $('#methane').textContent=range(e.ca);$('#methane-note').textContent='интервал состояния · % об. CH₄';
  $('#availability').textContent=`${used.length} / 5`;$('#candidates').textContent=fmt(s.width,3);
  $('#pause').textContent=s.paused?'Продолжить':'Пауза';$('#speed').value=s.speed;
  $('#connection').textContent=s.connection.mode==='local'?'● Локальный стенд':'● OpenEgiz / Ditto';$('#connection').className='badge';
  $('#footer-source').textContent=s.connection.mode==='local'?'Источник: локальная симуляция · интервальный наблюдатель':'Источник: Ditto · новые функции требуют отдельной проверки интеграции';
  setInput('#seed',s.seed);setInput('#target-width',s.mission.target_width_pp);
  setInput('#fan',Math.round(s.params.fan*100));$('#fan-value').textContent=fmt(s.params.fan*100,0)+'%';
  setInput('#leakage',Math.round(s.params.leakage*100));$('#leak-value').textContent='×'+fmt(s.params.leakage,2);
  const statuses={inspect:'Проверить согласованность',target_met:'Ширина в пределах цели',choose:'Выбрать измерение',precision_limited:'Точность ограничена допусками'};
  $('#mission-status').textContent=statuses[s.mission.status];$('#mission-status').className='badge'+(s.conflict?' error':'');
  $('#mission-text').textContent=`W = ${fmt(s.width,3)} п.п.; цель ${fmt(s.mission.target_width_pp,2)} п.п. ${s.conflict?'Оценка противоречива; выполнение цели не оценивается.':s.width<=s.mission.target_width_pp?'Следите за динамикой: при потере каналов диапазон может вырасти.':'Сравните доступные варианты восстановления и фактический результат.'}`;
  const missing=5-used.length,note=$('#notice');
  note.className='notice'+(s.conflict?' error':missing||s.quality.nominal_conflict?' warning':'');
  note.textContent=s.conflict?'Обнаружено противоречие измерений и прогноза. Диапазоны не следует трактовать как подтверждённую оценку; рейтинг остановлен.':missing?`Для текущего состояния не используются каналов: ${missing}. Предыдущие измерения сохранены в интервальном состоянии; неопределённость развивается со временем.`:s.quality.nominal_conflict?'Библиотека постоянных гипотез не согласуется с показаниями. Основной интервальный наблюдатель допускает изменения параметров внутри своих границ.':'Все пять измерений свежие. Диапазоны учитывают допуски; зелёный статус относится только к экспериментальному порогу.';
  const riskText={below:'интервал ниже порога опыта',uncertain:'интервал пересекает порог опыта',exceedance:'интервал выше порога опыта',conflict:'есть противоречие модели'};
  $('#assessment').textContent=`A: ${riskText[s.risk.ca]}. B: ${riskText[s.risk.cb]}. Вывод условен относительно модели и границ ошибок.`;
  $('#quality-summary').textContent=`Используются сейчас: ${used.length?used.map(k=>k.toUpperCase()).join(', '):'нет свежих каналов'}. ${Object.entries(s.sensors).filter(([,v])=>!v.usable).map(([k,v])=>`${k.toUpperCase()}: ${qualityNames[v.quality]}${v.age_s===null?'':', возраст '+fmt(v.age_s,0)+' с'}`).join('; ')}`;
  $('#fault-list').replaceChildren(...s.quality.faults.map(fault=>{const line=document.createElement('p');line.className='tiny';line.textContent=`${fmt(fault.time,0)} с · ${fault.quantity.toUpperCase()}: прогноз [${fmt(fault.predicted[0])}; ${fmt(fault.predicted[1])}], интервал показания [${fmt(fault.measured_interval[0])}; ${fmt(fault.measured_interval[1])}].`;return line;}));
  $('#nominal-status').textContent=`Совместимых постоянных эталонов: ${s.candidate_count} / ${s.hypothesis_count}. Их количество не задаёт вероятность и не определяет основной интервал.`;
  for(const [id,q]of [['a',e.qa.mean],['b',e.qb.mean],['bypass',e.ql.mean],['inlet',e.qt.mean],['return',e.qt.mean]]){
    const line=$('#air-'+id);line.style.strokeWidth=String(1+Math.min(5,q/12));line.style.animationDuration=`${Math.max(.5,65/Math.max(q,1))}s`;line.style.animationPlayState=s.paused?'paused':'running';
  }
  for(const [key,value]of Object.entries(s.sensors))$(`[data-sensor="${key}"]`).classList.toggle('failed',!value.usable);
  $('#map-qa').textContent=`Q: ${range(e.qa,1)}`;$('#map-qb').textContent=`Q: ${range(e.qb,1)}`;
  $('#map-ca').textContent=`CH₄: ${range(e.ca)}%`;$('#map-cb').textContent=`CH₄: ${range(e.cb)}%`;$('#map-return').textContent=`${range(e.cr)}% CH₄`;
  const colors={below:'#193d40',uncertain:'#594a2b',exceedance:'#623941',conflict:'#623941'};
  $('#face-a').style.fill=colors[s.risk.ca];$('#face-b').style.fill=colors[s.risk.cb];
  $('#balance').textContent=$('#showTruth').checked?`Эталон: невязка ${s.truth.continuity_error.toExponential(1)} м³/с`:'Связь потоков: QT = QA + QB + Qобхода';
  $('#truth-strip').hidden=!$('#showTruth').checked;
  $('#truth-strip').textContent=`Эталон только для проверки: A ${fmt(s.truth.ca)}% · B ${fmt(s.truth.cb)}% · возврат ${fmt(s.truth.cr)}%; мощность ${fmt(s.truth.power_kw,1)} кВт. Скрытые множители R: ${fmt(s.params.resistance_a)}/${fmt(s.params.resistance_b)}, G: ${fmt(s.params.gas_a)}/${fmt(s.params.gas_b)}. Они не подаются наблюдателю.`;
  $('#process-summary').textContent=`Известные команды: вентилятор ${fmt(s.params.fan*100,0)}% · проводимость обхода ×${fmt(s.params.leakage,2)}. Линии показывают оценку расхода.`;
  renderObject();renderRankings(s);
  if(!sensorRowsBuilt)buildSensorRows(s);
  for(const [key,sensor]of Object.entries(s.sensors)){
    $('#row-'+key).classList.toggle('failed',!sensor.usable);
    $('#reading-'+key).textContent=fmt(sensor.usable?s.readings[key]:sensor.last_value);
    $('#quality-'+key).textContent=qualityNames[sensor.quality]+(sensor.frozen?' · время не обновляется':'');
    $('#age-'+key).textContent=sensor.age_s===null?'нет показания':`${sensor.usable?'измерение':'последнее показание'} · ${fmt(sensor.age_s,0)} с`;
    const button=$(`[data-toggle="${key}"]`),repair=sensor.failed||!sensor.usable;
    button.textContent=repair?'Восстановить':'Откл.';button.setAttribute('aria-label',`${repair?'Восстановить':'Отключить'} ${key.toUpperCase()}`);
    setInput('#cost-'+key,sensor.cost);
  }
  renderSensorSettings();renderComparison(s);
  $('#event-log').replaceChildren(...s.events.slice().reverse().map(event=>{const li=document.createElement('li');li.textContent=`${fmt(event.time,0)} с · ${event.text}`;return li;}));
  $('#sample-age').textContent=`Ревизия ${s.revision} · seed ${s.seed}`;
  if(!s.replay_available)$('#import-status').textContent='Журнал превысил 4000 записей. Начните новый опыт, чтобы сохранить его для воспроизведения.';
  drawChart(s);
}

function drawChart(s){
  const points=new Map((s.series||[]).map(row=>[row.t,{t:row.t,low:row.estimate.ca.low,high:row.estimate.ca.high,truth:row.ca,conflict:row.conflict}]));
  points.set(s.time,{t:s.time,low:s.estimate.ca.low,high:s.estimate.ca.high,truth:s.truth.ca,conflict:s.conflict});
  const rows=[...points.values()].sort((a,b)=>a.t-b.t).slice(-160),W=1100,H=180,L=48,B=28,T=12;
  const loT=rows[0].t,hiT=Math.max(loT+60,rows.at(-1).t),truth=$('#showTruth').checked;
  const maximum=Math.max(1.5,...rows.map(row=>Math.max(row.high,truth?row.truth:0)))*1.12;
  const x=t=>L+(t-loT)/(hiT-loT)*(W-L-20),y=v=>T+(H-B-T)*(1-v/maximum);
  let html='';
  for(let i=0;i<4;i++){const value=maximum*i/3;html+=`<path d="M${L} ${y(value)}H${W}" stroke="#29404d"/><text x="2" y="${y(value)+4}" fill="#90a7b4" font-size="11">${fmt(value,1)}%</text>`;}
  const band=rows.map(row=>`${x(row.t)},${y(row.high)}`).concat(rows.slice().reverse().map(row=>`${x(row.t)},${y(row.low)}`)).join(' ');
  html+=`<polygon points="${band}" fill="#77e2ce" opacity=".18"/>`;
  for(let i=1;i<rows.length;i++)if(rows[i].conflict)html+=`<rect x="${x(rows[i-1].t)}" y="${T}" width="${Math.max(1,x(rows[i].t)-x(rows[i-1].t))}" height="${H-T-B}" fill="#f28080" opacity=".18"/>`;
  for(const key of ['low','high'])html+=`<polyline points="${rows.map(row=>`${x(row.t)},${y(row[key])}`).join(' ')}" fill="none" stroke="#77e2ce" stroke-width="1.5"/>`;
  if(truth)html+=`<polyline points="${rows.map(row=>`${x(row.t)},${y(row.truth)}`).join(' ')}" fill="none" stroke="#eac077" stroke-width="2"/>`;
  html+=`<path d="M${L} ${y(1)}H${W}" stroke="#f28080" stroke-dasharray="5 5"/><text x="${W-175}" y="${y(1)-5}" fill="#f28080" font-size="10">Порог опыта 1,0%</text><text x="${L}" y="177" fill="#90a7b4" font-size="10">${Math.round(loT)} с</text><text x="${W-65}" y="177" fill="#90a7b4" font-size="10">${Math.round(hiT)} с</text>`;
  $('#chart').innerHTML=html;
}

async function poll(){
  if(pending)return pending;
  pending=(async()=>{try{const response=await fetch('/api/state'),data=await response.json();if(!response.ok)throw Error(data.error||'Нет данных');render(data);}
    catch(error){document.body.classList.add('data-stale');$('#connection').textContent='Источник недоступен';$('#connection').className='badge error';$('#notice').className='notice error';$('#notice').textContent=error.message+' · повторное подключение…';}
    finally{pending=null;}})();
  return pending;
}

$('#rankings').addEventListener('click',event=>{const target=event.target.closest('[data-restore]');if(target)command({action:'restore',sensor:target.dataset.restore});});
$('#sensors').addEventListener('click',event=>{const target=event.target.closest('[data-toggle]');if(target)toggleSensor(target.dataset.toggle);});
$('#sensors').addEventListener('change',event=>{if(event.target.dataset.cost)command({action:'cost',sensor:event.target.dataset.cost,value:Number(event.target.value)});});
document.querySelectorAll('[data-scenario]').forEach(button=>button.onclick=()=>command({action:'scenario',name:button.dataset.scenario}));
document.querySelectorAll('[data-zone]').forEach(element=>{const select=()=>{selectedZone=element.dataset.zone;renderObject();};element.addEventListener('click',select);element.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}});});
$('#pause').onclick=()=>command({action:'pause'});$('#reset').onclick=()=>command({action:'reset'});
$('#new-seed').onclick=()=>command({action:'reset',seed:Number($('#seed').value)});
$('#target-width').onchange=event=>command({action:'target',value:Number(event.target.value)});
$('#checkpoint').onclick=()=>command({action:'checkpoint'});
$('#observer-reset').onclick=()=>command({action:'observer_reset'});
$('#cancel').onclick=()=>command({action:'scenario',name:'cancel'});
$('#speed').onchange=event=>command({action:'speed',value:Number(event.target.value)});
$('#fan').onchange=event=>command({action:'parameter',name:'fan',value:Number(event.target.value)/100});
$('#leakage').onchange=event=>command({action:'parameter',name:'leakage',value:Number(event.target.value)/100});
$('#showTruth').onchange=()=>{if(state)render(state);};
$('#sensor-choice').onchange=()=>{if(state){const sensor=state.sensors[$('#sensor-choice').value];$('#sensor-noise').value=sensor.noise;$('#sensor-delay').value=sensor.delay_s;$('#sensor-frozen').checked=sensor.frozen;}};
$('#sensor-settings').onsubmit=event=>{event.preventDefault();command({action:'sensor_config',sensor:$('#sensor-choice').value,settings:{noise:Number($('#sensor-noise').value),delay_s:Number($('#sensor-delay').value),frozen:$('#sensor-frozen').checked}});};
$('#import-choose').onclick=()=>$('#import-file').click();
$('#import-file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  try{
    if(file.size>2*1024*1024)throw Error('Размер опыта превышает 2 МиБ');
    const experiment=JSON.parse(await file.text());$('#import-status').textContent='Воспроизведение журнала…';
    const response=await fetch('/api/replay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(experiment)}),result=await response.json();
    if(!response.ok)throw Error(result.error||'Не удалось воспроизвести');
    $('#import-status').textContent='Опыт воспроизведён с исходным seed и журналом. Состояние паузы восстановлено; управление временем — вверху страницы.';
    await poll();
  }catch(error){$('#import-status').textContent=error.message;toast(error.message);}
  finally{event.target.value='';}
};

async function loadReference(){
  try{
    const response=await fetch('/api/reference'),data=await response.json();if(!response.ok)throw Error('Расчёт недоступен');
    const nodes={V1:[40,75],V2:[175,75],V5:[320,75],V7:[475,75],V8:[630,75],V3:[40,235],V4:[175,235],V6:[320,235],V9:[475,235],V10:[630,235]};
    let svg='<svg viewBox="0 0 680 300" role="img" aria-label="Опубликованная сеть Gucheng: девять ветвей и два выходных вентилятора">';
    for(const row of data.branches){const [x1,y1]=nodes[row.from],[x2,y2]=nodes[row.to];svg+=`<path d="M${x1} ${y1}L${x2} ${y2}" stroke="#77e2ce" stroke-width="3"/><text x="${(x1+x2)/2+5}" y="${(y1+y2)/2-12}" fill="#eac077" font-size="11">${escapeHTML(row.branch)} · ${fmt(row.computed_q,1)}</text>`;}
    for(const [id,[x,y]]of Object.entries(nodes))svg+=`<circle cx="${x}" cy="${y}" r="13" fill="#193d40" stroke="#77e2ce"/><text x="${x}" y="${y+30}" fill="#edf4f3" text-anchor="middle" font-size="11">${id}</text>`;
    svg+='</svg>';
    const table=`<div class="table-wrap"><table><thead><tr><th>Ветвь</th><th>В публикации, м³/с</th><th>Расчёт, м³/с</th><th>Различие</th></tr></thead><tbody>${data.branches.map(row=>`<tr><td>${escapeHTML(row.branch)}</td><td>${fmt(row.published_q,2)}</td><td>${fmt(row.computed_q,3)}</td><td>${fmt(row.relative_difference*100,3)}%</td></tr>`).join('')}</tbody></table></div>`;
    $('#reference-result').innerHTML=`<p>Максимальное отличие расходов: <b>${fmt(data.max_relative_flow_difference*100,3)}%</b>. Энергетическая невязка: ${data.max_energy_residual_pa.toExponential(2)} Па.</p><div class="reference-network">${svg}</div>${table}<p class="tiny">Совпадение с публикацией не является независимой полевой валидацией. Метан и активные объёмы основного стенда остаются синтетическими.</p>`;
  }catch(error){$('#reference-result').textContent=error.message;}
}
async function loadEvaluation(){
  try{
    const response=await fetch('/api/evaluation'),data=await response.json();if(!response.ok)throw Error(data.error||'Нет результатов');
    const names={selected:'Модельный рейтинг',fixed_priority:'Фиксированный приоритет',simple_width_per_cost:'Простое правило «ширина / стоимость»',random_expected:'Случайный выбор',oracle:'Оракул с известным эталоном'};
    $('#evaluation-result').innerHTML=`<p>${data.summary.cases} синтетических случаев. Каждое восстановление проверено из одинакового исходного состояния.</p><div class="table-wrap"><table><thead><tr><th>Стратегия</th><th>Средний выигрыш / стоимость</th></tr></thead><tbody>${Object.entries(data.summary.mean).map(([key,value])=>`<tr><td>${escapeHTML(names[key])}</td><td>${fmt(value,6)}</td></tr>`).join('')}</tbody></table></div><p>С простым правилом результат совпал в ${data.summary.versus.simple_width_per_cost.equal} случаях из ${data.summary.cases}. Преимущество более сложного расчёта над этим правилом не установлено.</p><p class="tiny">${data.coverage.checks} проверок внутри допущений: нарушений включения эталона ${data.coverage.failures}. Это не доверительная вероятность и не полевая валидация. Стресс-тесты показывают необнаруженный выход за границы при всех отключённых каналах.</p>`;
  }catch(error){$('#evaluation-result').textContent=error.message;}
}
poll();setInterval(poll,1000);loadReference();loadEvaluation();
