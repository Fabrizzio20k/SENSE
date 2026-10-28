/* El backend mantiene reloj, muestreo y pendientes aunque este documento se cierre. */
(() => {
  'use strict';
  const byId=id=>document.getElementById(id), dialog=byId('observer-dialog'), form=byId('observer-form');
  let current={}, connected=false, ready=false, busy=false, saving=false, starting=false, setupMode=null, selectedRequest=null, reviewRun=null, requests=[], lastRun='', autoKey='';
  const resolved=new Set(), deferred=new Set();
  const fieldIds={power_w:'power',visible_people:'people',action:'action'};
  const reasons={RUN_INITIAL:'Condiciones iniciales',RUN_FINAL:'Cierre de la ejecución',VISION_TASK_STARTED:'YOLO inició: observa personas en la región de cámara y lee W',VISION_TASK_COMPLETED:'YOLO finalizó',TEXT_TASK_STARTED:'Gemma textual inició',TEXT_TASK_COMPLETED:'Gemma textual finalizó',MULTIMODAL_TASK_STARTED:'Gemma con imagen inició',MULTIMODAL_TASK_COMPLETED:'Gemma con imagen finalizó',OBSERVER_EVENT:'Evento real registrado por el observador',TEMP_RISE:'Cambio de temperatura',HUMIDITY_RISE:'Cambio de humedad',AQI_WORSENED:'Cambio de AQI',ECO2_THRESHOLD_CROSSED:'Cambio de eCO₂',PRESENCE_CHANGED:'Cambio detectado de presencia',RADAR_NEAR_CONFIRMED:'Entrada en zona del radar',RADAR_ZONE_EXITED:'Salida de zona del radar'};
  Object.assign(reasons,{FAULT_INJECTED:'Falla por software activada',FAULT_RESTORED:'Entrada restaurada; recuperación por comprobar',FAULT_RECOVERED:'Recuperación comprobada',MANUAL_PRESENCE_CHANGED:'Intervención manual de presencia'});
  const text=(id,value)=>{byId(id).textContent=value;};
  const localTime=()=>{const date=new Date();return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,19);};
  const clock=seconds=>{const value=Math.max(0,Math.floor(seconds||0));return String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0');};
  async function post(url,body){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'No se pudo guardar.');return data;}
  function showTab(){
    document.querySelectorAll('.tab').forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.panel==='experimentation')));
    document.querySelectorAll('.panel').forEach(panel=>panel.hidden=panel.id!=='experimentation');
    window.measurement.resizeGraph();
  }
  function controls(){
    const locked=!!(current.running||current.reserved||starting||saving);
    byId('experiment-start').disabled=locked||!connected||!ready||busy||!!requests.length;
    for(const id of ['experiment-scenario','experiment-mode','experiment-repetition'])byId(id).disabled=locked;
    text('experiment-start-note',!connected?'Sin conexión. SENSE sigue registrando en el backend.':current.running?'Medición activa. Cierre automático al completar 30 minutos.':current.reserved?'Esperando a los workers.':requests.length?'Completa las observaciones pendientes.':!ready?'Esperando a que termine la preparación.':busy?'Espera a que termine el sandbox.':'Registra las condiciones iniciales para comenzar.');
    byId('measurement-observe').disabled=!connected||!requests.length||saving;
    byId('measurement-add-observation').disabled=!connected||!current.run||saving;
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
        byId('observer-'+id+'-time').required=enabled&&!unavailable;
      }
      missing ||= enabled&&unavailable;
    }
    byId('observer-missing-label').hidden=!missing;byId('observer-missing').required=missing;
  }
  function openForm(){
    const setup=!!setupMode, now=localTime();
    form.reset();
    text('observer-error','');
    byId('observer-setup').hidden=!setup;
    for(const id of ['observer-name','observer-instrument','observer-equipment']){byId(id).disabled=!setup;byId(id).required=setup;}
    byId('observer-region').value=current.run?.observation_region||current.observation_region||'rasp_shared_view';
    for(const id of ['observer-time','observer-power-time','observer-people-time'])byId(id).value=now;
    const reason=selectedRequest?.reason||'';
    const label=reasons[reason]||(reason.endsWith('_TASK_FAILED')?'Falló '+(reason.startsWith('VISION')?'YOLO':'Gemma'):reason.endsWith('_TASK_TIMEOUT')?'Tiempo de espera agotado · '+(reason.startsWith('VISION')?'YOLO':'Gemma'):reason.startsWith('PERIODIC_W:')?'Lectura periódica común A–F · '+clock(Number(reason.split(':')[1])):reason.startsWith('SCENARIO_CHECKPOINT:')?'Cambio del guion · '+clock(Number(reason.split(':')[1])):'Evento del sistema: '+reason);
    text('observer-title',setup?'Preparar · '+byId('experiment-scenario').value+' · Modo '+setupMode+' · Repetición '+byId('experiment-repetition').value:label);
    text('observer-description',setup?'El cronómetro comienza al guardar. Registra lo observado, aunque difiera del guion.':`Solicitud de ${new Date(selectedRequest.requested_at).toLocaleString()}. ${selectedRequest.task_id?'Tarea '+selectedRequest.task_id.slice(0,8)+'. ':''}No copies la estimación del sistema. Si ese instante ya pasó y no lo observaste, declara el dato no observado.`);
    text('observer-save',setup?'Guardar y comenzar 30 min':'Guardar observación');
    text('observer-later',setup?'Cancelar':'Dejar pendiente');
    missingFields();
    if(!dialog.open)dialog.showModal();
  }
  function openPending(){
    if(!requests.length)return;
    setupMode=null;selectedRequest=requests[0];openForm();
  }
  function begin(mode){
    if(!connected||!ready||busy||current.running||current.reserved||starting)return;
    if(requests.length){openPending();return;}
    byId('experiment-mode').value=mode;showTab();setupMode=mode;selectedRequest=null;reviewRun=null;openForm();
  }
  for(const id of Object.values(fieldIds))byId('observer-'+id+'-unavailable').onchange=missingFields;
  dialog.addEventListener('cancel',event=>event.preventDefault());
  byId('observer-later').onclick=()=>{if(saving)return;if(selectedRequest)deferred.add(selectedRequest.request_id);setupMode=null;reviewRun=null;dialog.close();controls();};
  form.onsubmit=async event=>{
    event.preventDefault();if(saving||!form.reportValidity())return;
    saving=true;byId('observer-save').disabled=true;byId('observer-later').disabled=true;controls();text('observer-error','');
    try{
      const fields=setupMode?['power_w','visible_people']:selectedRequest.fields;
      const payload={observed_at:new Date(byId('observer-time').value).toISOString(),region:byId('observer-region').value.trim(),notes:byId('observer-notes').value.trim(),unavailable_fields:[],missing_reason:byId('observer-missing').value.trim()};
      for(const field of fields){
        const id=fieldIds[field];
        if(byId('observer-'+id+'-unavailable').checked){payload[field]=null;payload.unavailable_fields.push(field);}
        else {payload[field]=id==='action'?byId('observer-action').value.trim():Number(byId('observer-'+id).value);if(id!=='action')payload[id+'_observed_at']=new Date(byId('observer-'+id+'-time').value).toISOString();}
      }
      if(setupMode){
        for(const [key,id] of [['observer','observer-name'],['instrument','observer-instrument'],['equipment','observer-equipment']])payload[key]=byId(id).value.trim();
        const started=await post('/api/experiments/start',{mode:setupMode,guided:true,scenario_id:byId('experiment-scenario').value,repetition:Number(byId('experiment-repetition').value),initial_observation:payload});
        starting=current.run?.run_id!==started.run_id;setupMode=null;showTab();
      }else{
        const runId=reviewRun||current.run.run_id;
        const data=await post('/api/experiments/'+encodeURIComponent(runId)+'/observer-requests/'+encodeURIComponent(selectedRequest.request_id),payload);
        resolved.add(selectedRequest.request_id);requests=data.observer_requests.filter(r=>!resolved.has(r.request_id));
        if(!reviewRun){current.observer_requests=requests;current.quality=data.quality;}
        if(!requests.length)reviewRun=null;
        autoKey='';
      }
      dialog.close();selectedRequest=null;
      if(requests.length&&!starting)openPending();
    }catch(error){text('observer-error',error.message);}
    finally{saving=false;byId('observer-save').disabled=false;byId('observer-later').disabled=false;controls();}
  };
  byId('experiment-start').onclick=()=>begin(byId('experiment-mode').value);
  byId('measurement-observe').onclick=openPending;
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
      if(panel==='measurement'&&!current.running&&!current.reserved){byId('measurement').append(byId('measurement-workspace'));byId('measurement-relocated').hidden=true;}
      if(panel==='experimentation'&&current.run?.guided){byId('experiment-live').append(byId('measurement-workspace'));byId('measurement-relocated').hidden=false;}
    },
    connection(value){connected=value;controls();if(!value)text('measurement-clock-note','Sin conexión: última duración recibida. El backend controla el cierre.');},
    async review(runId){
      try{const response=await fetch('/api/experiments/'+encodeURIComponent(runId));const data=await response.json();if(!response.ok)throw new Error(data.error);reviewRun=runId;requests=data.observer_requests.filter(r=>!resolved.has(r.request_id));if(requests.length)openPending();else text('measurement-error','Esta ejecución no tiene observaciones pendientes.');controls();}
      catch(error){text('measurement-error',error.message);}
    },
    render(data,isReady,sandboxBusy){
      current=data||{};connected=true;ready=isReady;busy=sandboxBusy;
      for(const option of byId('experiment-mode').options)option.disabled=!!current.enabled_modes&&!current.enabled_modes.includes(option.value);
      if(current.run?.run_id!==lastRun){
        lastRun=current.run?.run_id||'';reviewRun=null;starting=false;
        if(current.run?.guided){
          byId('experiment-scenario').value=current.run.scenario_id;byId('experiment-mode').value=current.run.mode;byId('experiment-repetition').value=String(current.run.repetition);
          document.querySelectorAll('.experiment-guide').forEach(guide=>guide.hidden=guide.dataset.scenario!==current.run.scenario_id);
          byId('experiment-live').append(byId('measurement-workspace'));byId('measurement-relocated').hidden=false;
          if(current.running){showTab();byId('experiment-live').scrollIntoView?.({block:'start'});}
        }
      }
      if(!reviewRun)requests=(current.observer_requests||[]).filter(r=>!resolved.has(r.request_id));
      if(selectedRequest&&!saving&&!requests.some(r=>r.request_id===selectedRequest.request_id)){
        selectedRequest=null;if(dialog.open&&!setupMode)dialog.close();
      }
      const duration=current.run?.duration_seconds||1800, elapsed=Math.min(duration,current.elapsed_s||0);
      text('measurement-clock',clock(elapsed));text('measurement-duration',clock(duration));
      byId('measurement-progress').max=duration;byId('measurement-progress').value=elapsed;
      text('measurement-clock-note',current.running?'Restan '+clock(duration-elapsed)+'. Cierre automático en el backend.':current.run?'Registro detenido · '+(current.run.finish_reason==='MAX_RUN_DURATION'?'duración completada':current.run.finish_reason==='USER_STOP'?'finalización anticipada':current.run.status)+'.':'Comienza al iniciar. Experimentación solicita primero las condiciones iniciales.');
      const resources=current.resources||{}, number=(value,unit)=>value==null?'—':value+' '+unit;
      text('measurement-cpu',number(resources.cpu_total_percent,'%'));text('measurement-ram',number(resources.ram_used_mb,'MB'));text('measurement-rss',number(resources.main?.rss_mb,'MB'));text('measurement-temp',number(resources.temperature_c,'°C'));
      for(const [id,suffix] of [['measurement-csv-export','?format=csv'],['measurement-raw-export','']]){const link=byId(id);link.hidden=!current.run;if(current.run)link.href='/api/experiments/'+encodeURIComponent(current.run.run_id)+'/export'+suffix;}
      text('measurement-observer-status',requests.length?requests.length+' observaciones obligatorias pendientes':'Sin observaciones pendientes');
      const q=current.quality;
      text('measurement-quality',q?`${q.samples} muestras · ${q.missing_samples} segundos sin muestra · ${q.unavailable_observations} registros con datos no observados · ${q.task_failures||0} fallos · ${q.task_timeouts||0} timeouts · ${q.sensor_incomplete_samples||0} muestras con sensores incompletos. ${!current.running?(q.record_complete?'Traza completa.':'Registro con pendientes o datos faltantes.'):'Cobertura provisional.'}`:'El registro mostrará su cobertura y datos faltantes.');
      const oldest=requests.find(r=>!deferred.has(r.request_id));
      if(oldest&&!dialog.open&&!saving&&!setupMode&&autoKey!==oldest.request_id){autoKey=oldest.request_id;selectedRequest=oldest;openForm();}
      controls();
    }
  };
})();
