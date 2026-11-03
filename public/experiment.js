/* El backend mantiene reloj, muestreo y pendientes aunque este documento se cierre. */
(() => {
  'use strict';
  const byId=id=>document.getElementById(id), dialog=byId('observer-dialog'), form=byId('observer-form');
  let current={}, connected=false, ready=false, busy=false, saving=false, starting=false, setupMode=null, selectedRequest=null, reviewRun=null, requests=[], lastRun='', pendingKey='';
  const resolved=new Set();
  let viewingReplay=false;
  const connectedEquipment='Raspberry Pi, todos los sensores y cámara';
  let observationRegion='rasp_shared_view', previous={}, repeated=new Set();
  const drafts=new Map();
  let completed=[], replacing=null;
  const exportAttempts=new Set();
  const completedFor=(mode=byId('experiment-mode').value,repetition=Number(byId('experiment-repetition').value))=>completed.find(r=>r.scenario_id===byId('experiment-scenario').value&&r.mode===mode&&r.repetition===repetition);
  async function autoDownload(runId){
    if(!runId||!completed.some(r=>r.run_id===runId)||exportAttempts.has(runId))return;
    if(current.run?.run_id===runId&&(current.running||current.reserved||current.tasks?.active?.length||current.tasks?.queued))return;
    exportAttempts.add(runId);
    try{if(window.localStorage?.getItem('sense-export-'+runId))return;}catch{}
    text('experiment-download-note','Preparando descarga automática del ZIP…');
    try{
      await window.senseAPI.downloadRun(runId);
      try{window.localStorage?.setItem('sense-export-'+runId,'requested');}catch{}
      text('experiment-download-note','Descarga del ZIP solicitada. Si el navegador la bloqueó, usa Descargar ZIP.');
    }catch(error){text('experiment-download-note',error.message);}
  }
  const draftIds=['name','instrument','power','people','action','power-time','people-time','notes','missing'];
  const draftKey=()=>setupMode?['setup',setupMode,byId('experiment-scenario').value,byId('experiment-repetition').value].join(':'):selectedRequest?.request_id;
  const fieldIds={power_w:'power',visible_people:'people',action:'action'};
  const reasons={RUN_INITIAL:'Condiciones iniciales',RUN_FINAL:'Cierre de la ejecución',VISION_TASK_STARTED:'YOLO inició',VISION_TASK_COMPLETED:'YOLO finalizó',TEXT_TASK_STARTED:'Gemma textual inició',TEXT_TASK_COMPLETED:'Gemma textual finalizó',MULTIMODAL_TASK_STARTED:'Gemma con imagen inició',MULTIMODAL_TASK_COMPLETED:'Gemma con imagen finalizó',OBSERVER_EVENT:'Evento real',TEMP_RISE:'Cambio de temperatura',HUMIDITY_RISE:'Cambio de humedad',AQI_WORSENED:'Cambio de AQI',ECO2_THRESHOLD_CROSSED:'Cambio de eCO₂',PRESENCE_CHANGED:'Cambio detectado de presencia',RADAR_NEAR_CONFIRMED:'Entrada en zona del radar',RADAR_ZONE_EXITED:'Salida de zona del radar'};
  Object.assign(reasons,{FAULT_INJECTED:'Falla por software activada',FAULT_RESTORED:'Entrada restaurada; recuperación por comprobar',FAULT_RECOVERED:'Recuperación comprobada',SENSOR_PRESENCE_CHANGED:'Cambio del sensor de presencia',MANUAL_PRESENCE_CHANGED:'Cambio del sensor de presencia'});
  const text=(id,value)=>{byId(id).textContent=value;};
  const localTime=()=>{const date=new Date();return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,19);};
  const clock=seconds=>{const value=Math.max(0,Math.floor(seconds||0));return String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0');};
  async function post(url,body){const response=await window.senseAPI.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'No se pudo guardar.');return data;}
  function showTab(){
    if(window.senseUI){window.senseUI.selectPanel('experimentation');return;}
    document.querySelectorAll('.tab').forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.panel==='experimentation')));
    document.querySelectorAll('.panel').forEach(panel=>panel.hidden=panel.id!=='experimentation');
    window.measurement.resizeGraph();
  }
  function controls(){
    const locked=!!(current.running||current.reserved||starting||saving);
    const done=completedFor();
    byId('experiment-start').disabled=locked||!connected||!ready||busy||!!requests.length||!!done;
    for(const id of ['experiment-scenario','experiment-mode','experiment-repetition'])byId(id).disabled=locked;
    text('experiment-start-note',!connected?'Sin conexión. SENSE sigue registrando en el backend.':current.running?'Medición activa. Cierre automático al completar 30 minutos.':current.reserved?'Esperando a los workers.':requests.length?'Completa las observaciones pendientes.':!ready?'Esperando a que termine la preparación.':busy?'Espera a que termine el sandbox.':'Registra las condiciones iniciales para comenzar.');
    for(const option of byId('experiment-repetition').options)option.textContent='Repetición '+option.value+(completedFor(undefined,Number(option.value))?' · Completada 🔒':'');
    byId('experiment-completed').hidden=!done;
    byId('experiment-remeasure').disabled=locked||!connected||!ready||busy||!!requests.length;
    if(done){
      if(!locked&&!requests.length)text('experiment-start-note','Completada y bloqueada. Usa Volver a medir para reemplazar el resultado vigente.');
      window.senseAPI.setExportLink(byId('experiment-completed-export'),done.run_id);
    }
    byId('measurement-observe').disabled=!connected||!requests.length||saving;
    byId('measurement-add-observation').disabled=!connected||!current.run||saving||completed.some(r=>r.run_id===current.run.run_id);
    text('observer-pending-count',setupMode?'':requests.length+' pendientes');
    text('observer-pending-toggle','Pendientes · '+requests.length);
    byId('observer-pending-toggle').hidden=!requests.length;
    byId('observer-pending-toggle').disabled=!connected||saving;
    text('measurement-observer-status',requests.length?requests.length+' observaciones obligatorias pendientes':'Sin observaciones pendientes');
    for(const [field,id] of Object.entries(fieldIds))if(id!=='action'){
      const button=byId('observer-'+id+'-repeat'), value=previous[field];
      button.disabled=!!setupMode||saving||value==null||byId('observer-'+id).disabled;
      text('observer-'+id+'-repeat',value==null?'Sin anterior':'Repetir '+value+(id==='power'?' W':' personas'));
    }
  }
  function renderPending(){
    const key=requests.map(item=>item.request_id+':'+item.reason).join('|');if(key===pendingKey)return;pendingKey=key;
    const list=byId('measurement-pending-list');
    list.replaceChildren(...requests.slice(0,5).map(item=>{
      const button=document.createElement('button'),date=new Date(item.requested_at),time=document.createElement('time'),body=document.createElement('span'),name=document.createElement('strong'),fields=document.createElement('small');
      button.type='button';button.className='pending-item';time.textContent=Number.isNaN(date.getTime())?'—':date.toLocaleTimeString();
      const label=reasons[item.reason]||(item.reason.startsWith('PERIODIC_W:')?'Lectura periódica de potencia':item.reason.startsWith('SCENARIO_CHECKPOINT:')?'Cambio del guion':'Observación solicitada');
      name.textContent=label;fields.textContent=item.fields.map(field=>({power_w:'W',visible_people:'personas',action:'acción real'})[field]||field).join(' · ');
      body.append(name,fields);button.append(time,body);button.onclick=()=>{selectedRequest=item;setupMode=null;openForm();};return button;
    }));
    if(requests.length>5){const more=document.createElement('p');more.className='sub';more.textContent='+'+(requests.length-5)+' solicitudes en espera';list.append(more);}
  }
  function missingFields(){
    let missing=false;
    for(const [field,id] of Object.entries(fieldIds)){
      const enabled=setupMode?field!=='action':!!selectedRequest?.fields.includes(field);
      const unavailable=byId('observer-'+id+'-unavailable').checked;
      byId('observer-'+id+'-group').hidden=!enabled;
      byId('observer-'+id).disabled=!enabled||unavailable;
      byId('observer-'+id).required=enabled&&!unavailable;
      byId('observer-'+id+'-unavailable').disabled=!enabled;
      if(id!=='action'){
        byId('observer-'+id+'-time').disabled=!enabled||unavailable;
        byId('observer-'+id+'-time-label').hidden=!enabled||unavailable;
      }
      missing ||= enabled&&unavailable;
    }
    byId('observer-missing-label').hidden=!missing;byId('observer-missing').required=missing;
    controls();
  }
  function saveDraft(){
    const key=draftKey();if(!key)return;
    drafts.set(key,{
      values:Object.fromEntries(draftIds.map(id=>[id,byId('observer-'+id).value])),
      unavailable:Object.values(fieldIds).filter(id=>byId('observer-'+id+'-unavailable').checked),
      repeated:[...repeated],details:byId('observer-details').open
    });
  }
  function openForm(){
    const setup=!!setupMode;
    form.reset();
    repeated=new Set();byId('observer-details').open=false;
    text('observer-error','');
    byId('observer-setup').hidden=!setup;
    for(const id of ['observer-name','observer-instrument']){byId(id).disabled=!setup;byId(id).required=setup;}
    const observedRun=setup?null:reviewRun||current.run;
    if(setup)for(const [field,id] of [['observer','name'],['instrument','instrument']])byId('observer-'+id).value=current.run?.[field]||'';
    observationRegion=observedRun?.observation_region||current.observation_region||'rasp_shared_view';
    text('observer-mount','Observas la misma vista que la Raspberry. El vatímetro mide: '+(observedRun?.equipment||connectedEquipment)+'.');
    const draft=drafts.get(draftKey());
    if(draft){
      for(const [id,value] of Object.entries(draft.values))byId('observer-'+id).value=value;
      for(const id of draft.unavailable)byId('observer-'+id+'-unavailable').checked=true;
      repeated=new Set(draft.repeated);byId('observer-details').open=draft.details;
    }
    const reason=selectedRequest?.reason||'';
    const label=reasons[reason]||(reason.endsWith('_TASK_FAILED')?'Falló '+(reason.startsWith('VISION')?'YOLO':'Gemma'):reason.endsWith('_TASK_TIMEOUT')?'Tiempo de espera agotado · '+(reason.startsWith('VISION')?'YOLO':'Gemma'):reason.startsWith('PERIODIC_W:')?'Lectura periódica común A–F · '+clock(Number(reason.split(':')[1])):reason.startsWith('SCENARIO_CHECKPOINT:')?'Cambio del guion · '+clock(Number(reason.split(':')[1])):'Evento del sistema: '+reason);
    text('observer-title',setup?'Comenzar · '+byId('experiment-scenario').value+' · '+setupMode:label);
    text('observer-event-time',setup?'El cronómetro comienza al guardar.':'Evento · '+new Date(selectedRequest.requested_at).toLocaleString());
    text('observer-description',setup?(replacing?'Volverás a medir esta repetición. El resultado anterior seguirá vigente hasta completar los 30 minutos y resolver las observaciones de este intento.':'Registra W y personas iniciales.'):'Completa solo lo que observaste. Si no lo viste, marca No observado.');
    text('observer-save',setup?'Guardar y comenzar 30 min':'Guardar observación');
    text('observer-later',setup?'Cancelar':'Dejar pendiente');
    missingFields();
    if(!dialog.open)dialog.showModal();
  }
  function openPending(){
    if(!requests.length)return;
    setupMode=null;selectedRequest=requests[0];openForm();
  }
  function begin(mode,replaces=null){
    if(!connected||!ready||busy||current.running||current.reserved||starting)return;
    if(requests.length){openPending();return;}
    byId('experiment-mode').value=mode;
    const done=completedFor();
    if(done&&done.run_id!==replaces){controls();return;}
    replacing=replaces;showTab();setupMode=mode;selectedRequest=null;reviewRun=null;openForm();
  }
  for(const id of Object.values(fieldIds))byId('observer-'+id+'-unavailable').onchange=missingFields;
  for(const [field,id] of Object.entries(fieldIds))if(id!=='action'){
    byId('observer-'+id).oninput=()=>{byId('observer-'+id+'-time').value=localTime();repeated.delete(field);};
    byId('observer-'+id+'-repeat').onclick=()=>{
      if(byId('observer-'+id+'-repeat').disabled)return;
      byId('observer-'+id).value=String(previous[field]);
      byId('observer-'+id+'-time').value=localTime();repeated.add(field);
    };
  }
  function closeForm(){
    if(saving)return;
    saveDraft();
    setupMode=null;selectedRequest=null;replacing=null;dialog.close();controls();
  }
  dialog.addEventListener('cancel',event=>{event.preventDefault();closeForm();});
  byId('observer-later').onclick=closeForm;
  form.onsubmit=async event=>{
    event.preventDefault();if(saving||!form.reportValidity())return;
    saving=true;byId('observer-save').disabled=true;byId('observer-later').disabled=true;controls();text('observer-error','');
    try{
      const fields=setupMode?['power_w','visible_people']:selectedRequest.fields;
      const payload={observed_at:new Date().toISOString(),region:observationRegion,notes:byId('observer-notes').value.trim(),unavailable_fields:[],missing_reason:byId('observer-missing').value.trim(),repeated_fields:[]};
      for(const field of fields){
        const id=fieldIds[field];
        if(byId('observer-'+id+'-unavailable').checked){payload[field]=null;payload.unavailable_fields.push(field);}
        else {
          payload[field]=id==='action'?byId('observer-action').value.trim():Number(byId('observer-'+id).value);
          if(id!=='action')payload[id+'_observed_at']=byId('observer-'+id+'-time').value?new Date(byId('observer-'+id+'-time').value).toISOString():payload.observed_at;
          if(repeated.has(field))payload.repeated_fields.push(field);
        }
      }
      if(setupMode){
        for(const [key,id] of [['observer','observer-name'],['instrument','observer-instrument']])payload[key]=byId(id).value.trim();
        payload.equipment=connectedEquipment;
        const started=await post('/api/experiments/start',{mode:setupMode,guided:true,scenario_id:byId('experiment-scenario').value,repetition:Number(byId('experiment-repetition').value),initial_observation:payload,...(replacing?{replaces_run_id:replacing}:{})});
        drafts.delete(draftKey());starting=current.run?.run_id!==started.run_id;setupMode=null;replacing=null;showTab();
      }else{
        const runId=reviewRun?.run_id||current.run.run_id;
        const data=await post('/api/experiments/'+encodeURIComponent(runId)+'/observer-requests/'+encodeURIComponent(selectedRequest.request_id),payload);
        completed=data.completed_repetitions||completed;
        current.completed_repetitions=completed;
        autoDownload(runId);
        drafts.delete(selectedRequest.request_id);previous=data.observer_previous||previous;
        resolved.add(selectedRequest.request_id);requests=data.observer_requests.filter(r=>!resolved.has(r.request_id));
        if(!reviewRun){current.observer_requests=requests;current.observer_previous=previous;current.quality=data.quality;}
        if(!requests.length)reviewRun=null;
        pendingKey='';
        renderPending();
      }
      dialog.close();selectedRequest=null;
      if(requests.length&&!starting)openPending();
    }catch(error){text('observer-error',error.message);}
    finally{saving=false;byId('observer-save').disabled=false;byId('observer-later').disabled=false;controls();}
  };
  byId('experiment-start').onclick=()=>begin(byId('experiment-mode').value);
  byId('experiment-remeasure').onclick=()=>{
    if(byId('experiment-remeasure').disabled)return;
    const done=completedFor();if(done)begin(done.mode,done.run_id);
  };
  for(const id of ['experiment-scenario','experiment-mode','experiment-repetition'])byId(id).addEventListener('change',controls);
  byId('measurement-observe').onclick=openPending;
  byId('observer-pending-toggle').onclick=openPending;
  byId('measurement-go-experiment').onclick=showTab;
  byId('measurement-add-observation').onclick=async()=>{
    try{
      const data=await post('/api/experiments/'+encodeURIComponent(current.run.run_id)+'/observer-requests',{});
      reviewRun=null;requests=data.observer_requests.filter(r=>!resolved.has(r.request_id));openPending();
    }catch(error){text('measurement-error',error.message);}
  };
  window.experimentation={
    begin,
    selectPanel(panel){
      viewingReplay=panel==='replay';
      if(panel==='measurement'&&!current.running&&!current.reserved){byId('measurement').append(byId('measurement-workspace'));byId('measurement-relocated').hidden=true;}
      if(panel==='experimentation'&&current.run?.guided){byId('experiment-live').append(byId('measurement-workspace'));byId('measurement-relocated').hidden=false;}
    },
    connection(value){connected=value;controls();if(!value)text('measurement-clock-note','Sin conexión: última duración recibida. El backend controla el cierre.');},
    async review(runId){
      try{const response=await window.senseAPI.fetch('/api/experiments/'+encodeURIComponent(runId));const data=await response.json();if(!response.ok)throw new Error(data.error);completed=data.completed_repetitions||completed;reviewRun=data.run;previous=data.observer_previous||{};requests=data.observer_requests.filter(r=>!resolved.has(r.request_id));renderPending();if(requests.length)openPending();else text('measurement-error','Esta ejecución no tiene observaciones pendientes.');controls();}
      catch(error){text('measurement-error',error.message);}
    },
    render(data,isReady,sandboxBusy){
      current=data||{};connected=true;ready=isReady;busy=sandboxBusy;
      completed=current.completed_repetitions||[];
      for(const option of byId('experiment-mode').options)option.disabled=!!current.enabled_modes&&!current.enabled_modes.includes(option.value);
      if(current.run?.run_id!==lastRun){
        lastRun=current.run?.run_id||'';starting=false;
        if(current.run?.guided){
          if(current.running)byId('experiment-guide-details').open=false;
          byId('experiment-scenario').value=current.run.scenario_id;byId('experiment-mode').value=current.run.mode;byId('experiment-repetition').value=String(current.run.repetition);
          document.querySelectorAll('.experiment-guide').forEach(guide=>guide.hidden=guide.dataset.scenario!==current.run.scenario_id);
          byId('experiment-live').append(byId('measurement-workspace'));byId('measurement-relocated').hidden=false;
          if(current.running&&!viewingReplay){showTab();byId('experiment-live').scrollIntoView?.({block:'start'});}
        }
      }
      if(!reviewRun){requests=(current.observer_requests||[]).filter(r=>!resolved.has(r.request_id));previous=current.observer_previous||{};}
      renderPending();
      if(selectedRequest&&!saving&&!requests.some(r=>r.request_id===selectedRequest.request_id)){
        selectedRequest=null;if(dialog.open&&!setupMode)dialog.close();
      }
      const duration=current.run?.duration_seconds||1800, elapsed=Math.min(duration,current.elapsed_s||0);
      text('measurement-clock',clock(elapsed));text('measurement-duration',clock(duration));
      byId('measurement-progress').max=duration;byId('measurement-progress').value=elapsed;
      text('measurement-clock-note',current.running?'Cierre automático al completar la sesión.':current.run?'Registro detenido · '+(current.run.finish_reason==='MAX_RUN_DURATION'?'duración completada':current.run.finish_reason==='USER_STOP'?'finalización anticipada':current.run.status)+'.':'Comienza al iniciar. Experimentación solicita primero las condiciones iniciales.');
      const resources=current.resources||{}, number=(value,unit)=>value==null?'—':value+' '+unit;
      text('measurement-cpu',window.measurement.formatResource(resources.cpu_total_percent,'%'));text('measurement-ram',window.measurement.formatResource(resources.ram_used_mb,'MB'));text('measurement-rss',window.measurement.formatResource(resources.main?.rss_mb,'MB'));text('measurement-temp',number(resources.temperature_c,'°C'));
      for(const [id,format] of [['measurement-csv-export','csv'],['measurement-raw-export','ndjson']]){const link=byId(id);link.hidden=!current.run;if(current.run)window.senseAPI.setExportLink(link,current.run.run_id,format);}
      const q=current.quality;
      text('measurement-quality',q?`${q.samples} muestras · ${q.missing_samples} segundos sin muestra · ${q.unavailable_observations} registros con datos no observados · ${q.task_failures||0} fallos · ${q.task_timeouts||0} timeouts · ${q.sensor_incomplete_samples||0} muestras con sensores incompletos. ${!current.running?(q.record_complete?'Traza completa.':'Registro con pendientes o datos faltantes.'):'Cobertura provisional.'}`:'El registro mostrará su cobertura y datos faltantes.');
      byId('experimentation').classList.toggle('is-running',!!current.run?.guided&&!!current.running);
      controls();
      autoDownload(current.run?.run_id);
    }
  };
})();
