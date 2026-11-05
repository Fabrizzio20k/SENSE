/* La UI solo envía inicio/cierre/consulta; las activaciones pertenecen al orquestador. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const labels = {WAIT:'Espera', ACQUIRE:'Sensores', ASSESS:'Política', VISION:'YOLO', INTERPRET:'Interpretación', REPORT:'Registro', DEGRADED:'Degradado'};
  const stateDescriptions = {WAIT:'Esperando datos o un disparador',ACQUIRE:'Recopilando observaciones',ASSESS:'Evaluando la evidencia',VISION:'Capturando imagen y ejecutando YOLO',INTERPRET:'Solicitando interpretación',REPORT:'Guardando respuestas',DEGRADED:'Continuando con información parcial'};
  const statusLabels = {VALID:'Vigente', UNKNOWN:'Desconocido', STALE:'Vencido', CONFLICTING:'Conflicto', UNAVAILABLE:'Sin datos', ERROR:'Error'};
  const modes = {A:'A · Periódico', B:'B · Reactivo', C:'C · Adaptativo', D:'D · Adaptativo + texto', E:'E · Adaptativo + multimodal', F:'F · Multimodal + fallas por software'};
  const answerStatuses = {RESOLVED:'Resuelta',PARTIAL:'Con limitaciones',ABSTAINED:'Evidencia insuficiente',PENDING:'Pendiente',INTERPRETED:'Interpretación disponible',NOT_APPLICABLE:'No aplica'};
  const runStatuses = {RUNNING:'En ejecución',COMPLETED:'Finalizada',FAILED:'Finalizada con error',INTERRUPTED:'Interrumpida'};
  const informationNames = {PRESENCE_REQUIRED:'presencia vigente del radar',VISUAL_COUNT_REQUIRED:'conteo visual vigente',ENVIRONMENT_STATUS_REQUIRED:'lecturas ambientales',CONFLICT_RESOLUTION_REQUIRED:'evidencia para aclarar el conflicto',TEXT_INTERPRETATION_REQUIRED:'interpretación textual adicional',MULTIMODAL_INTERPRETATION_REQUIRED:'interpretación de una imagen pertinente',temperature:'temperatura',humidity:'humedad',aqi:'AQI ENS160',tvoc:'TVOC',eco2:'eCO₂ estimado',presence:'presencia',count:'conteo visual'};
  const eventNames = {TEMP_RISE:'Subida de temperatura',HUMIDITY_RISE:'Subida de humedad',AQI_WORSENED:'Empeoramiento del AQI ENS160',ECO2_THRESHOLD_CROSSED:'Cruce del umbral de eCO₂ estimado'};
  const scenarioSteps={
    S1:[['0–10 min','Aula vacía','Mantén el aula sin personas.'],['10–15 min','Entra una persona','Registra cuándo ingresó y se sentó.'],['15–30 min','Permanece sentada','Observa si se mantiene la evidencia sin tareas innecesarias.']],
    S2:[['0–30 min','Ocupación alta estable','Mantén el aula concurrida; registra solo cambios reales de ocupación.']],
    S3:[['0–10 min','Condición inicial','Mantén una concurrencia comparable a S2 y observa el ambiente.'],['10–20 min','Cambio ambiental','Modifica la ventilación de forma segura y registra la acción real.'],['20–30 min','Restaurar condición','Restablece la condición inicial y observa la evolución.']]
  };
  const scenarioStarts={S1:[0,600,900],S2:[0],S3:[0,600,1200]};
  const timeLabel = value => {const date=new Date(value);return value&&!Number.isNaN(date.getTime())?date.toLocaleTimeString():'—';};
  let current = {}, connected = false, pending = false, stopRequested = false, ready = false, sandboxBusy = false, historyKey = '', lastDetails = '', lastInterpretations = '', lastGuidance = '', flow = null, flowPulse = null, fallbackStage = null, selectedState = null, seenTransitionKey;
  const fallbackView={x:0,y:0,scale:1};
  const text = (id, value) => {const node=byId(id); const next=String(value ?? '—'); if(node.textContent!==next)node.textContent=next;};
  const make = (tag, value, className) => {const node=document.createElement(tag); if(value!==undefined)node.textContent=String(value); if(className)node.className=className; return node;};
  const graphEdges=[['WAIT','ACQUIRE'],['ACQUIRE','ASSESS'],['ASSESS','VISION'],['VISION','ASSESS'],['ASSESS','INTERPRET'],['INTERPRET','REPORT'],['ASSESS','REPORT'],['REPORT','WAIT'],['ASSESS','DEGRADED'],['VISION','DEGRADED'],['INTERPRET','DEGRADED'],['REPORT','DEGRADED'],['DEGRADED','REPORT']];
  const graphPositions={WAIT:{x:90,y:260},ACQUIRE:{x:285,y:260},ASSESS:{x:470,y:260},VISION:{x:470,y:410},INTERPRET:{x:670,y:410},REPORT:{x:860,y:260},DEGRADED:{x:670,y:85}};
  const graphIcon=state=>'/public/assets/sense-icons-v2/svg/'+(document.documentElement.dataset.theme==='dark'?'dark':'light')+'/'+state.toLowerCase()+'.svg';
  const compactFlow=window.matchMedia?.('(max-width:640px)');
  function applyFallback(){if(fallbackStage)fallbackStage.style.transform=`translate(${fallbackView.x}px,${fallbackView.y}px) scale(${fallbackView.scale})`;}
  function fitFallback(){
    const graph=byId('measurement-graph');if(!graph.clientWidth||!graph.clientHeight||compactFlow?.matches)return;
    fallbackView.scale=Math.min((graph.clientWidth-32)/1000,(graph.clientHeight-32)/500);
    fallbackView.x=(graph.clientWidth-1000*fallbackView.scale)/2;
    fallbackView.y=(graph.clientHeight-500*fallbackView.scale)/2;applyFallback();
  }
  function zoomFallback(amount){
    const graph=byId('measurement-graph'),old=fallbackView.scale,next=Math.max(.35,Math.min(2,old+amount));
    const centerX=(graph.clientWidth||1000)/2,centerY=(graph.clientHeight||500)/2;
    fallbackView.x=centerX-(centerX-fallbackView.x)*next/old;
    fallbackView.y=centerY-(centerY-fallbackView.y)*next/old;
    fallbackView.scale=next;applyFallback();
  }
  function initFallback(){
    if(fallbackStage)return;
    const graph=byId('measurement-graph');fallbackStage=make('div',undefined,'flow-fallback-stage');
    fallbackStage.append(byId('measurement-fallback-lines'),byId('measurement-pipeline'));graph.append(fallbackStage);
    graph.addEventListener('wheel',event=>{if(flow||compactFlow?.matches||!byId('measurement-inspection').open)return;event.preventDefault();zoomFallback(event.deltaY<0?.12:-.12);},{passive:false});
    let dragging=false,startX=0,startY=0;
    graph.addEventListener('pointerdown',event=>{if(flow||compactFlow?.matches||!byId('measurement-inspection').open||event.target.closest?.('button,.pipeline-node'))return;dragging=true;startX=event.clientX;startY=event.clientY;graph.setPointerCapture?.(event.pointerId);graph.classList.add('is-dragging');});
    graph.addEventListener('pointermove',event=>{if(!dragging)return;fallbackView.x+=event.clientX-startX;fallbackView.y+=event.clientY-startY;startX=event.clientX;startY=event.clientY;applyFallback();});
    const stop=()=>{dragging=false;graph.classList.remove('is-dragging');};graph.addEventListener('pointerup',stop);graph.addEventListener('pointercancel',stop);
  }
  function graphStyle(){
    const palette=getComputedStyle(document.documentElement), color=name=>palette.getPropertyValue('--'+name).trim();
    return [
      {selector:'node',style:{'shape':'round-rectangle','width':150,'height':106,'background-color':color('panel'),'border-width':2,'border-color':color('strong-line'),'background-image':'data(icon)','background-fit':'none','background-width':'42px','background-height':'42px','background-position-x':'50%','background-position-y':'16%','background-repeat':'no-repeat','label':'data(label)','color':color('ink'),'font-size':13,'font-weight':400,'text-wrap':'wrap','text-max-width':130,'text-valign':'center','text-halign':'center','text-margin-y':28,'line-height':1.35}},
      {selector:'edge',style:{'width':3,'line-color':color('strong-line'),'target-arrow-color':color('strong-line'),'target-arrow-shape':'triangle','curve-style':'bezier','arrow-scale':1.2}},
      {selector:'node.done',style:{'background-color':color('success-bg'),'border-color':color('success'),'color':color('success')}},
      {selector:'node.waiting',style:{'background-color':color('soft'),'border-color':color('strong-line')}},
      {selector:'node.active',style:{'background-color':color('info-bg'),'border-color':color('info'),'border-width':5,'underlay-color':color('info'),'underlay-opacity':.22,'underlay-padding':11,'color':color('info')}},
      {selector:'node.degraded',style:{'background-color':color('danger-bg'),'border-color':color('danger'),'color':color('danger')}},
      {selector:'node.inspected',style:{'border-color':color('accent'),'border-width':5,'underlay-color':color('accent'),'underlay-opacity':.18,'underlay-padding':13}},
      {selector:'edge.active',style:{'width':6,'line-color':color('info'),'target-arrow-color':color('info'),'line-style':'dashed','line-dash-pattern':[10,7],'line-dash-offset':-30,'overlay-color':color('info'),'overlay-opacity':.12,'overlay-padding':8}},
      {selector:'edge.done',style:{'line-color':color('success'),'target-arrow-color':color('success')}},
      {selector:'edge.inspected',style:{'overlay-color':color('accent'),'overlay-opacity':.12,'overlay-padding':10}}
    ];
  }
  function graphVisibility(){
    initFallback();
    const graphical=!!flow&&!compactFlow?.matches;
    byId('measurement-pipeline').hidden=graphical;
    const fallback=byId('measurement-fallback-lines');if(fallback)fallback.hidden=graphical;
    fallbackStage.hidden=graphical;
    byId('measurement-flow-canvas').hidden=!graphical;
    byId('measurement-flow-controls').hidden=!!compactFlow?.matches;
  }
  function initFlow(){
    if(flow||!byId('measurement-inspection').open||!window.cytoscape||compactFlow?.matches){graphVisibility();return;}
    const canvas=byId('measurement-flow-canvas'); if(!canvas)return;
    canvas.hidden=false;
    flow=window.cytoscape({container:canvas,elements:{nodes:Object.entries(labels).map(([id,label])=>({data:{id,label:id+'\n'+label,icon:graphIcon(id)},position:graphPositions[id]})),edges:graphEdges.map(([source,target])=>({data:{id:source+'-'+target,source,target}}))},style:graphStyle(),layout:{name:'preset',fit:true,padding:55},wheelSensitivity:.18});
    flow.on('tap','node',event=>selectState(event.target.id()));
    graphVisibility();
    if(!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)flowPulse=window.setInterval(()=>{if(!flow||compactFlow?.matches||!byId('measurement-inspection').open||document.documentElement.dataset.motion!=='on')return;flow.nodes('.active,.waiting').animate({style:{'underlay-opacity':.4}},{duration:450}).animate({style:{'underlay-opacity':.12}},{duration:450});},950);
    updateSelectionVisual();
  }
  function updateSelectionVisual(){
    for(const [state,{node}] of Object.entries(nodes)){node.dataset.selected=String(state===selectedState);node.setAttribute('aria-pressed',String(state===selectedState));}
    const paths=byId('measurement-fallback-lines').querySelectorAll?.('path[data-edge]')||[];
    for(const path of paths)path.classList.toggle('inspected',!!selectedState&&path.dataset.edge.split('-').includes(selectedState));
    if(flow){flow.elements().removeClass('inspected');if(selectedState){flow.$id(selectedState).addClass('inspected');for(const [from,to] of graphEdges)if(from===selectedState||to===selectedState)flow.$id(from+'-'+to).addClass('inspected');}}
  }
  function updateInspector(){
    const panel=byId('measurement-graph-inspector');panel.hidden=!selectedState;if(!selectedState)return;
    byId('measurement-graph-inspector-icon').dataset.sprite=selectedState.toLowerCase();
    text('measurement-graph-inspector-title',selectedState+' · '+labels[selectedState]);
    const active=current.running&&current.fsm===selectedState,done=(current.cycle?.actions||[]).includes(selectedState)&&!active;
    text('measurement-graph-inspector-status',(active?'En curso':done?'Completado en este ciclo':current.run?'Sin actividad en este ciclo':'Sin ejecución')+' · '+stateDescriptions[selectedState]);
    const incoming=graphEdges.filter(([,to])=>to===selectedState).map(([from])=>from),outgoing=graphEdges.filter(([from])=>from===selectedState).map(([,to])=>to);
    text('measurement-graph-inspector-routes','Desde '+incoming.join(', ')+' · Hacia '+outgoing.join(', '));
  }
  function selectState(state){
    if(state&&!labels[state])return;
    selectedState=state||null;byId('measurement-graph-picker').value=selectedState||'';
    updateSelectionVisual();updateInspector();
  }
  function updateFlow(data,lastTransition,actions){
    initFlow();
    const paths=byId('measurement-fallback-lines').querySelectorAll?.('path[data-edge]')||[];
    for(const path of paths){const [from,to]=path.dataset.edge.split('-');path.classList.toggle('done',(data.transitions||[]).some(item=>item.from===from&&item.to===to));path.classList.toggle('active',lastTransition?.from===from&&lastTransition?.to===to);}
    const transitionKey=lastTransition?(data.run?.run_id||'')+':'+(lastTransition.timestamp||lastTransition.elapsed_seconds||(data.transitions||[]).length)+':'+lastTransition.from+'-'+lastTransition.to:'';
    if(seenTransitionKey!==undefined&&transitionKey&&transitionKey!==seenTransitionKey&&data.running&&document.documentElement?.dataset.motion==='on'){
      const path=Array.from(paths).find(item=>item.dataset.edge===lastTransition.from+'-'+lastTransition.to);
      if(path){path.classList.remove('flow-burst');void path.getBoundingClientRect?.();path.classList.add('flow-burst');window.setTimeout?.(()=>path.classList.remove('flow-burst'),1500);}
      if(flow)flow.$id(lastTransition.from+'-'+lastTransition.to).animate({style:{'line-dash-offset':-90}},{duration:900});
    }
    seenTransitionKey=transitionKey;
    if(!flow)return;
    flow.elements().removeClass('active done waiting degraded');
    for(const state of actions)flow.$id(state).addClass('done');
    const active=data.running?data.fsm:null;
    if(active)flow.$id(active).removeClass('done').addClass(active==='WAIT'?'waiting':'active');
    if(active==='DEGRADED')flow.$id('DEGRADED').addClass('degraded');
    flow.edges().removeClass('active done');
    for(const transition of data.transitions||[])flow.$id(transition.from+'-'+transition.to).addClass('done');
    if(lastTransition)flow.$id(lastTransition.from+'-'+lastTransition.to).removeClass('done').addClass('active');
    updateSelectionVisual();
  }
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
    node.dataset.state=state;node.setAttribute('role','button');node.setAttribute('tabindex','0');node.setAttribute('aria-label','Inspeccionar '+state+' · '+label);node.onclick=()=>selectState(state);node.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectState(state);}};
    icon.setAttribute('aria-hidden','true');node.append(icon,title,detail); byId('measurement-pipeline').append(node); nodes[state]={node,icon,detail,label};
  }
  const observations = {presence:['Radar','presence'], count:['Personas visibles','visible_people'], temperature:['Temperatura','°C'], humidity:['Humedad','%RH'], aqi:['AQI ENS160','ENS160 AQI'], tvoc:['TVOC','ppb'], eco2:['eCO₂ estimado','ppm equivalent']};
  const cards = {};
  const answerNodes = {};
  const interpretationNodes = new Map();
  for (const [key,[label]] of Object.entries(observations)) {
    const card=make('article',undefined,'card'), title=make('p',label,'sub'), value=make('p','—','measurement-value'), age=make('p','Sin evidencia','evidence-age'), status=make('span','Desconocido','evidence-status'), source=make('p',{presence:'Fuente · radar',count:'Fuente · YOLO',temperature:'Fuente · SHT40',humidity:'Fuente · SHT40',aqi:'Fuente · ENS160',tvoc:'Fuente · ENS160',eco2:'Fuente · ENS160'}[key],'evidence-source'), captured=make('p','Hora sin registrar','evidence-time'), info=make('p','Región sin registrar','evidence-detail'), details=make('details',undefined,'reading-details');
    const sprite={presence:'radar',count:'yolo',temperature:'temperature',humidity:'humidity',aqi:'aqi',tvoc:'tvoc',eco2:'eco2'}[key];if(sprite)card.dataset.sprite=sprite;
    const summary=make('summary','Detalles');summary.setAttribute('aria-label','Detalles de '+label);details.append(summary,info,source,captured);
    const control=key==='presence'?make('div',undefined,'presence-control'):null;
    const distance=key==='presence'?make('p',undefined,'reading-distance'):null;
    if(control){
      const mode=make('button','Auto'), toggle=make('button','No detectada');
      mode.onclick=()=>setPresence(current.presence_control?.mode==='MANUAL'?{mode:'auto'}:current.run?.mode==='B'?{mode:'manual',detected:!!current.context?.observations?.presence?.value,near:current.reactive_trigger?.state==='NEAR'}:{mode:'manual',detected:!!current.context?.observations?.presence?.value});
      toggle.onclick=()=>setPresence({mode:'manual',detected:!(current.run?.mode==='B'?current.presence_control?.near:current.presence_control?.detected)});
      control.append(mode,toggle);
    }
    card.append(title,value,age,status); if(control)card.append(control);if(distance)card.append(distance);card.append(details); byId(['presence','count'].includes(key)?'measurement-presence-readings':'measurement-environment-readings').append(card); cards[key]={card,title,value,age,status,source,captured,info,details,control,distance};
  }
  const modeSelect = byId('measurement-mode');
  for(const [mode,label] of Object.entries(modes)){const option=make('option',label);option.value=mode;modeSelect.append(option);}
  const componentNames={sht40:'SHT40 · temperatura y humedad',ens160:'ENS160 · AQI, TVOC y eCO₂',radar:'Radar LD2410C',camera:'Cámara / YOLO',gemma:'Gemma'};
  const healthLabels={UNKNOWN:'Sin comprobar',HEALTHY:'Operativo',STALE:'Evidencia vencida',UNAVAILABLE:'Sin datos',FAILED:'Fallo detectado',RECOVERING:'Comprobando recuperación'};
  const healthNodes={},faultButtons={};
  for(const [component,label] of Object.entries(componentNames)){
    const card=make('article'),name=make('span',label),state=make('strong','Sin comprobar');card.append(name,state);byId('measurement-health').append(card);healthNodes[component]=state;
    if(component==='gemma')continue;
    const row=make('div',undefined,'fault-row'),button=make('button','Deshabilitar por software');button.type='button';
    button.onclick=()=>setFault({action:'availability',component,enabled:!!current.fault_control?.disabled.includes(component)});
    row.append(make('span',label),button);byId('measurement-fault-switches').append(row);faultButtons[component]=button;
  }
  for(const [id,lane] of [['measurement-timeout-vision','vision'],['measurement-timeout-gemma','gemma']])byId(id).onclick=()=>setFault({action:'timeout',lane});
  async function setFault(body){
    if(pending||!connected||current.run?.mode!=='F'||!current.running)return;
    pending=true;controls();text('measurement-error','');
    try{await post('/api/experiments/faults',body);}
    catch(error){text('measurement-error',error.message);}
    finally{pending=false;controls();}
  }
  function controls(){
    byId('measurement-toggle').disabled=!!(pending||stopRequested||!connected||(!current.running&&(current.reserved||!ready||sandboxBusy)));
    byId('measurement-toggle').dataset.running=String(!!current.running);
    modeSelect.disabled=!!(pending||current.running||current.reserved);
    byId('measurement-toggle').textContent=pending?'Procesando…':current.running?'Finalizar':'Comenzar';
    byId('measurement-query').disabled=pending||!connected||!current.running;
    const presenceEnabled=connected&&current.running&&['B','C','D','E','F'].includes(current.run?.mode)&&!pending;
    const [presenceMode,presenceToggle]=cards.presence.control.children;
    presenceMode.disabled=!presenceEnabled;presenceToggle.disabled=!presenceEnabled||current.presence_control?.mode!=='MANUAL';
    const faultEnabled=connected&&current.running&&current.run?.mode==='F'&&!pending;
    for(const button of Object.values(faultButtons))button.disabled=!faultEnabled;
    byId('measurement-timeout-vision').disabled=!faultEnabled||!!current.fault_control?.timeouts?.vision;
    byId('measurement-timeout-gemma').disabled=!faultEnabled||!!current.fault_control?.timeouts?.gemma;
  }
  async function post(url,body){
    const response=await window.senseAPI.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'No se pudo completar la operación.');return data;
  }
  async function setPresence(body){
    if(pending||!connected||!current.running)return;pending=true;controls();text('measurement-error','');
    try{await post('/api/experiments/presence',body);}
    catch(error){text('measurement-error',error.message);}
    finally{pending=false;controls();}
  }
  async function toggleRun(stopping=false){
    if(pending)return;pending=true;controls();text('measurement-error','');
    try{
      await post('/api/experiments/'+(stopping?'stop':'start'),{mode:modeSelect.value});
      stopRequested=stopping;
      current={...current,reserved:true};
      text('measurement-state','Solicitud aceptada; esperando confirmación de SENSE.');
    }catch(error){text('measurement-error',error.message);}
    finally{pending=false;controls();}
  }
  byId('measurement-toggle').onclick=()=>{
    if(current.running){byId('finish-dialog').showModal();return;}
    return toggleRun();
  };
  byId('finish-cancel').onclick=()=>byId('finish-dialog').close();
  byId('finish-accept').onclick=async()=>{byId('finish-dialog').close();await toggleRun(true);};
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
        const article=make('article',undefined,'question-result'),heading=make('h3'),value=make('p',undefined,'answer-value'),status=make('p',undefined,'answer-meta'),pending=make('p',undefined,'answer-limitations'),detail=make('details'),fullAnswer=make('p',undefined,'answer-full'),contract=make('pre');
        detail.append(make('summary','Respuesta completa y evidencia'),fullAnswer,contract);article.append(heading,value,status,pending,detail);byId('measurement-answers').append(article);
        nodes=answerNodes[answer.question_id]={article,heading,value,status,pending,fullAnswer,contract};
      }
      nodes.heading.textContent=answer.question_id+' · '+answer.question;
      nodes.value.textContent=answerText(answer);
      nodes.fullAnswer.textContent=answerText(answer);
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
      article.append(make('strong',result.question_id+' · '+(result.image_id?'Con imagen':'Solo texto')+' · '+(result.validation_status==='VALIDATED'?'Formato validado':'Respuesta rechazada')),make('p','Finalizó a las '+timeLabel(result.completed_at)+' · evidencia histórica · las hipótesis requieren verificación','sub'));
      if(result.validation_status==='VALIDATED'){
        if(result.summary)article.append(make('p',result.summary));
        else for(const [key,label] of [['inferences','Inferencias'],['unknowns','Desconocidos'],['recommendations','Recomendaciones no críticas']])if(result[key]?.length)article.append(make('p',label+': '+result[key].join(' ')));
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
      const response=await window.senseAPI.fetch('/api/experiments');if(!response.ok)throw new Error('No se pudo cargar el historial.');
      const {runs,completed_repetitions=[]}=await response.json();
      byId('measurement-history').replaceChildren(...runs.map(run=>{
        const official=completed_repetitions.find(r=>['scenario_id','mode','repetition'].every(key=>r[key]===run[key]));
        const result=official?.run_id===run.run_id?' · Vigente':official&&run.finish_reason==='MAX_RUN_DURATION'&&!run.quality?.pending_observations?' · Anterior':'';
        const label=run.guided?run.scenario_id+' · '+run.mode+' · Repetición '+run.repetition:run.mode;
        const row=make('tr');for(const value of [new Date(run.start_time).toLocaleString(),label,(runStatuses[run.status]||run.status)+result])row.append(make('td',value));
        const cell=make('td'),link=make('a','CSV · ZIP'),raw=make('a','NDJSON'),observe=make('button','Completar observaciones');
        window.senseAPI.setExportLink(link,run.run_id);window.senseAPI.setExportLink(raw,run.run_id,'ndjson');
        observe.hidden=!run.quality?.pending_observations;observe.onclick=()=>window.experimentation?.review(run.run_id);
        cell.append(link,make('span',' · '),raw,observe);row.append(cell);return row;
      }));
      text('measurement-history-note',runs.length?'Últimas '+runs.length+' ejecuciones.':'Todavía no hay ejecuciones.');
    }catch(error){text('measurement-history-note',error.message);}
  }
  byId('measurement-history-details').addEventListener('toggle',()=>{if(byId('measurement-history-details').open)history();});
  function renderGuidance(run,elapsed){
    const panel=byId('measurement-guidance'),steps=scenarioSteps[run?.scenario_id];panel.hidden=!run?.guided||!steps;
    if(panel.hidden)return;
    const starts=scenarioStarts[run.scenario_id];
    const active=Math.max(0,starts.findLastIndex(second=>elapsed>=second));
    const stage=steps[active],next=steps[active+1];
    text('measurement-scenario-label',run.scenario_id+' · '+(run.repetition?'Repetición '+run.repetition:'Guion'));
    text('measurement-step',run.status==='RUNNING'?stage[1]:'Sesión '+(run.status==='COMPLETED'?'finalizada':'interrumpida'));
    text('measurement-step-note',run.status==='RUNNING'?stage[0]+' · tiempos orientativos. '+stage[2]:'Consulta el registro y completa las observaciones pendientes.');
    text('measurement-next',run.status==='RUNNING'&&next?'Siguiente · '+next[0]+' · '+next[1]:'Registra la hora real de cada acción.');
    const key=run.scenario_id+'/'+active+'/'+run.status;
    if(key!==lastGuidance){lastGuidance=key;byId('measurement-scenario-timeline').replaceChildren(...steps.map((item,i)=>{const node=make('li');node.className=i===active&&run.status==='RUNNING'?'current':i<active?'past':'';node.append(make('strong',item[0]),make('span',item[1]));if(i===active&&run.status==='RUNNING')node.setAttribute('aria-current','step');return node;}));}
  }
  window.measurement = {
    formatAnswer:answerText,
    formatResource:(value,unit)=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(2)+(unit?' '+unit:''):'—',
    connection(value){connected=value;controls();window.experimentation?.connection(value);if(!value){text('measurement-state','Conexión interrumpida; estado sin actualizar.');text('measurement-answer-note','Conexión interrumpida. Se muestran las últimas respuestas recibidas.');}},
    render(data,phases,busy){
      current=data||{};connected=true;sandboxBusy=!!busy;ready=Object.values(phases||{}).length===3&&Object.values(phases).every(p=>!['waiting','loading'].includes(p.status));
      if(!current.running)stopRequested=false;
      controls();
      for(const option of modeSelect.options)option.disabled=current.enabled_modes&&!current.enabled_modes.includes(option.value);
      if(current.run&&current.running)modeSelect.value=current.run.mode;
      const visualQuestion=Array.from(byId('measurement-question').options).find(option=>option.value==='Q7');
      if(visualQuestion)visualQuestion.disabled=!['E','F'].includes(current.run?.mode);
      if(visualQuestion?.disabled&&byId('measurement-question').value==='Q7')byId('measurement-question').value='Q1';
      const run=current.run;
      renderGuidance(run,current.elapsed_s||0);
      text('measurement-current-fsm',current.running?current.fsm||'—':'—');
      text('measurement-heading',run?.guided?'Medición experimental':'Medición y pruebas');
      text('measurement-run',current.running?'En ejecución':run?(modes[run.mode]||run.mode)+' · '+(runStatuses[run.status]||run.status):'Sin ejecución');
      const stateLabel=stateDescriptions[current.fsm]||current.fsm;
      text('measurement-state',current.running?stateLabel:current.reserved?(run?'Medición finalizada; esperando a que terminen las tareas activas':'Esperando a que terminen las tareas activas'):run?'Ejecución finalizada':'Listo para comenzar');
      text('measurement-run-metadata',JSON.stringify({run,cycle:current.cycle,config_version:current.config_version},null,2));
      const download=byId('measurement-current-export');download.hidden=!run;if(run)window.senseAPI.setExportLink(download,run.run_id,'ndjson');
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
      updateFlow(current,lastTransition,actions);
      updateInspector();
      byId('measurement-transition-live').hidden=!lastTransition;
      if(lastTransition)text('measurement-transition-live','Última transición: '+lastTransition.from+' → '+lastTransition.to+' · '+lastTransition.reason);
      const background=byId('measurement-background-tasks'), activeTasks=(current.tasks?.active||[]), queued=Array.isArray(current.tasks?.queued)?current.tasks.queued.length:Number(current.tasks?.queued)||0;
      background.hidden=!activeTasks.length&&!queued;
      background.replaceChildren(...activeTasks.map(task=>make('span',task.question_id+' · '+(task.simulated?'simulación, modelo sin ejecutar':task.status==='RUNNING'?'en segundo plano':'esperando finalización')+' · '+task.elapsed_seconds+' s','background-task '+(task.status==='RUNNING'?'running':''))),...(queued?[make('span',queued+' tareas en cola','background-task')]:[]));
      byId('measurement-degraded').classList.toggle('active',current.fsm==='DEGRADED'||actions.includes('DEGRADED'));
      byId('measurement-degraded').hidden=!actions.includes('DEGRADED')&&current.fsm!=='DEGRADED';
      text('measurement-degraded','Este ciclo produjo información parcial o una abstención por falta de evidencia.');
      for(const [key,card] of Object.entries(cards)){
        const observation=current.context?.observations?.[key],status=observation?.status||'UNKNOWN';
        card.value.textContent=observation?.value==null?'—':key==='presence'?(observation.value?'Detectada':'No detectada'):String(observation.value)+(key==='temperature'?' °C':key==='humidity'?' %':key==='tvoc'?' ppb':key==='eco2'?' ppm eq.':'');
        card.age.textContent=observation?(observation.age_seconds==null?'Edad desconocida':Math.floor(observation.age_seconds)+' s'):'Sin evidencia';
        card.info.textContent='Región · '+(observation?.region||'Sin registrar');
        card.status.textContent=statusLabels[status]||status;card.status.dataset.status=status;
        card.captured.textContent=observation?.captured_at?'Lectura · '+timeLabel(observation.captured_at):'Hora sin registrar';
        if(key==='presence')card.source.textContent='Fuente · radar';
        if(key==='presence'){
          const metadata=observation?.metadata||{},trigger=current.reactive_trigger;
          const source={total_distance_cm:'distancia total',motion_distance_cm:'blanco en movimiento',static_distance_cm:'blanco estático'}[metadata.trigger_distance_source];
          card.title.textContent=run?.mode==='B'?'Radar · zona B':'Radar';
          const distanceParts=[];
          if(metadata.trigger_distance_cm!=null)distanceParts.push(metadata.trigger_distance_cm+' cm · '+(source||'blanco activo'));
          if(run?.mode==='B'){
            card.value.textContent={NEAR:'Dentro de zona',FAR:'Fuera de zona',CONFIRMING:'Confirmando…',UNKNOWN:'Zona desconocida'}[trigger?.state]||'Zona desconocida';
            if(observation?.value!=null)distanceParts.push((status==='VALID'?'Radar: ':'Última lectura: ')+(observation.value?'presencia detectada':'sin presencia detectada'));
          }
          card.distance.textContent=distanceParts.join(' · ');card.distance.hidden=!distanceParts.length;
          if(card.control){
            const manual=current.presence_control?.mode==='MANUAL';
            card.control.hidden=!['B','C','D','E','F'].includes(run?.mode);
            const [mode,toggle]=card.control.children;
            mode.textContent=manual?'Manual':'Auto';mode.className=manual?'manual':'';
            toggle.textContent=run?.mode==='B'?(current.presence_control?.near?'Dentro de zona':'Fuera de zona'):(current.presence_control?.detected?'Detectada':'No detectada');
          }
        }
      }
      const trigger=current.reactive_trigger,visionDecision=(current.decisions||[]).filter(item=>item.kind==='VISION').at(-1);
      let triggerText='';
      if(current.running&&run?.mode==='B'&&trigger){
        const rule=current.presence_control?.mode==='MANUAL'?'B manual: señal explícita de presencia/zona; sin distancia simulada.':'B: entrada < '+trigger.enter_below_cm+' cm · salida ≥ '+trigger.exit_at_or_above_cm+' cm · '+trigger.required_samples+' lecturas.';
        const reason={RADAR_DISTANCE_UNKNOWN:'Sin distancia válida y vigente; esperando al radar.',RADAR_ZONE_CONFIRMING:'Confirmando zona: '+trigger.confirmed_samples+'/'+trigger.required_samples+'.',
          COOLDOWN_ACTIVE:'Esperando el intervalo mínimo entre capturas.',CAMERA_UNAVAILABLE:'YOLO no está disponible.',DUPLICATE_REQUEST:'Captura visual en curso.',
          INSUFFICIENT_MEMORY:'Captura pospuesta por memoria disponible.',CPU_BUDGET:'Captura pospuesta por carga de CPU.',RATE_LIMIT:'Esperando el presupuesto de activaciones.',
          RADAR_NEAR_CONFIRMED:'Zona próxima inicial confirmada: captura autorizada.',RADAR_ZONE_ENTERED:'Entrada confirmada: captura autorizada.',RADAR_ZONE_EXITED:'Salida confirmada: captura autorizada.',MANUAL_ZONE_ENTERED:'Entrada confirmada: captura autorizada si hay recursos.',MANUAL_ZONE_EXITED:'Salida confirmada: captura autorizada si hay recursos.'}[visionDecision?.reason];
        triggerText=rule+' '+(reason||(trigger.state==='UNKNOWN'?'Sin distancia válida y vigente.':trigger.state==='CONFIRMING'?'Confirmando zona: '+trigger.confirmed_samples+'/'+trigger.required_samples+'.':'Esperando otro cambio confirmado de zona.'));
        if(current.context?.observations?.count?.status==='STALE')triggerText+=' El conteo está vencido; B no lo renueva únicamente por antigüedad.';
      }
      text('measurement-trigger',triggerText);
      const tasks=current.tasks||{},active=tasks.active||[];
      const gemmaTasks=active.filter(task=>task.agent==='InterpretationAgent');
      byId('measurement-worker').classList.toggle('loading',gemmaTasks.length>0);
      text('measurement-worker',gemmaTasks.length?gemmaTasks.map(task=>task.question_id+' · '+(task.simulated?'Simulando timeout; modelo sin ejecutar':task.status==='RUNNING'?'Interpretando':task.status==='DRAINING'?'Esperando finalización física':'Estado del runtime sin confirmar')+' · '+task.elapsed_seconds+' s').join('\n')+'\nEn cola: '+(tasks.queued||0):tasks.queued?'Interpretaciones en espera: '+tasks.queued:'');
      const interpretationCount=(current.interpretations||[]).length;
      byId('measurement-interpretations-empty').hidden=interpretationCount>0;
      text('measurement-interpretation-count',interpretationCount?Math.min(10,interpretationCount)+' resultados recientes':'');
      text('measurement-interpretations-empty',!run?'Gemma se utiliza en D, E y F cuando la política identifica una necesidad adicional.':!['D','E','F'].includes(run.mode)?'El modo '+run.mode+' responde mediante reglas; no utiliza Gemma.':gemmaTasks.length||tasks.queued?'Todavía no hay resultados: una interpretación está pendiente.':'Todavía no hay interpretaciones. Gemma solo se invoca cuando puede aportar información adicional.');
      for(const [component,node] of Object.entries(healthNodes)){
        const status=current.component_health?.[component]?.status||'UNKNOWN';node.textContent=healthLabels[status]||status;node.dataset.status=status;
      }
      byId('measurement-fault-panel').hidden=run?.mode!=='F';
      for(const [component,button] of Object.entries(faultButtons)){
        const disabled=current.fault_control?.disabled.includes(component);button.textContent=disabled?'Restaurar entrada':'Deshabilitar por software';button.setAttribute('aria-pressed',String(!!disabled));
      }
      const timeoutLabel=lane=>({ARMED:'Armado: esperando una solicitud de la política',QUEUED:'Asignado a una tarea en cola',RUNNING:'Timeout simulado en curso'}[current.fault_control?.timeouts[lane]]||'Sin timeout armado');
      text('measurement-timeout-vision-status',timeoutLabel('vision'));text('measurement-timeout-gemma-status',timeoutLabel('gemma'));
      const faults=current.fault_control?.faults||[];
      text('measurement-fault-summary',faults.length?faults.length+' fallas registradas · '+faults.filter(f=>f.detected_at).length+' detectadas · '+faults.filter(f=>f.recovered_at).length+' recuperadas · '+faults.filter(f=>f.not_executed_reason).length+' sin ejecutar.':'Sin fallas inyectadas. F utiliza la misma política de E.');
      text('measurement-resources',JSON.stringify({resources:current.resources,workers:tasks,dispatcher:current.dispatcher},null,2));
      if(current.error)text('measurement-error',current.error);
      renderDetails(current);
      const blind=!!current.run?.guided&&(current.observer_requests||[]).some(r=>r.fields.includes('visible_people'));
      cards.count.value.textContent=blind?'Conteo en verificación':cards.count.value.textContent;
      cards.count.status.textContent=blind?'Confirmación humana pendiente':cards.count.status.textContent;
      cards.count.status.dataset.status=blind?'PENDING':cards.count.status.dataset.status;
      cards.count.card.dataset.blinded=String(blind);
      if(answerNodes.Q2)answerNodes.Q2.article.hidden=blind||!current.answers?.Q2;
      window.experimentation?.render(current,ready,sandboxBusy);
      const nextHistory=(run?.run_id||'')+'/'+(run?.status||'');if(nextHistory!==historyKey){historyKey=nextHistory;if(byId('measurement-history-details').open)history();}
    },
    resizeGraph(){initFlow();graphVisibility();if(flow&&!compactFlow?.matches){updateFlow(current,(current.transitions||[]).at(-1),current.cycle?.actions||[]);flow.resize();flow.fit(flow.elements(),55);}else fitFallback();}
  };
  document.addEventListener?.('themechange',()=>{if(flow){for(const state of Object.keys(labels))flow.$id(state).data('icon',graphIcon(state));flow.style(graphStyle()).update();}});
  byId('measurement-inspection').addEventListener('toggle',()=>{if(byId('measurement-inspection').open){window.measurement.resizeGraph();if(!selectedState&&current.fsm)selectState(current.fsm);}});
  byId('measurement-graph-picker').onchange=event=>selectState(event.target.value);
  compactFlow?.addEventListener('change',()=>window.measurement.resizeGraph());
  byId('measurement-flow-zoom-in').onclick=()=>{if(flow)flow.zoom({level:flow.zoom()+.2,renderedPosition:{x:byId('measurement-graph').clientWidth/2,y:byId('measurement-graph').clientHeight/2}});else zoomFallback(.15);};
  byId('measurement-flow-zoom-out').onclick=()=>{if(flow)flow.zoom({level:Math.max(flow.minZoom(),flow.zoom()-.2),renderedPosition:{x:byId('measurement-graph').clientWidth/2,y:byId('measurement-graph').clientHeight/2}});else zoomFallback(-.15);};
  byId('measurement-flow-reset').onclick=()=>{if(flow)flow.fit(flow.elements(),55);else fitFallback();};
})();
