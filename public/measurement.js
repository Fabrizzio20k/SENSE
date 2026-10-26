/* La UI solo envía inicio/cierre/consulta; las activaciones pertenecen al orquestador. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const labels = {WAIT:'Espera', ACQUIRE:'Sensores', ASSESS:'Política', VISION:'YOLO', INTERPRET:'Interpretación', REPORT:'Registro', DEGRADED:'Degradado'};
  const statusLabels = {VALID:'Vigente', UNKNOWN:'Desconocido', STALE:'Vencido', CONFLICTING:'Conflicto', UNAVAILABLE:'Sin datos', ERROR:'Error'};
  const modes = {A:'A · Periódico', B:'B · Reactivo', C:'C · Adaptativo', D:'D · Adaptativo + texto', E:'E · Adaptativo + multimodal'};
  const answerStatuses = {RESOLVED:'Resuelta',PARTIAL:'Con limitaciones',ABSTAINED:'Evidencia insuficiente',PENDING:'Pendiente',INTERPRETED:'Interpretación disponible',NOT_APPLICABLE:'No aplica'};
  const runStatuses = {RUNNING:'En ejecución',COMPLETED:'Finalizada',FAILED:'Finalizada con error',INTERRUPTED:'Interrumpida'};
  const informationNames = {PRESENCE_REQUIRED:'presencia vigente del radar',VISUAL_COUNT_REQUIRED:'conteo visual vigente',ENVIRONMENT_STATUS_REQUIRED:'lecturas ambientales',CONFLICT_RESOLUTION_REQUIRED:'evidencia para aclarar el conflicto',TEXT_INTERPRETATION_REQUIRED:'interpretación textual adicional',MULTIMODAL_INTERPRETATION_REQUIRED:'interpretación de una imagen pertinente',temperature:'temperatura',humidity:'humedad',aqi:'AQI ENS160',tvoc:'TVOC',eco2:'eCO₂ estimado',presence:'presencia',count:'conteo visual'};
  const eventNames = {TEMP_RISE:'Subida de temperatura',HUMIDITY_RISE:'Subida de humedad',AQI_WORSENED:'Empeoramiento del AQI ENS160',ECO2_THRESHOLD_CROSSED:'Cruce del umbral de eCO₂ estimado'};
  const timeLabel = value => {const date=new Date(value);return value&&!Number.isNaN(date.getTime())?date.toLocaleTimeString():'—';};
  let current = {}, connected = false, pending = false, ready = false, sandboxBusy = false, historyKey = '', lastDetails = '', lastInterpretations = '';
  const text = (id, value) => {const node=byId(id); const next=String(value ?? '—'); if(node.textContent!==next)node.textContent=next;};
  const make = (tag, value, className) => {const node=document.createElement(tag); if(value!==undefined)node.textContent=String(value); if(className)node.className=className; return node;};
  function answerText(answer){
    const value=answer.answer;
    if(answer.question_id==='Q2')return typeof value==='number'?value+' '+(value===1?'persona visible':'personas visibles'):'Sin conteo visual vigente.';
    if(answer.question_id==='Q3'&&value&&typeof value==='object'&&!Array.isArray(value))return Object.entries(value).map(([key,reading])=>{
      const unit={'ppm equivalent':'ppm eq.','ENS160 AQI':'nivel ENS160'}[reading.unit]||reading.unit||'';
      return (informationNames[key]||key)+': '+(reading.value==null?'sin lectura':reading.value+' '+unit)+' · '+(statusLabels[reading.status]||'Desconocido');
    }).join('\n');
    if(answer.question_id==='Q4'&&Array.isArray(value))return value.length?value.map(event=>{
      const unit={TEMP_RISE:' °C',HUMIDITY_RISE:' puntos de humedad',AQI_WORSENED:' niveles ENS160',ECO2_THRESHOLD_CROSSED:' ppm eq. sobre el umbral'}[event.event_type]||'';
      return (eventNames[event.event_type]||event.event_type)+(typeof event.magnitude==='number'?' · '+event.magnitude+unit:'')+' · '+timeLabel(event.captured_at);
    }).join('\n'):'Sin episodios confirmados en esta ejecución.';
    if(Array.isArray(value))return value.join('\n');
    return value==null?'Sin respuesta con la evidencia disponible.':typeof value==='string'?value:JSON.stringify(value);
  }
  const nodes = {};
  for (const [state,label] of Object.entries(labels)) {
    const node=make('li',undefined,'pipeline-node'), icon=make('span','○','node-icon'), title=make('strong',state,'node-title'), detail=make('span',label,'node-label');
    node.dataset.state=state;node.append(icon,title,detail); byId('measurement-pipeline').append(node); nodes[state]={node,icon,detail,label};
  }
  const observations = {presence:['Radar','presence'], count:['Personas visibles','visible_people'], temperature:['Temperatura','°C'], humidity:['Humedad','%RH'], aqi:['AQI ENS160','ENS160 AQI'], tvoc:['TVOC','ppb'], eco2:['eCO₂ estimado','ppm equivalent']};
  const cards = {};
  const answerNodes = {};
  const interpretationNodes = new Map();
  for (const [key,[label]] of Object.entries(observations)) {
    const card=make('article',undefined,'card'), title=make('p',label,'sub'), value=make('p','—','measurement-value'), age=make('p','Sin evidencia','evidence-age'), status=make('span','Desconocido','evidence-status');
    const control=key==='presence'?make('div',undefined,'presence-control'):null;
    if(control){
      const mode=make('button','Auto'), toggle=make('button','No detectada');
      mode.onclick=()=>setPresence(current.presence_control?.mode==='MANUAL'?{mode:'auto'}:{mode:'manual',detected:!!current.context?.observations?.presence?.value});
      toggle.onclick=()=>setPresence({mode:'manual',detected:!current.presence_control?.detected});
      control.append(mode,toggle);
    }
    card.append(title,value,age,status); if(control)card.append(control); byId('measurement-observations').append(card); cards[key]={title,value,age,status,control};
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
  async function setPresence(body){
    if(pending)return;pending=true;controls();text('measurement-error','');
    try{await post('/api/experiments/presence',body);}
    catch(error){text('measurement-error',error.message);}
    finally{pending=false;controls();}
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
        const article=make('article',undefined,'question-result'),heading=make('h3'),value=make('p',undefined,'answer-value'),status=make('p',undefined,'answer-meta'),pending=make('p',undefined,'answer-limitations'),detail=make('details'),contract=make('pre');
        detail.append(make('summary','Evidencia y contrato'),contract);article.append(heading,value,status,pending,detail);byId('measurement-answers').append(article);
        nodes=answerNodes[answer.question_id]={article,heading,value,status,pending,contract};
      }
      nodes.heading.textContent=answer.question_id+' · '+answer.question;
      nodes.value.textContent=answerText(answer);
      const source=answer.interpretation_id?'Gemma':{Q1:'Radar',Q2:'YOLO',Q3:'Sensores ambientales',Q4:'Reglas ambientales',Q5:'Reglas de contexto',Q6:'Reglas de contexto',Q7:'Análisis de imagen'}[answer.question_id]||'SENSE';
      nodes.status.textContent=(answerStatuses[answer.status]||answer.status||'Sin evaluar')+' · '+source+' · '+timeLabel(answer.evaluated_at);
      nodes.article.dataset.status=answer.status;
      const missing=(answer.pending_information||[]).map(item=>informationNames[item]||item);
      nodes.pending.textContent=[...(answer.limitations||[]),...(missing.length?['Falta: '+missing.join(', ')+'.']:[])].join('\n');
      nodes.contract.textContent=JSON.stringify(answer,null,2);
    }
    for(const [qid,nodes] of Object.entries(answerNodes))nodes.article.hidden=!data.answers?.[qid]||data.answers[qid].status==='NOT_APPLICABLE';
    byId('measurement-answers-empty').hidden=Object.keys(data.answers||{}).length>0;
    const visibleInterpretations=(data.interpretations||[]).slice(-10).reverse();
    const interpretationKey=visibleInterpretations.map(result=>result.interpretation_id).join('/');
    if(interpretationKey!==lastInterpretations){
    lastInterpretations=interpretationKey;
    for(const id of interpretationNodes.keys())if(!visibleInterpretations.some(item=>item.interpretation_id===id))interpretationNodes.delete(id);
    byId('measurement-interpretations').replaceChildren(...visibleInterpretations.map(result=>{
      if(interpretationNodes.has(result.interpretation_id))return interpretationNodes.get(result.interpretation_id);
      const article=make('article',undefined,'interpretation');
      article.append(make('strong',result.question_id+' · '+(result.image_id?'Con imagen':'Solo texto')+' · '+(result.validation_status==='VALIDATED'?'Formato validado':'Respuesta rechazada')),make('p','Finalizó a las '+timeLabel(result.completed_at)+' · evidencia histórica','sub'));
      if(result.validation_status==='VALIDATED'){
        for(const [key,label] of [['inferences','Inferencias'],['unknowns','Desconocidos'],['recommendations','Recomendaciones no críticas']])if(result[key]?.length)article.append(make('p',label+': '+result[key].join(' ')));
      }else article.append(make('p',result.validation_error||'Respuesta rechazada.'));
      const details=make('details');details.append(make('summary','Registro completo'),make('pre',JSON.stringify(result,null,2)));article.append(details);interpretationNodes.set(result.interpretation_id,article);return article;
    }));
    }
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
        const row=make('tr');for(const value of [new Date(run.start_time).toLocaleString(),run.mode,runStatuses[run.status]||run.status])row.append(make('td',value));
        const cell=make('td'),link=make('a','Descargar registro');link.href='/api/experiments/'+encodeURIComponent(run.run_id)+'/export';cell.append(link);row.append(cell);return row;
      }));
      text('measurement-history-note',runs.length?'Últimas '+runs.length+' ejecuciones.':'Todavía no hay ejecuciones.');
    }catch(error){text('measurement-history-note',error.message);}
  }
  byId('measurement-history-details').addEventListener('toggle',()=>{if(byId('measurement-history-details').open)history();});
  window.measurement = {
    connection(value){connected=value;controls();if(!value){text('measurement-state','Conexión interrumpida; estado sin actualizar.');text('measurement-answer-note','Conexión interrumpida. Se muestran las últimas respuestas recibidas.');}},
    render(data,phases,busy){
      current=data||{};connected=true;sandboxBusy=!!busy;ready=Object.values(phases||{}).length===3&&Object.values(phases).every(p=>!['waiting','loading'].includes(p.status));
      controls();
      for(const option of modeSelect.options)option.disabled=current.enabled_modes&&!current.enabled_modes.includes(option.value);
      if(current.run&&current.running)modeSelect.value=current.run.mode;
      const visualQuestion=Array.from(byId('measurement-question').options).find(option=>option.value==='Q7');
      if(visualQuestion)visualQuestion.disabled=current.run?.mode!=='E';
      if(visualQuestion?.disabled&&byId('measurement-question').value==='Q7')byId('measurement-question').value='Q1';
      const run=current.run;
      text('measurement-run',run?(modes[run.mode]||run.mode)+' · '+(runStatuses[run.status]||run.status):'Sin ejecución · parámetros de piloto');
      const stateLabel={WAIT:'Esperando datos o un disparador',ACQUIRE:'Recopilando observaciones',ASSESS:'Evaluando la evidencia',VISION:'Capturando imagen y ejecutando YOLO',INTERPRET:'Solicitando interpretación',REPORT:'Guardando respuestas',DEGRADED:'Continuando con información parcial'}[current.fsm]||current.fsm;
      text('measurement-state',current.running?stateLabel:current.reserved?'Esperando a que terminen las tareas activas':run?'Ejecución finalizada':'Listo para comenzar');
      text('measurement-run-metadata',JSON.stringify({run,cycle:current.cycle,config_version:current.config_version},null,2));
      const download=byId('measurement-current-export');download.hidden=!run;if(run)download.href='/api/experiments/'+encodeURIComponent(run.run_id)+'/export';
      const evaluated=Object.values(current.answers||{}).map(answer=>answer.evaluated_at).filter(Boolean).sort().at(-1);
      text('measurement-updated',evaluated?'Última evaluación: '+timeLabel(evaluated):'Sin evaluación todavía');
      text('measurement-answer-note',current.running?'Actualización automática con la evidencia disponible. Las lecturas pueden estar incompletas o vencidas.':run?'Últimas respuestas de la ejecución finalizada. El registro conserva las anteriores.':'Las respuestas se actualizan automáticamente durante la ejecución.');
      const lastError=current.errors?.at(-1);text('measurement-task-error',lastError?'Último fallo · '+timeLabel(lastError.timestamp)+': '+lastError.detail:'');
      const actions=current.cycle?.actions||[], lastTransition=(current.transitions||[]).at(-1);
      for(const [state,{node,icon,detail,label}] of Object.entries(nodes)){
        const active=current.running&&current.fsm===state,waiting=active&&state==='WAIT',done=actions.includes(state)&&!active,skipped=!active&&!done&&actions.includes('REPORT');
        node.className='pipeline-node'+(waiting?' waiting':active?' active':done?' done':skipped?' skipped':'');
        node.setAttribute('aria-current',active?'step':'false');icon.textContent=waiting?'⌛':active?'↻':done?'✓':skipped?'−':'○';detail.textContent=waiting?label+' · esperando evento':active?label+' · ejecutando':done?label+' · completado':skipped?label+' · sin ejecutar':label+' · pendiente';
      }
      const graph=byId('measurement-graph');
      graph.dataset.edge=lastTransition?lastTransition.from+'-'+lastTransition.to:'';
      text('measurement-transition-live',lastTransition?'Última transición: '+lastTransition.from+' → '+lastTransition.to+' · '+lastTransition.reason:'Esperando inicio.');
      const background=byId('measurement-background-tasks'), activeTasks=(current.tasks?.active||[]);
      background.hidden=!activeTasks.length;
      background.replaceChildren(...activeTasks.map(task=>make('span',task.question_id+' · '+(task.status==='RUNNING'?'en segundo plano':'esperando finalización')+' · '+task.elapsed_seconds+' s','background-task '+(task.status==='RUNNING'?'running':''))));
      byId('measurement-degraded').classList.toggle('active',current.fsm==='DEGRADED'||actions.includes('DEGRADED'));
      byId('measurement-degraded').hidden=!actions.includes('DEGRADED')&&current.fsm!=='DEGRADED';
      text('measurement-degraded','Este ciclo produjo información parcial o una abstención por falta de evidencia.');
      for(const [key,card] of Object.entries(cards)){
        const observation=current.context?.observations?.[key],status=observation?.status||'UNKNOWN';
        card.value.textContent=observation?.value==null?'—':key==='presence'?(observation.value?'Detectada':'No detectada'):String(observation.value)+(key==='temperature'?' °C':key==='humidity'?' %':key==='tvoc'?' ppb':key==='eco2'?' ppm eq.':'');
        card.age.textContent=observation?Math.floor(observation.age_seconds)+' s · '+observation.region:'Sin evidencia';
        card.status.textContent=statusLabels[status]||status;card.status.dataset.status=status;
        if(key==='presence'){
          const metadata=observation?.metadata||{},trigger=current.reactive_trigger;
          const source={total_distance_cm:'distancia total',motion_distance_cm:'blanco en movimiento',static_distance_cm:'blanco estático'}[metadata.trigger_distance_source];
          card.title.textContent=run?.mode==='B'?'Radar · zona B':'Radar';
          if(metadata.trigger_distance_cm!=null)card.age.textContent+='\n'+metadata.trigger_distance_cm+' cm · '+(source||'blanco activo');
          if(run?.mode==='B'){
            card.value.textContent={NEAR:'Dentro de zona',FAR:'Fuera de zona',CONFIRMING:'Confirmando…',UNKNOWN:'Zona desconocida'}[trigger?.state]||'Zona desconocida';
            if(observation?.value!=null)card.age.textContent+='\n'+(status==='VALID'?'Radar: ':'Última lectura: ')+(observation.value?'presencia detectada':'sin presencia detectada');
          }
          if(card.control){
            const manual=current.presence_control?.mode==='MANUAL', enabled=!!(current.running&&['C','D','E'].includes(run?.mode)&&!pending);
            card.control.hidden=!['C','D','E'].includes(run?.mode);
            const [mode,toggle]=card.control.children;
            mode.textContent=manual?'Manual':'Auto';mode.className=manual?'manual':'';mode.disabled=!enabled;
            toggle.textContent=current.presence_control?.detected?'Detectada':'No detectada';toggle.disabled=!enabled||!manual;
          }
        }
      }
      const trigger=current.reactive_trigger,visionDecision=(current.decisions||[]).filter(item=>item.kind==='VISION').at(-1);
      let triggerText='';
      if(current.running&&run?.mode==='B'&&trigger){
        const rule='B: entrada < '+trigger.enter_below_cm+' cm · salida ≥ '+trigger.exit_at_or_above_cm+' cm · '+trigger.required_samples+' lecturas.';
        const reason={RADAR_DISTANCE_UNKNOWN:'Sin distancia válida y vigente; esperando al radar.',RADAR_ZONE_CONFIRMING:'Confirmando zona: '+trigger.confirmed_samples+'/'+trigger.required_samples+'.',
          COOLDOWN_ACTIVE:'Esperando el intervalo mínimo entre capturas.',CAMERA_UNAVAILABLE:'YOLO no está disponible.',DUPLICATE_REQUEST:'Captura visual en curso.',
          INSUFFICIENT_MEMORY:'Captura pospuesta por memoria disponible.',CPU_BUDGET:'Captura pospuesta por carga de CPU.',RATE_LIMIT:'Esperando el presupuesto de activaciones.',
          RADAR_NEAR_CONFIRMED:'Zona próxima inicial confirmada: captura autorizada.',RADAR_ZONE_ENTERED:'Entrada confirmada: captura autorizada.',RADAR_ZONE_EXITED:'Salida confirmada: captura autorizada.'}[visionDecision?.reason];
        triggerText=rule+' '+(reason||(trigger.state==='UNKNOWN'?'Sin distancia válida y vigente.':trigger.state==='CONFIRMING'?'Confirmando zona: '+trigger.confirmed_samples+'/'+trigger.required_samples+'.':'Esperando otro cambio confirmado de zona.'));
        if(current.context?.observations?.count?.status==='STALE')triggerText+=' El conteo está vencido; B no lo renueva únicamente por antigüedad.';
      }
      text('measurement-trigger',triggerText);
      const tasks=current.tasks||{},active=tasks.active||[];
      const gemmaTasks=active.filter(task=>task.agent==='InterpretationAgent');
      byId('measurement-worker').classList.toggle('loading',gemmaTasks.length>0);
      text('measurement-worker',gemmaTasks.length?gemmaTasks.map(task=>task.question_id+' · '+(task.status==='RUNNING'?'Interpretando':task.status==='DRAINING'?'Esperando finalización física':'Estado del runtime sin confirmar')+' · '+task.elapsed_seconds+' s').join('\n')+'\nEn cola: '+(tasks.queued||0):tasks.queued?'Interpretaciones en espera: '+tasks.queued:'');
      const interpretationCount=(current.interpretations||[]).length;
      byId('measurement-interpretations-empty').hidden=interpretationCount>0;
      text('measurement-interpretation-count',interpretationCount?Math.min(10,interpretationCount)+' resultados recientes':'');
      text('measurement-interpretations-empty',!run?'Gemma se utiliza en D y E cuando la política identifica una necesidad adicional.':!['D','E'].includes(run.mode)?'El modo '+run.mode+' responde mediante reglas; no utiliza Gemma.':gemmaTasks.length||tasks.queued?'Todavía no hay resultados: una interpretación está pendiente.':'Todavía no hay interpretaciones. Gemma solo se invoca cuando puede aportar información adicional.');
      text('measurement-resources',JSON.stringify({resources:current.resources,workers:tasks,dispatcher:current.dispatcher},null,2));
      if(current.error)text('measurement-error',current.error);
      renderDetails(current);
      const nextHistory=(run?.run_id||'')+'/'+(run?.status||'');if(nextHistory!==historyKey){historyKey=nextHistory;if(byId('measurement-history-details').open)history();}
    }
  };
})();
