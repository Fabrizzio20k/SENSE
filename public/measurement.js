/* La UI solo envía inicio/cierre/consulta; las activaciones pertenecen al orquestador. */
(() => {
  'use strict';
  const root = document.getElementById('measurement');
  const byId = id => document.getElementById(id);
  const labels = {WAIT:'Espera', ACQUIRE:'Sensores', ASSESS:'Política', VISION:'YOLO', INTERPRET:'Interpretación', REPORT:'Registro'};
  const statusLabels = {VALID:'Vigente', UNKNOWN:'Desconocido', STALE:'Vencido', CONFLICTING:'Conflicto', UNAVAILABLE:'Sin datos', ERROR:'Error'};
  const modes = {A:'A · Periódico', B:'B · Reactivo', C:'C · Adaptativo', D:'D · Adaptativo + texto', E:'E · Adaptativo + multimodal'};
  let current = {}, connected = false, pending = false, ready = false, sandboxBusy = false, historyKey = '', lastDetails = '';
  const text = (id, value) => {const node=byId(id); const next=String(value ?? '—'); if(node.textContent!==next)node.textContent=next;};
  const make = (tag, value, className) => {const node=document.createElement(tag); if(value!==undefined)node.textContent=String(value); if(className)node.className=className; return node;};
  const nodes = {};
  for (const [state,label] of Object.entries(labels)) {
    const node=make('li',undefined,'pipeline-node'), icon=make('span','○','node-icon'), title=make('strong',state,'node-title'), detail=make('span',label,'node-label');
    node.append(icon,title,detail); byId('measurement-pipeline').append(node); nodes[state]={node,icon,detail,label};
  }
  const observations = {presence:['Radar','presence'], count:['Personas visibles','visible_people'], temperature:['Temperatura','°C'], humidity:['Humedad','%RH'], aqi:['AQI ENS160','ENS160 AQI'], tvoc:['TVOC','ppb'], eco2:['eCO₂ estimado','ppm equivalent']};
  const cards = {};
  const answerNodes = {};
  const interpretationNodes = new Map();
  for (const [key,[label]] of Object.entries(observations)) {
    const card=make('article',undefined,'card'), title=make('p',label,'sub'), value=make('p','—','measurement-value'), age=make('p','Sin evidencia','evidence-age'), status=make('span','Desconocido','evidence-status');
    card.append(title,value,age,status); byId('measurement-observations').append(card); cards[key]={value,age,status};
  }
  const modeSelect = byId('measurement-mode');
  for(const [mode,label] of Object.entries(modes)){const option=make('option',label);option.value=mode;modeSelect.append(option);}
  function controls(){
    byId('measurement-toggle').disabled=!!(pending||!connected||(!current.running&&(!ready||sandboxBusy||current.reserved)));
    modeSelect.disabled=!!(pending||current.running||current.reserved);
    byId('measurement-toggle').textContent=pending?'Procesando…':current.running?'Finalizar':'Comenzar';
    byId('measurement-query').disabled=pending||!connected||!current.running;
  }
  async function post(url,body){
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'No se pudo completar la operación.');return data;
  }
  byId('measurement-toggle').onclick=async()=>{
    if(pending)return;pending=true;controls();text('measurement-error','');
    try{
      const stopping=current.running;
      await post('/api/experiments/'+(stopping?'stop':'start'),{mode:modeSelect.value});
      if(stopping)current={...current,running:false,reserved:true};
      else current={...current,running:true,reserved:true};
    }catch(error){text('measurement-error',error.message);}
    finally{pending=false;controls();}
  };
  byId('measurement-query').onclick=async()=>{
    pending=true;controls();
    try{await post('/api/experiments/query',{question_id:byId('measurement-question').value});}
    catch(error){text('measurement-error',error.message);}
    finally{pending=false;controls();}
  };
  function renderDetails(data){
    const key=JSON.stringify([data.answers,data.interpretations,data.transitions,data.errors,data.decisions]);
    if(key===lastDetails)return;lastDetails=key;
    for(const answer of Object.values(data.answers||{})){
      let nodes=answerNodes[answer.question_id];
      if(!nodes){
        const article=make('article',undefined,'question-result'),heading=make('h3'),value=make('p'),status=make('p',undefined,'sub'),pending=make('p',undefined,'sub'),detail=make('details'),contract=make('pre');
        detail.append(make('summary','Evidencia y contrato'),contract);article.append(heading,value,status,pending,detail);byId('measurement-answers').append(article);
        nodes=answerNodes[answer.question_id]={article,heading,value,status,pending,contract};
      }
      nodes.heading.textContent=answer.question_id+' · '+answer.question;
      nodes.value.textContent=typeof answer.answer==='string'?answer.answer:JSON.stringify(answer.answer,null,2);
      nodes.status.textContent=answer.status+' · '+(answer.limitations||[]).join(' ');
      nodes.pending.textContent=answer.pending_information?.length?'Pendiente: '+answer.pending_information.join(', '):'';
      nodes.contract.textContent=JSON.stringify(answer,null,2);
    }
    for(const [qid,nodes] of Object.entries(answerNodes))nodes.article.hidden=!data.answers?.[qid];
    const visibleInterpretations=(data.interpretations||[]).slice(-10).reverse();
    for(const id of interpretationNodes.keys())if(!visibleInterpretations.some(item=>item.interpretation_id===id))interpretationNodes.delete(id);
    byId('measurement-interpretations').replaceChildren(...visibleInterpretations.map(result=>{
      if(interpretationNodes.has(result.interpretation_id))return interpretationNodes.get(result.interpretation_id);
      const article=make('article',undefined,'interpretation');
      article.append(make('strong',result.question_id+' · '+result.validation_status),make('p','Evidencia histórica · snapshot '+result.snapshot_id+' · imagen '+(result.image_id||'no enviada')));
      if(result.validation_status==='VALIDATED'){
        for(const [key,label] of [['inferences','Inferencias'],['unknowns','Desconocidos'],['recommendations','Recomendaciones no críticas']])if(result[key]?.length)article.append(make('p',label+': '+result[key].join(' ')));
      }else article.append(make('p',result.validation_error||'Respuesta rechazada.'));
      const details=make('details');details.append(make('summary','Registro completo'),make('pre',JSON.stringify(result,null,2)));article.append(details);interpretationNodes.set(result.interpretation_id,article);return article;
    }));
    byId('measurement-transitions').replaceChildren(...(data.transitions||[]).slice(-24).reverse().map(item=>{
      const row=make('tr');for(const value of [new Date(item.timestamp).toLocaleTimeString(),item.from+' → '+item.to,item.reason])row.append(make('td',value));return row;
    }));
    text('measurement-decisions',JSON.stringify({decisions:data.decisions||[],needs:data.needs||[],errors:data.errors||[]},null,2));
  }
  async function history(){
    try{
      const response=await fetch('/api/experiments');if(!response.ok)throw new Error('No se pudo cargar el historial.');
      const {runs}=await response.json();
      byId('measurement-history').replaceChildren(...runs.map(run=>{
        const row=make('tr');for(const value of [new Date(run.start_time).toLocaleString(),run.mode,run.status])row.append(make('td',value));
        const cell=make('td'),link=make('a','Descargar registro');link.href='/api/experiments/'+encodeURIComponent(run.run_id)+'/export';cell.append(link);row.append(cell);return row;
      }));
      text('measurement-history-note',runs.length?'Últimas '+runs.length+' ejecuciones.':'Todavía no hay ejecuciones.');
    }catch(error){text('measurement-history-note',error.message);}
  }
  byId('measurement-history-details').addEventListener('toggle',()=>{if(byId('measurement-history-details').open)history();});
  window.measurement = {
    connection(value){connected=value;controls();if(!value)text('measurement-state','Conexión interrumpida; estado sin actualizar.');},
    render(data,phases,busy){
      current=data||{};connected=true;sandboxBusy=!!busy;ready=Object.values(phases||{}).length===3&&Object.values(phases).every(p=>!['waiting','loading'].includes(p.status));
      controls();
      for(const option of modeSelect.options)option.disabled=current.enabled_modes&&!current.enabled_modes.includes(option.value);
      if(current.run&&current.running)modeSelect.value=current.run.mode;
      const visualQuestion=Array.from(byId('measurement-question').options).find(option=>option.value==='Q7');
      if(visualQuestion)visualQuestion.disabled=current.run?.mode!=='E';
      if(visualQuestion?.disabled&&byId('measurement-question').value==='Q7')byId('measurement-question').value='Q1';
      const run=current.run;
      text('measurement-run',run?run.mode+' · '+run.run_id+'\n'+run.status+' · '+(current.config_version||''):'Sin ejecución · parámetros de piloto');
      text('measurement-state',current.running?current.fsm+' · ciclo '+(current.cycle?.cycle_id?.slice(0,8)||'—'):current.reserved?'Finalizando workers; monitoreo MQTT disponible.':run?'Ejecución finalizada':'Listo para comenzar');
      const actions=current.cycle?.actions||[];
      for(const [state,{node,icon,detail,label}] of Object.entries(nodes)){
        const active=current.running&&current.fsm===state,done=actions.includes(state)&&!active,skipped=!active&&!done&&actions.includes('REPORT');
        node.className='pipeline-node'+(active?' active':done?' done':skipped?' skipped':'');
        node.setAttribute('aria-current',active?'step':'false');icon.textContent=active?'↻':done?'✓':skipped?'−':'○';detail.textContent=label+(skipped?' · sin ejecutar':'');
      }
      byId('measurement-degraded').classList.toggle('active',current.fsm==='DEGRADED'||actions.includes('DEGRADED'));
      text('measurement-degraded',actions.includes('DEGRADED')?'DEGRADED · resultado parcial o abstención registrada':'DEGRADED · ruta de recuperación ante fallos');
      for(const [key,card] of Object.entries(cards)){
        const observation=current.context?.observations?.[key],status=observation?.status||'UNKNOWN';
        card.value.textContent=observation?.value==null?'—':key==='presence'?(observation.value?'Detectada':'No detectada'):String(observation.value)+(key==='temperature'?' °C':key==='humidity'?' %':key==='tvoc'?' ppb':key==='eco2'?' ppm eq.':'');
        card.age.textContent=observation?Math.floor(observation.age_seconds)+' s · '+observation.region:'Sin evidencia';
        card.status.textContent=statusLabels[status]||status;card.status.dataset.status=status;
      }
      const tasks=current.tasks||{},active=tasks.active||[];
      byId('measurement-worker').classList.toggle('loading',active.length>0);
      text('measurement-worker',active.length?active.map(task=>task.agent+' · '+task.question_id+' · '+task.status+' · '+task.elapsed_seconds+' s').join('\n')+'\nCola Gemma: '+tasks.queued+'/'+tasks.queue_capacity:'Workers libres · cola Gemma: '+(tasks.queued||0));
      text('measurement-resources',JSON.stringify({resources:current.resources,workers:tasks,dispatcher:current.dispatcher},null,2));
      if(current.error)text('measurement-error',current.error);
      renderDetails(current);
      const nextHistory=(run?.run_id||'')+'/'+(run?.status||'');if(nextHistory!==historyKey){historyKey=nextHistory;if(byId('measurement-history-details').open)history();}
    }
  };
})();
