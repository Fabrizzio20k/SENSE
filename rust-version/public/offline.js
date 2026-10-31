/* Simulador de presentación. Nunca llama al backend ni representa mediciones físicas. */
(() => {
  'use strict';
  if(!window.senseAPI.offline)return;
  const copy=value=>structuredClone(value),iso=(start,second)=>new Date(Date.parse(start)+second*1000).toISOString();
  const config={sensors:{presence_ttl_seconds:6,environment_ttl_seconds:10},vision:{ttl_seconds:60},regions:{camera_region:'rasp_shared_view'}};
  const ready=()=>Object.fromEntries(['yolo','text','vision'].map(key=>[key,{status:'ready',detail:'Disponible · simulación offline'}]));
  let serial=0,current=null,scene='ready',phases=ready(),sandboxTasks={},captureVersion=0;
  const id=()=> 'offline-'+(++serial),listeners=new Set(),runs=new Map();
  function sample(start,second){
    const people=Math.floor(second/300)%4,health=Object.fromEntries(['sht40','ens160','radar','camera','gemma'].map(key=>[key,{status:second>=900&&second<950&&key==='camera'?'FAILED':'HEALTHY'}]));
    const row={second,elapsed_s:second,timestamp_utc:iso(start,second),fsm_state:second%30===0?'VISION':'WAIT',temperature_c:Number((24+second/1800).toFixed(2)),humidity_pct:48,aqi:1,tvoc_ppb:75,eco2_ppm_equiv:550+people*75,presence:people?1:0,visible_count:people,
      cpu_percent:20+second%25,ram_used_mb:3300+second%100,pi_temp_c:52+second%8,process_rss_mb:650,component_health:health,queued_tasks:0,vision_worker_state:second%30===0?'RUNNING':'IDLE',gemma_worker_state:'IDLE',presence_source:'RADAR',sample_status:'OBSERVED'};
    for(const key of ['temperature','humidity','aqi','tvoc','eco2','presence','count'])Object.assign(row,{[key+'_status']:'VALID',[key+'_age_s']:key==='count'?second%30:0,[key+'_observed_at']:iso(start,key==='count'?second-second%30:second),[key+'_observation_id']:key+'-'+second});
    return row;
  }
  function answers(row,start){
    const values={Q1:row.presence?'Presencia detectada en la vista compartida.':'Sin presencia en la vista compartida.',Q2:row.visible_count,Q3:{temperature:{value:row.temperature_c,unit:'°C',status:'VALID'},humidity:{value:row.humidity_pct,unit:'%RH',status:'VALID'},eco2:{value:row.eco2_ppm_equiv,unit:'ppm equivalent',status:'VALID'}},Q4:[],Q5:'Evidencia disponible y consistente en esta escena simulada.',Q6:'Coincidencia temporal de ocupación y condiciones ambientales; no implica causalidad.',Q7:'Ejemplo simulado: vista del aula con mobiliario y personas visibles.'};
    const questions=['Presencia','Personas visibles','Condiciones ambientales','Cambios ambientales','Suficiencia de evidencia','Relación contextual','Descripción de imagen'];
    return Object.fromEntries(Object.entries(values).map(([qid,answer],i)=>[qid,{question_id:qid,question:questions[i],status:'RESOLVED',answer,evaluated_at:iso(start,row.second),evidence_ids:['demo-'+row.second],limitations:['Datos simulados para desarrollo de interfaz.'],pending_information:[]}]));
  }
  function event(trace,second,type,payload){const row={sequence:trace.events.length+1,timestamp:iso(trace.run.start_time,second),recorded_at:iso(trace.run.start_time,second),type,payload};trace.events.push(row);return row;}
  function interpretation(second){return {interpretation_id:'demo-gemma-'+second,question_id:'Q7',image_id:'demo-image-'+second,completed_at:iso('2026-10-27T12:00:00Z',second),validation_status:'VALIDATED',inferences:['Descripción simulada del aula; no es una inferencia real.'],unknowns:['No se identifican personas.'],recommendations:['Revisar la evidencia registrada.']};}
  function demo(){
    const run={run_id:'offline-example-30min',mode:'F',policy_mode:'E',guided:true,scenario_id:'S2',repetition:1,status:'COMPLETED',start_time:'2026-10-27T12:00:00Z',end_time:'2026-10-27T12:30:00Z',duration_seconds:1800,elapsed_s:1800,expected_samples:1800,finish_reason:'MAX_RUN_DURATION',simulated:true,data_origin:'offline-demo',observation_region:'rasp_shared_view',observer:'Observador de ejemplo',instrument:'Vatímetro simulado',equipment:'Raspberry Pi, todos los sensores y cámara',config};
    const trace={run,samples:[],events:[],records:[],requests:[]};event(trace,0,'RUN_STARTED',run);
    for(let second=0;second<1800;second++){
      if(second<600||second>603)trace.samples.push(sample(run.start_time,second));
      if(second%60===0){
        const task='demo-task-'+second,command={command_id:task,experiment_run_id:run.run_id,target_agent:'VisionAgent',action:'vision',parameters:{question_id:'Q2'}};
        event(trace,second,'FSM_TRANSITION',{from:'WAIT',to:'VISION',reason:'DEMO'});
        event(trace,second,'TASK_STARTED',{command,started_at:iso(run.start_time,second)});
        event(trace,second+1,'TASK_COMPLETED',{command,completed_at:iso(run.start_time,second+1),result:{count:sample(run.start_time,second).visible_count,image_id:'demo-'+second}});
        event(trace,second+1,'RESULT_PUBLISHED',{answers:answers(sample(run.start_time,second+1),run.start_time)});
        event(trace,second+2,'FSM_TRANSITION',{from:'VISION',to:'WAIT',reason:'DEMO_COMPLETED'});
        trace.records.push({run_id:run.run_id,record_id:'demo-record-'+second,kind:'OBSERVER_RECORD',reason:'PERIODIC_W',observed_at:iso(run.start_time,second+3),power_observed_at:iso(run.start_time,second+3),people_observed_at:iso(run.start_time,second+3),recorded_at:iso(run.start_time,second+5),event_at:iso(run.start_time,second),region:'rasp_shared_view',power_w:8+second%5,visible_people:sample(run.start_time,second).visible_count,notes:'Dato simulado.',unavailable_fields:[],repeated_fields:second%120===0?['power_w']:[]});
      }
    }
    event(trace,600,'SAMPLE_GAP',{from_second:600,to_second:603,reason:'DEMO_GAP'});
    event(trace,900,'FAULT_INJECTED',{fault_id:'demo-camera-fault',component:'camera',simulated:true});event(trace,901,'COMPONENT_HEALTH_CHANGED',{component:'camera',status:'FAILED'});
    event(trace,950,'FAULT_RECOVERED',{fault_id:'demo-camera-fault',component:'camera'});
    const command={command_id:'demo-gemma',target_agent:'InterpretationAgent',action:'multimodal',parameters:{question_id:'Q7'}};
    event(trace,1000,'TASK_STARTED',{command,started_at:iso(run.start_time,1000)});event(trace,1025,'TASK_COMPLETED',{command,result:interpretation(1025),completed_at:iso(run.start_time,1025)});
    event(trace,1800,'RUN_FINISHED',{reason:'MAX_RUN_DURATION'});event(trace,1805,'HISTORICAL_INTERPRETATION',{...interpretation(1805),historical:true});
    return trace;
  }
  const example=demo();runs.set(example.run.run_id,example);
  function recordRequest(reason,fields){
    const request={request_id:id(),run_id:current.run.run_id,requested_at:iso(current.run.start_time,current.elapsed),reason,fields,status:'PENDING'};current.requests.push(request);event(current,current.elapsed,'OBSERVER_REQUESTED',request);return request;
  }
  function begin(body={},elapsed=0){
    const start=new Date(Date.now()-elapsed*1000).toISOString();
    current={run:{run_id:id(),mode:body.mode||'C',policy_mode:body.mode==='F'?'E':body.mode||'C',guided:!!body.guided,scenario_id:body.scenario_id||'S2',repetition:body.repetition||1,status:'RUNNING',start_time:start,duration_seconds:1800,observation_region:'rasp_shared_view',simulated:true,data_origin:'offline-demo',config,...Object.fromEntries(['observer','instrument','equipment'].map(key=>[key,body.initial_observation?.[key]||({observer:'Ana · demo',instrument:'Vatímetro · demo',equipment:'Raspberry Pi, todos los sensores y cámara'})[key]]))},elapsed,samples:[],events:[],records:[],requests:[],manual:{mode:'AUTO',detected:null},disabled:[],faults:[],timeouts:{},previous:{power_w:9,visible_people:0}};
    event(current,0,'RUN_STARTED',copy(current.run));for(let second=0;second<=Math.min(1799,elapsed);second++)current.samples.push(sample(start,second));
    event(current,elapsed,'RESULT_PUBLISHED',{answers:answers(sample(start,elapsed),start)});
    if(body.initial_observation)current.records.push({...copy(body.initial_observation),record_id:id(),run_id:current.run.run_id,kind:'OBSERVER_RECORD',recorded_at:new Date().toISOString()});
    if(body.initial_observation)for(const key of ['power_w','visible_people'])if(body.initial_observation[key]!=null)current.previous[key]=body.initial_observation[key];
    runs.set(current.run.run_id,current);return current;
  }
  function stop(reason='USER_STOP'){
    if(!current||current.run.status!=='RUNNING')return;
    Object.assign(current.run,{status:'COMPLETED',end_time:iso(current.run.start_time,current.elapsed),elapsed_s:current.elapsed,expected_samples:Math.ceil(current.elapsed),finish_reason:reason});event(current,current.elapsed,'RUN_FINISHED',{reason});
    if(current.run.guided)recordRequest('RUN_FINAL',['power_w','visible_people','action']);
  }
  function quality(trace){const missing=Math.max(0,(trace.run.expected_samples||trace.samples.length)-trace.samples.length),unavailable=trace.records.filter(r=>r.unavailable_fields?.length).length,pending=trace.requests.filter(r=>r.status==='PENDING').length;return {samples:trace.samples.length,missing_samples:missing,unavailable_observations:unavailable,pending_observations:pending,record_complete:trace.run.status==='COMPLETED'&&!missing&&!unavailable&&!pending,task_failures:0,task_timeouts:0,sensor_incomplete_samples:0};}
  function measurement(){
    if(!current)return {running:false,enabled_modes:[...'ABCDEF'],observation_region:'rasp_shared_view',observer_requests:[]};
    const s=sample(current.run.start_time,current.elapsed),missing=scene==='missing';
    const observations={};
    for(const [key,field,unit] of [['temperature','temperature_c','°C'],['humidity','humidity_pct','%RH'],['aqi','aqi','ENS160 AQI'],['eco2','eco2_ppm_equiv','ppm equivalent'],['presence','presence','presence'],['count','visible_count','visible_people']])observations[key]={value:missing&&key==='temperature'?null:key==='presence'&&current.manual.mode==='MANUAL'?Number(current.manual.detected):s[field],unit,status:missing&&key==='temperature'?'UNAVAILABLE':'VALID',captured_at:s[key+'_observed_at'],age_seconds:s[key+'_age_s'],region:'rasp_shared_view',metadata:key==='presence'?{state_code:s.presence?2:0,trigger_distance_cm:s.presence?25:150,trigger_distance_source:'static_distance_cm'}:{}};
    const health=copy(s.component_health);for(const component of current.disabled)health[component]={status:'FAILED'};
    return {running:current.run.status==='RUNNING',run:copy(current.run),enabled_modes:[...'ABCDEF'],elapsed_s:current.elapsed,fsm:s.fsm_state,cycle:{actions:['ACQUIRE','ASSESS',s.fsm_state]},observation_region:'rasp_shared_view',context:{observations},answers:answers(s,current.run.start_time),interpretations:['D','E','F'].includes(current.run.mode)?[interpretation(25)]:[],resources:{cpu_total_percent:s.cpu_percent,ram_used_mb:s.ram_used_mb,temperature_c:s.pi_temp_c,main:{rss_mb:650}},component_health:health,presence_control:copy(current.manual),raw_presence:observations.presence,reactive_trigger:{state:s.presence?'NEAR':'FAR',enter_below_cm:30,exit_at_or_above_cm:50,required_samples:3,confirmed_samples:3},fault_control:{disabled:current.disabled,timeouts:current.timeouts,faults:current.faults},observer_requests:copy(current.requests.filter(r=>r.status==='PENDING')),observer_previous:copy(current.previous),quality:quality(current),tasks:{active:[],queued:0,counters:{}},transitions:current.events.filter(e=>e.type==='FSM_TRANSITION').slice(-20).map(e=>({...e.payload,timestamp:e.timestamp})),decisions:[{kind:'VISION',reason:'DEMO_ONLY'}]};
  }
  function snapshot(){const m=measurement(),s=current?sample(current.run.start_time,current.elapsed):sample(new Date().toISOString(),0);return {phases:copy(phases),system:{cpu_percent:s.cpu_percent,memory_percent:42,memory_used_mb:s.ram_used_mb},telemetry:{schema:'rustio.iot.telemetry.v1',timestamp:new Date().toISOString(),environment:{sht40:{temperature_c:s.temperature_c,humidity_percent:s.humidity_pct},ens160:{aqi:s.aqi,eco2_ppm:s.eco2_ppm_equiv}},presence:{state:s.presence?'Presencia · demo':'Sin presencia · demo',total_distance_cm:s.presence?25:150}},sandbox:{ready:Object.values(phases).every(p=>p.status==='ready'),busy:Object.values(sandboxTasks).some(t=>t.status==='loading')},tasks:copy(sandboxTasks),measurement:m};}
  function emit(){for(const listener of listeners)listener(snapshot());}
  function tick(publish=true){
    if(current?.run.status==='RUNNING'){
      current.elapsed=Math.min(1800,current.elapsed+1);current.run.elapsed_s=current.elapsed;
      if(current.elapsed<1800)current.samples.push(sample(current.run.start_time,current.elapsed));
      if(current.elapsed%60===0&&current.run.guided)recordRequest('PERIODIC_W:'+current.elapsed,['power_w']);
      if(current.elapsed===1800)stop('MAX_RUN_DURATION');
    }
    if(publish)emit();
  }
  function setScene(value){
    scene=value;phases=ready();sandboxTasks={};
    if(value==='ready'||value==='loading'){current=null;if(value==='loading')phases=Object.fromEntries(['yolo','text','vision'].map(key=>[key,{status:'loading',detail:'Preparando · simulación'}]));}
    else{
      begin({mode:value==='failure'?'F':'E',guided:true},value==='finished'?1800:150);
      if(value==='pending'){recordRequest('VISION_TASK_STARTED',['power_w','visible_people']);recordRequest('PERIODIC_W:120',['power_w']);}
      if(value==='failure'){current.disabled=['camera'];current.faults=[{fault_id:id(),component:'camera',simulated:true,detected_at:new Date().toISOString()}];}
      if(value==='finished')stop('MAX_RUN_DURATION');
    }
    emit();
  }
  function response(body,status=200){return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});}
  async function fetchMock(url,options={}){
    const address=new URL(url,'http://offline.local'),path=address.pathname,body=options.body?JSON.parse(options.body):{},method=options.method||'GET';
    if(path==='/api/experiments'&&method==='GET')return response({runs:[...runs.values()].reverse().map(t=>({...t.run,quality:quality(t)}))});
    if(path==='/api/experiments/start'){if(current?.run.status==='RUNNING')return response({error:'La demo ya tiene una ejecución activa.'},409);begin(body);emit();return response({run_id:current.run.run_id},202);}
    if(path==='/api/experiments/stop'){stop();emit();return response({ok:true},202);}
    if(path==='/api/experiments/query'){if(current){event(current,current.elapsed,'QUESTION_REQUESTED',body);if(current.run.guided)recordRequest('VISION_TASK_STARTED',['power_w','visible_people']);}emit();return response({ok:true},202);}
    if(path==='/api/experiments/presence'){if(current)current.manual={mode:body.mode==='auto'?'AUTO':'MANUAL',detected:body.mode==='auto'?null:body.detected,near:body.near};emit();return response({ok:true},202);}
    if(path==='/api/experiments/faults'){
      if(!current||current.run.mode!=='F')return response({error:'Selecciona la escena F para probar fallas.'},400);
      if(body.action==='availability'){current.disabled=current.disabled.filter(c=>c!==body.component);if(!body.enabled)current.disabled.push(body.component);event(current,current.elapsed,body.enabled?'FAULT_RESTORED':'FAULT_INJECTED',{...body,simulated:true});}
      else current.timeouts[body.lane]='ARMED';
      emit();return response({ok:true},202);
    }
    if(['/api/capture','/api/yolo','/api/chat','/api/vision'].includes(path)){
      const key=({'/api/capture':'capture','/api/yolo':'yolo','/api/chat':'chat','/api/vision':'vision'})[path];
      sandboxTasks[key]={status:'loading',detail:'Procesando ejemplo simulado…'};emit();
      window.setTimeout(()=>{sandboxTasks[key]={status:'ready',detail:key==='yolo'?'2 personas visibles · resultado simulado.':key==='capture'?'Imagen de ejemplo · sin cámara.':'Respuesta simulada para revisar la interfaz. No se ejecutó Gemma.',seconds:++captureVersion/10};emit();},350);
      return response({ok:true},202);
    }
    const match=path.match(/^\/api\/experiments\/([^/]+)(?:\/(.*))?$/);
    if(match){
      const trace=runs.get(decodeURIComponent(match[1])),action=match[2];if(!trace)return response({error:'Ejecución simulada inexistente.'},404);
      const pending=()=>trace.requests.filter(r=>r.status==='PENDING');
      if(action==='export'){
        if(address.searchParams.get('format')==='csv')return new Response(window.senseReplayData.toZip(trace),{headers:{'Content-Type':'application/zip'}});
        const lines=[{type:'RUN',payload:trace.run},...trace.events,...trace.records.map(r=>({type:r.kind,payload:r})),...trace.samples.map(s=>({type:'SAMPLE_1S',payload:s}))];return new Response(lines.map(r=>JSON.stringify(r)).join('\n'),{headers:{'Content-Type':'application/x-ndjson'}});
      }
      if(action==='observer-requests'&&method==='POST'){
        if(trace!==current)return response({error:'Abre una escena activa para registrar eventos.'},400);
        recordRequest('OBSERVER_EVENT',['power_w','visible_people','action']);emit();return response({observer_requests:pending()},201);
      }
      if(action?.startsWith('observer-requests/')&&method==='POST'){
        const requested=pending().find(r=>r.request_id===decodeURIComponent(action.split('/')[1]));if(!requested)return response({error:'Solicitud ya resuelta.'},400);
        const record={...copy(body),kind:'OBSERVER_RECORD',record_id:id(),run_id:trace.run.run_id,request_id:requested.request_id,reason:requested.reason,event_at:requested.requested_at,recorded_at:iso(trace.run.start_time,trace.elapsed||0)};trace.records.push(record);requested.status='RESOLVED';requested.record_id=record.record_id;
        trace.previous??={};for(const key of ['power_w','visible_people'])if(requested.fields.includes(key)&&record[key]!=null)trace.previous[key]=record[key];
        return response({record_id:record.record_id,observer_requests:pending(),observer_previous:trace.previous,quality:quality(trace)},201);
      }
      if(!action)return response({run:trace.run,events:trace.events,observer_requests:pending(),observer_previous:trace.previous||{power_w:9,visible_people:0},quality:quality(trace)});
    }
    return response({error:'Ruta no simulada; no se enviaron datos al backend.'},404);
  }
  const svg='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400"><rect width="640" height="400" fill="#edf2ed"/><rect x="100" y="40" width="440" height="100" rx="8" fill="#285d45"/><path d="M0 250H640L640 400H0Z" fill="#cbd6cb"/><g fill="#b7a483"><rect x="50" y="240" width="150" height="45"/><rect x="245" y="240" width="150" height="45"/><rect x="440" y="240" width="150" height="45"/></g><g fill="#52635a"><circle cx="150" cy="215" r="20"/><rect x="125" y="235" width="50" height="70" rx="15"/><circle cx="480" cy="215" r="20"/><rect x="455" y="235" width="50" height="70" rx="15"/></g><text x="320" y="95" text-anchor="middle" fill="white" font-family="sans-serif" font-size="26">OFFLINE · Imagen simulada</text></svg>';
  window.senseOffline={fetch:fetchMock,scene:setScene,advance(){if(current?.run.status==='RUNNING')for(let n=0;n<60;n++)tick(false);emit();},demo:()=>copy(example),captureURL:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg),subscribe(listener){listeners.add(listener);listener(snapshot());const timer=window.setInterval(tick,1000);return ()=>{listeners.delete(listener);window.clearInterval(timer);};}};
})();
