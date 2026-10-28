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
  const context=vm.createContext({document,window:{},console,fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({run_id:'new-run',runs:[],...respond(url,options)})};}});
  for(const file of ['measurement.js','experiment.js'])vm.runInContext(fs.readFileSync('public/'+file,'utf8'),context);
  get('experiment-scenario').value='S2';get('experiment-mode').value='C';get('experiment-repetition').value='2';
  return {get,calls,guides,ui:context.window.measurement,experiment:context.window.experimentation};
}
const phases={yolo:{status:'ready'},text:{status:'ready'},vision:{status:'ready'}};
const request={request_id:'request',requested_at:'2026-10-27T12:00:00Z',reason:'VISION_TASK_STARTED',task_id:'task',fields:['power_w','visible_people']};
const run={run_id:'run',mode:'C',guided:true,scenario_id:'S2',repetition:2,status:'RUNNING',duration_seconds:1800};

test('comenzar exige condiciones iniciales y envía escenario, repetición y W reales',async()=>{
  const {get,calls,ui}=fixture();
  ui.render({running:false},phases,false);
  assert.equal(get('experiment-start').disabled,false);
  get('experiment-start').onclick();
  assert.equal(calls.length,0);
  assert.equal(get('observer-dialog').open,true);
  for(const [id,value] of [['observer-name','Ana'],['observer-instrument','V1'],['observer-equipment','Pi'],['observer-power','10.5'],['observer-people','0']])get(id).value=value;
  await get('observer-form').onsubmit({preventDefault(){}});
  const body=JSON.parse(calls[0].options.body);
  assert.equal(calls[0].url,'/api/experiments/start');
  assert.equal(body.mode,'C');assert.equal(body.scenario_id,'S2');assert.equal(body.repetition,2);
  assert.equal(body.initial_observation.power_w,10.5);assert.equal(body.initial_observation.visible_people,0);
  assert.equal(get('observer-dialog').open,false);
});

test('reutiliza el panel literal, congela guion y no crea otro inicio al reconectar',()=>{
  const {get,calls,ui,guides}=fixture();
  ui.render({running:true,run,elapsed_s:125,observer_requests:[]},phases,false);
  assert.equal(get('experiment-live').children[0],get('measurement-workspace'));
  assert.equal(get('measurement-clock').textContent,'02:05');
  assert.equal(get('experiment-scenario').disabled,true);
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
  assert.equal(get('observer-dialog').open,true);
  get('observer-power').value='12';
  ui.render({...data,elapsed_s:20},phases,false);
  assert.equal(get('observer-power').value,'12');
  get('observer-people-unavailable').checked=true;get('observer-people-unavailable').onchange();
  assert.equal(get('observer-people').disabled,true);
  assert.equal(get('observer-missing').required,true);
  get('observer-missing').value='No observé la captura';
  let prevented=false;get('observer-dialog').listeners.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);
  await get('observer-form').onsubmit({preventDefault(){}});
  const body=JSON.parse(calls[0].options.body);
  assert.equal(body.power_w,12);assert.equal(body.visible_people,null);
  assert.deepEqual(body.unavailable_fields,['visible_people']);
  assert.equal(calls[0].url,'/api/experiments/run/observer-requests/request');
});

test('dejar pendiente no borra solicitud ni detiene backend; se puede reabrir',()=>{
  const {get,calls,ui}=fixture();
  const data={running:true,run,observer_requests:[request]};
  ui.render(data,phases,false);get('observer-later').onclick();
  ui.render({...data,elapsed_s:30},phases,false);
  assert.equal(get('observer-dialog').open,false);
  assert.match(get('measurement-observer-status').textContent,/1 observaciones/);
  get('measurement-observe').onclick();assert.equal(get('observer-dialog').open,true);
  assert.equal(calls.length,0);
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
  for(const match of script.matchAll(/byId\('([^']+)'\)/g))assert.ok(ids.includes(match[1]),'Falta '+match[1]);
});

test('playground inicia F sin protocolo y Experimentación guarda S3 repetición 3',async()=>{
  const {get,calls,ui}=fixture();
  ui.render({running:false,enabled_modes:['A','B','C','D','E','F']},phases,false);
  get('measurement-mode').value='F';await get('measurement-toggle').onclick();
  assert.deepEqual(JSON.parse(calls[0].options.body),{mode:'F'});
  ui.render({running:false},phases,false);
  get('experiment-mode').value='F';get('experiment-scenario').value='S3';get('experiment-repetition').value='3';get('experiment-start').onclick();
  for(const [id,value] of [['observer-name','Ana'],['observer-instrument','V1'],['observer-equipment','Pi'],['observer-power','10'],['observer-people','2']])get(id).value=value;
  await get('observer-form').onsubmit({preventDefault(){}});
  const body=JSON.parse(calls[1].options.body);
  assert.equal(body.mode,'F');assert.equal(body.guided,true);assert.equal(body.scenario_id,'S3');assert.equal(body.repetition,3);
  assert.match(fs.readFileSync('public/index.html','utf8'),/option value="F"/);
});

test('panel compartido vuelve a pruebas al terminar la ejecución guiada',()=>{
  const {get,ui,experiment}=fixture();
  ui.render({running:false,run:{...run,mode:'F',status:'COMPLETED'},elapsed_s:1800},phases,false);
  assert.equal(get('experiment-live').children[0],get('measurement-workspace'));
  experiment.selectPanel('measurement');
  assert.equal(get('measurement').children.at(-1),get('measurement-workspace'));
  assert.equal(get('measurement-relocated').hidden,true);
});
