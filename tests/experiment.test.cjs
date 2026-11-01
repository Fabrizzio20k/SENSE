const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function fixture(respond=()=>({})){
  const elements=new Map(),calls=[];
  class Element{
    constructor(id=''){this.id=id;this.children=[];this.dataset={};this.attributes={};this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.open=false;this.listeners={};this.classList={toggle(){}};}
    append(...nodes){for(const node of nodes){if(node.parent)node.parent.children=node.parent.children.filter(n=>n!==node);node.parent=this;this.children.push(node);}}
    replaceChildren(...nodes){this.children=[];this.append(...nodes);}
    setAttribute(k,v){this.attributes[k]=v;}
    addEventListener(k,v){this.listeners[k]=v;}
    get options(){return this.children;}
    showModal(){this.open=true;}
    close(){this.open=false;}
    reportValidity(){return true;}
    reset(){for(const [id,node] of elements)if(id.startsWith('observer-')){node.value='';node.checked=false;}}
  }
  const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
  const guides=['S1','S2','S3'].map(s=>Object.assign(new Element(),{dataset:{scenario:s}}));
  const tabs=['preparation','measurement','experimentation'].map(s=>Object.assign(new Element(),{dataset:{panel:s}}));
  const document={getElementById:get,createElement:()=>new Element(),querySelectorAll:s=>s==='.experiment-guide'?guides:s==='.tab'?tabs:s==='.panel'?['preparation','measurement','experimentation'].map(get):[]};
  const context=vm.createContext({document,window:{location:{pathname:'/'}},console,fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({run_id:'new-run',runs:[],...respond(url,options)})};}});
  for(const file of ['api.js','measurement.js','experiment.js'])vm.runInContext(fs.readFileSync('public/'+file,'utf8'),context);
  get('experiment-scenario').value='S2';get('experiment-mode').value='C';get('experiment-repetition').value='2';
  return {get,calls,guides,ui:context.window.measurement,experiment:context.window.experimentation};
}
const phases={yolo:{status:'ready'},text:{status:'ready'},vision:{status:'ready'}};
const request={request_id:'request',requested_at:'2026-10-27T12:00:00Z',reason:'VISION_TASK_STARTED',task_id:'task',fields:['power_w','visible_people']};
const run={run_id:'run',mode:'C',guided:true,scenario_id:'S2',repetition:2,status:'RUNNING',duration_seconds:1800};

test('cambios de presencia B–F se muestran como cambios del sensor, incluidos pendientes anteriores',()=>{
  for(const mode of ['B','C','D','E','F'])for(const reason of ['SENSOR_PRESENCE_CHANGED','MANUAL_PRESENCE_CHANGED']){
    const {get,ui}=fixture();
    ui.render({running:true,run:{...run,mode},observer_requests:[{...request,reason,fields:['power_w','visible_people','action']}]},phases,false);
    assert.equal(get('measurement-pending-list').children[0].children[1].children[0].textContent,'Cambio del sensor de presencia');
    get('measurement-observe').onclick();
    assert.equal(get('observer-title').textContent,'Cambio del sensor de presencia');
    assert.equal(get('observer-action-group').hidden,false);
  }
});

test('comenzar exige condiciones iniciales y envía escenario, repetición y W reales',async()=>{
  const {get,calls,ui}=fixture();
  ui.render({running:false,observation_region:'configured_view',run:{...run,status:'COMPLETED',observation_region:'previous_view'}},phases,false);
  assert.equal(get('experiment-start').disabled,false);
  get('experiment-start').onclick();
  assert.equal(calls.length,0);
  assert.equal(get('observer-dialog').open,true);
  for(const [id,value] of [['observer-name','Ana'],['observer-instrument','V1'],['observer-power','10.5'],['observer-people','0']])get(id).value=value;
  await get('observer-form').onsubmit({preventDefault(){}});
  const body=JSON.parse(calls[0].options.body);
  assert.equal(calls[0].url,'/api/experiments/start');
  assert.equal(body.mode,'C');assert.equal(body.scenario_id,'S2');assert.equal(body.repetition,2);
  assert.equal(body.initial_observation.power_w,10.5);assert.equal(body.initial_observation.visible_people,0);
  assert.equal(body.initial_observation.region,'configured_view');
  assert.equal(body.initial_observation.equipment,'Raspberry Pi, todos los sensores y cámara');
  assert.equal(body.initial_observation.observer,'Ana');assert.equal(body.initial_observation.instrument,'V1');
  assert.equal(get('observer-dialog').open,false);
});

test('reutiliza el panel literal, congela guion y no crea otro inicio al reconectar',()=>{
  const {get,calls,ui,guides}=fixture();
  ui.render({running:true,run,elapsed_s:125,observer_requests:[]},phases,false);
  assert.equal(get('experiment-live').children[0],get('measurement-workspace'));
  assert.equal(get('measurement-clock').textContent,'02:05');
  assert.equal(get('experiment-scenario').disabled,true);
  assert.equal(get('experiment-guide-details').open,false);
  assert.equal(guides[0].hidden,true);assert.equal(guides[1].hidden,false);
  assert.equal(get('measurement-csv-export').href,'/api/experiments/run/export?format=csv');
  ui.connection(false);
  assert.equal(get('experiment-start').disabled,true);
  assert.match(get('measurement-clock-note').textContent,/última duración recibida/);
  ui.render({running:true,run,elapsed_s:126},phases,false);
  assert.equal(get('experiment-live').children.length,1);
  assert.equal(calls.length,0);
});

test('aviso persistente conserva formulario al recibir muestras y permite declarar faltantes',async()=>{
  const {get,calls,ui}=fixture(()=>({observer_requests:[],quality:{}}));
  const data={running:true,run,observer_requests:[request],context:{observations:{count:{value:2,status:'VALID',age_seconds:0}}}};
  ui.render(data,phases,false);
  assert.equal(get('observer-dialog').open,false);
  assert.equal(get('measurement-pending-list').children.length,1);
  get('measurement-observe').onclick();
  assert.equal(get('observer-dialog').open,true);
  get('observer-power').value='12';
  ui.render({...data,elapsed_s:20},phases,false);
  assert.equal(get('observer-power').value,'12');
  get('observer-people-unavailable').checked=true;get('observer-people-unavailable').onchange();
  assert.equal(get('observer-people').disabled,true);
  assert.equal(get('observer-missing').required,true);
  get('observer-missing').value='No observé la captura';
  let prevented=false;get('observer-dialog').listeners.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);
  assert.equal(get('observer-dialog').open,false);
  get('observer-pending-toggle').onclick();
  assert.equal(get('observer-power').value,'12');
  assert.equal(get('observer-missing').value,'No observé la captura');
  await get('observer-form').onsubmit({preventDefault(){}});
  const body=JSON.parse(calls[0].options.body);
  assert.equal(body.power_w,12);assert.equal(body.visible_people,null);
  assert.equal(body.region,'rasp_shared_view');
  assert.deepEqual(body.unavailable_fields,['visible_people']);
  assert.equal(calls[0].url,'/api/experiments/run/observer-requests/request');
});

test('dejar pendiente no borra solicitud ni detiene backend; se puede reabrir',()=>{
  const {get,calls,ui}=fixture();
  const data={running:true,run,observer_requests:[request]};
  ui.render(data,phases,false);
  get('measurement-observe').onclick();
  const eventTime=get('observer-event-time').textContent;
  get('observer-power').value='8.2';get('observer-power').oninput();
  const readingTime=get('observer-power-time').value;
  get('observer-later').onclick();
  ui.render({...data,elapsed_s:30},phases,false);
  assert.equal(get('observer-dialog').open,false);
  assert.match(get('measurement-observer-status').textContent,/1 observaciones/);
  assert.equal(get('observer-pending-toggle').textContent,'Pendientes · 1');
  get('measurement-observe').onclick();assert.equal(get('observer-dialog').open,true);
  assert.equal(get('observer-power').value,'8.2');
  assert.equal(get('observer-power-time').value,readingTime);
  assert.equal(get('observer-event-time').textContent,eventTime);
  assert.equal(calls.length,0);
});

test('repetir requiere un clic, admite cero y registra cada campo repetido',async()=>{
  const {get,calls,ui}=fixture(()=>({observer_requests:[],quality:{},observer_previous:{power_w:0,visible_people:3}}));
  const data={running:true,run,observer_previous:{power_w:0,visible_people:0},observer_requests:[request]};
  ui.render(data,phases,false);
  get('measurement-observe').onclick();
  assert.equal(get('observer-power').value,'');assert.equal(get('observer-people').value,'');
  assert.equal(get('observer-power-repeat').disabled,false);
  get('observer-power-repeat').onclick();get('observer-people-repeat').onclick();
  assert.equal(get('observer-power').value,'0');assert.equal(get('observer-people').value,'0');
  get('observer-people').value='3';get('observer-people').oninput();
  await get('observer-form').onsubmit({preventDefault(){}});
  const payload=JSON.parse(calls[0].options.body);
  assert.deepEqual(payload.repeated_fields,['power_w']);
  assert.equal(payload.power_w,0);assert.equal(payload.visible_people,3);
  assert.notEqual(payload.observed_at,request.requested_at);
  assert.ok(payload.power_observed_at);assert.ok(payload.people_observed_at);
  assert.equal(get('observer-pending-toggle').hidden,true);
  assert.equal(get('observer-pending-count').textContent,'0 pendientes');
});

test('solo pide los campos del evento y el contador crece sin borrar el borrador',()=>{
  const {get,ui}=fixture();
  const powerOnly={...request,fields:['power_w'],reason:'TEXT_TASK_STARTED'};
  const data={running:true,run,observer_requests:[powerOnly],observer_previous:{power_w:9}};
  ui.render(data,phases,false);
  get('measurement-observe').onclick();
  assert.equal(get('observer-people-group').hidden,true);assert.equal(get('observer-action-group').hidden,true);
  assert.equal(get('observer-details').open,false);
  get('observer-power').value='10';get('observer-power').oninput();
  ui.render({...data,observer_requests:[powerOnly,{...request,request_id:'second'}]},phases,false);
  assert.equal(get('observer-power').value,'10');
  assert.equal(get('observer-pending-count').textContent,'2 pendientes');
  assert.equal(get('observer-pending-toggle').textContent,'Pendientes · 2');
  get('observer-power-unavailable').checked=true;get('observer-power-unavailable').onchange();
  assert.equal(get('observer-power-repeat').disabled,true);
  get('observer-later').onclick();
  ui.render({...data,observer_requests:[powerOnly,{...request,request_id:'second'}]},phases,false);
  assert.equal(get('observer-dialog').open,false);
  assert.equal(get('observer-pending-toggle').textContent,'Pendientes · 2');
});

test('cancelar las condiciones iniciales conserva el borrador al volver al mismo caso',()=>{
  const {get,ui}=fixture();
  ui.render({running:false},phases,false);
  get('experiment-start').onclick();
  get('observer-name').value='Ana';get('observer-instrument').value='V1';
  get('observer-power').value='10';get('observer-power').oninput();
  get('observer-later').onclick();get('experiment-start').onclick();
  assert.equal(get('observer-name').value,'Ana');assert.equal(get('observer-instrument').value,'V1');
  assert.equal(get('observer-power').value,'10');
  assert.equal(get('observer-power-repeat').disabled,true);
});

test('guardar un pendiente actualiza inmediatamente el siguiente y los botones de repetir',async()=>{
  const next={...request,request_id:'next',fields:['power_w']};
  const {get,calls,ui}=fixture(()=>({observer_requests:[next],observer_previous:{power_w:12,visible_people:1},quality:{}}));
  ui.render({running:true,run,observer_requests:[request,next],observer_previous:{power_w:8}},phases,false);
  get('measurement-observe').onclick();
  get('observer-power').value='12';get('observer-people').value='1';
  await get('observer-form').onsubmit({preventDefault(){}});
  assert.equal(get('observer-dialog').open,true);
  assert.equal(get('observer-pending-count').textContent,'1 pendientes');
  assert.equal(get('observer-power-repeat').textContent,'Repetir 12 W');
  assert.equal(get('observer-people-group').hidden,true);
  assert.equal(get('observer-power').value,'');
  get('observer-power-repeat').onclick();
  await get('observer-form').onsubmit({preventDefault(){}});
  assert.equal(calls[1].url,'/api/experiments/run/observer-requests/next');
  assert.deepEqual(JSON.parse(calls[1].options.body).repeated_fields,['power_w']);
  assert.equal(get('observer-pending-toggle').hidden,true);
});

test('cierre a 30 minutos conserva descarga y solicita registro final',()=>{
  const {get,calls,ui}=fixture();
  ui.render({running:false,run:{...run,status:'COMPLETED',finish_reason:'MAX_RUN_DURATION'},elapsed_s:1800,observer_requests:[{...request,reason:'RUN_FINAL',fields:['power_w','visible_people','action']}],quality:{samples:1800,missing_samples:0,unavailable_observations:0,record_complete:false}},phases,false);
  assert.equal(get('measurement-clock').textContent,'30:00');
  assert.match(get('measurement-clock-note').textContent,/duración completada/);
  assert.equal(get('measurement-csv-export').hidden,false);
  assert.equal(get('observer-action-group').hidden,false);
  assert.match(get('measurement-quality').textContent,/1800 muestras/);
  assert.equal(calls.length,0);
});

test('los controles nuevos tienen un único destino HTML',()=>{
  const html=fs.readFileSync('public/index.html','utf8'),script=fs.readFileSync('public/experiment.js','utf8');
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(new Set(ids).size,ids.length);
  assert.ok(!ids.includes('observer-region'));assert.ok(!ids.includes('observer-equipment'));
  for(const match of script.matchAll(/byId\('([^']+)'\)/g))assert.ok(ids.includes(match[1]),'Falta '+match[1]);
});

test('playground inicia F sin protocolo y Experimentación guarda S3 repetición 3',async()=>{
  const {get,calls,ui}=fixture();
  ui.render({running:false,enabled_modes:['A','B','C','D','E','F']},phases,false);
  get('measurement-mode').value='F';await get('measurement-toggle').onclick();
  assert.deepEqual(JSON.parse(calls[0].options.body),{mode:'F'});
  ui.render({running:false},phases,false);
  get('experiment-mode').value='F';get('experiment-scenario').value='S3';get('experiment-repetition').value='3';get('experiment-start').onclick();
  for(const [id,value] of [['observer-name','Ana'],['observer-instrument','V1'],['observer-power','10'],['observer-people','2']])get(id).value=value;
  await get('observer-form').onsubmit({preventDefault(){}});
  const body=JSON.parse(calls[1].options.body);
  assert.equal(body.mode,'F');assert.equal(body.guided,true);assert.equal(body.scenario_id,'S3');assert.equal(body.repetition,3);
  assert.match(fs.readFileSync('public/index.html','utf8'),/option value="F"/);
});

test('los pendientes históricos conservan la región y el montaje de su ejecución',async()=>{
  const historical={...run,run_id:'old-run',observation_region:'old_view',equipment:'Montaje anterior'};
  const {get,calls,ui,experiment}=fixture(url=>url==='/api/experiments/old-run'?{run:historical,observer_requests:[request]}:{observer_requests:[],quality:{}});
  ui.render({running:false,observation_region:'current_view',run:{...run,status:'COMPLETED',observation_region:'current_view'}},phases,false);
  await experiment.review('old-run');
  assert.match(get('observer-mount').textContent,/Montaje anterior/);
  get('observer-power').value='10';get('observer-people').value='1';
  ui.render({running:false,observation_region:'another_view',run:{...run,status:'COMPLETED'}},phases,false);
  await get('observer-form').onsubmit({preventDefault(){}});
  assert.equal(calls[1].url,'/api/experiments/old-run/observer-requests/request');
  assert.equal(JSON.parse(calls[1].options.body).region,'old_view');
});

test('panel compartido vuelve a pruebas al terminar la ejecución guiada',()=>{
  const {get,ui,experiment}=fixture();
  ui.render({running:false,run:{...run,mode:'F',status:'COMPLETED'},elapsed_s:1800},phases,false);
  assert.equal(get('experiment-live').children[0],get('measurement-workspace'));
  experiment.selectPanel('measurement');
  assert.equal(get('measurement').children.at(-1),get('measurement-workspace'));
  assert.equal(get('measurement-relocated').hidden,true);
});
