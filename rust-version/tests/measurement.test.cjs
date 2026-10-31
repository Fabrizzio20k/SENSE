const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.textContent='';this.value='';this.disabled=false;this.open=false;this.dataset={};this.attributes={};this.className='';this.classList={toggle:()=>{}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(){}
  showModal(){this.open=true;}
  close(){this.open=false;}
  get options(){return this.children;}
}
function fixture(browser={}){
  const elements=new Map();
  const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:tag=>new Element(tag)};
  const calls=[];
  const context={document,window:browser,fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({run_id:'run',runs:[]})};},console};
  browser.location={pathname:'/'};
  vm.runInNewContext(fs.readFileSync('public/api.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync('public/measurement.js','utf8'),context);
  return {ui:context.window.measurement,get:id=>document.getElementById(id),calls};
}
const phases={yolo:{status:'ready'},text:{status:'ready'},vision:{status:'ready'}};

test('en móvil muestra pasos legibles y conserva el estado real sin inicializar el canvas',()=>{
  const {ui,get}=fixture({matchMedia:()=>({matches:true,addEventListener(){}}),cytoscape(){throw Error('No debe iniciar en móvil');}});
  ui.render({running:true,fsm:'VISION',run:{run_id:'run',mode:'C'},cycle:{actions:['ACQUIRE','ASSESS','VISION']}},phases,false);
  assert.equal(get('measurement-pipeline').hidden,false);
  assert.equal(get('measurement-flow-canvas').hidden,true);
  assert.equal(get('measurement-flow-controls').hidden,true);
  assert.equal(get('measurement-pipeline').children[3].className,'pipeline-node active');
  assert.doesNotThrow(()=>ui.resizeGraph());
});

test('selector A–F y pipeline gobernados por el backend',async()=>{
  const {ui,get,calls}=fixture();
  assert.equal(get('measurement-mode').options.length,6);
  assert.equal(get('measurement-pipeline').children.length,7);
  assert.ok(get('measurement-flow-canvas'));
  ui.render({running:false,enabled_modes:['A','B','C','D','E']},phases,false);
  assert.equal(get('measurement-toggle').disabled,false);
  get('measurement-mode').value='E';
  await get('measurement-toggle').onclick();
  assert.equal(calls[0].url,'/api/experiments/start');
  assert.equal(JSON.parse(calls[0].options.body).mode,'E');
  assert.equal(get('measurement-toggle').disabled,true);
  assert.equal(get('measurement-toggle').textContent,'Comenzar');
  assert.match(get('measurement-state').textContent,/esperando confirmación/);
  ui.render({running:true,reserved:false,fsm:'VISION',run:{run_id:'run',mode:'E',status:'RUNNING'},cycle:{actions:['ACQUIRE','ASSESS','VISION']}},phases,false);
  assert.equal(get('measurement-pipeline').children[3].className,'pipeline-node active');
  assert.equal(get('measurement-toggle').textContent,'Finalizar');
  get('measurement-toggle').onclick();
  assert.equal(get('finish-dialog').open,true);
  await get('finish-accept').onclick();
  assert.equal(calls[1].url,'/api/experiments/stop');
  assert.equal(get('measurement-toggle').disabled,true);
  assert.equal(get('measurement-toggle').textContent,'Finalizar');
});

test('desconocido conserva ausencia de valor, y cero es un conteo válido',()=>{
  const {ui,get}=fixture();
  ui.render({context:{observations:{count:{value:0,status:'VALID',age_seconds:1,region:'camera_view'},presence:{value:null,status:'UNAVAILABLE',age_seconds:1,region:'radar'}}}},phases,false);
  const cards=[...get('measurement-presence-readings').children,...get('measurement-environment-readings').children];
  assert.equal(cards[0].children[1].textContent,'—');
  assert.equal(cards[1].children[1].textContent,'0');
  assert.deepEqual(cards.map(card=>card.dataset.sprite),['radar','yolo','temperature','humidity','aqi','tvoc','eco2']);
  assert.equal(cards[0].children.at(-1).tagName,'details');
  assert.match(cards[0].children.at(-1).children[1].textContent,/Región · radar/);
  assert.match(cards[0].children.at(-1).children[2].textContent,/Fuente · radar/);
  assert.equal(get('measurement-flow-controls').hidden,false);
});

test('al perder conexión bloquea comandos; el sandbox activo bloquea comenzar',()=>{
  const {ui,get}=fixture();
  ui.render({running:false},phases,true);
  assert.equal(get('measurement-toggle').disabled,true);
  ui.render({running:false},phases,false);
  ui.connection(false);
  assert.equal(get('measurement-toggle').disabled,true);
});

test('control de radar manual aparece desde B y usa endpoint acotado',async()=>{
  const {ui,get,calls}=fixture();
  const data={running:true,run:{mode:'C',run_id:'run',status:'RUNNING'},presence_control:{mode:'AUTO',detected:null},context:{observations:{presence:{value:0,status:'VALID',age_seconds:1,region:'radar'}}}};
  ui.render(data,phases,false);
  const control=get('measurement-presence-readings').children[0].children[4];
  assert.equal(control.hidden,false);
  await control.children[0].onclick();
  assert.equal(calls[0].url,'/api/experiments/presence');
  assert.deepEqual(JSON.parse(calls[0].options.body),{mode:'manual',detected:false});
  ui.render({...data,presence_control:{mode:'MANUAL',detected:false}},phases,false);
  assert.equal(control.children[1].disabled,false);
  await control.children[1].onclick();
  assert.deepEqual(JSON.parse(calls[1].options.body),{mode:'manual',detected:true});
  ui.render({...data,run:{...data.run,mode:'A'}},phases,false);
  assert.equal(control.hidden,true);
});

test('contenido del modelo es texto y el detalle abierto sobrevive a actualizaciones',()=>{
  const {ui,get}=fixture();
  const answer={question_id:'Q1',question:'Presencia',answer:'<img src=x onerror=alert(1)>',limitations:[],pending_information:[]};
  ui.render({answers:{Q1:answer}},phases,false);
  const card=get('measurement-answers').children[0],detail=card.children[4];detail.open=true;
  ui.render({answers:{Q1:{...answer,evaluated_at:'new-time'}}},phases,false);
  assert.equal(get('measurement-answers').children[0],card);
  assert.equal(detail.open,true);
  assert.equal(card.children[1].textContent,answer.answer);
});

test('B distingue zona próxima de presencia original y explica conteo vencido',()=>{
  const {ui,get,calls}=fixture();
  const data={running:true,run:{mode:'B',run_id:'run',status:'RUNNING'},fsm:'WAIT',
    reactive_trigger:{state:'FAR',enter_below_cm:30,exit_at_or_above_cm:50,required_samples:3,confirmed_samples:3},
    context:{observations:{presence:{value:1,status:'VALID',age_seconds:1,region:'radar',metadata:{trigger_distance_cm:309,trigger_distance_source:'static_distance_cm'}},count:{value:2,status:'STALE',age_seconds:80,region:'camera'}}},
    decisions:[{kind:'VISION',reason:'NO_REACTIVE_TRIGGER'}]};
  ui.render(data,phases,false);
  const radar=get('measurement-presence-readings').children[0];
  assert.equal(radar.children[0].textContent,'Radar · zona B');
  assert.equal(radar.children[1].textContent,'Fuera de zona');
  assert.match(radar.children[5].textContent,/309 cm · blanco estático/);
  assert.match(radar.children[5].textContent,/presencia detectada/);
  assert.match(get('measurement-trigger').textContent,/entrada < 30 cm/);
  assert.match(get('measurement-trigger').textContent,/conteo está vencido/);
  assert.equal(calls.length,0);
  ui.render({...data,reactive_trigger:{...data.reactive_trigger,state:'UNKNOWN'},decisions:[{kind:'VISION',reason:'RADAR_DISTANCE_UNKNOWN'}]},phases,false);
  assert.equal(radar.children[1].textContent,'Zona desconocida');
  assert.match(get('measurement-trigger').textContent,/Sin distancia válida/);
});

test('respuestas automáticas legibles, unidades y datos desconocidos sin JSON',()=>{
  const {ui,get,calls}=fixture();
  ui.render({running:true,run:{mode:'B',run_id:'run',status:'RUNNING'},fsm:'WAIT',answers:{
    Q3:{question_id:'Q3',question:'Ambiente',status:'PARTIAL',evaluated_at:'2026-10-24T20:00:00Z',answer:{temperature:{value:26.3,unit:'°C',status:'VALID'},eco2:{value:null,unit:'ppm equivalent',status:'UNAVAILABLE'}},limitations:[],pending_information:['eco2']}
  }},phases,false);
  const card=get('measurement-answers').children[0];
  assert.match(card.children[1].textContent,/temperatura: 26.3 °C · Vigente/);
  assert.match(card.children[1].textContent,/eCO₂ estimado: sin lectura · Sin datos/);
  assert.match(card.children[2].textContent,/Con limitaciones · Sensores ambientales/);
  assert.match(card.children[3].textContent,/Falta: eCO₂ estimado/);
  assert.match(get('measurement-updated').textContent,/Última evaluación:/);
  assert.match(get('measurement-answer-note').textContent,/Actualización automática/);
  assert.equal(calls.length,0);
});

test('nueva evidencia cambia la respuesta sin consultar ni crear peticiones',()=>{
  const {ui,get,calls}=fixture();
  const data={running:true,run:{mode:'C',run_id:'run',status:'RUNNING'},fsm:'WAIT',answers:{Q2:{question_id:'Q2',question:'Conteo',status:'RESOLVED',answer:1,evaluated_at:'2026-10-24T20:00:00Z'}}};
  ui.render(data,phases,false);
  const card=get('measurement-answers').children[0];
  assert.equal(card.children[1].textContent,'1 persona visible');
  ui.render({...data,answers:{Q2:{...data.answers.Q2,answer:3,evaluated_at:'2026-10-24T20:01:00Z'}}},phases,false);
  assert.equal(card.children[1].textContent,'3 personas visibles');
  assert.equal(calls.length,0);
});

test('interpretaciones históricas se conservan al actualizar respuestas y estados son claros',()=>{
  const {ui,get}=fixture();
  const result={interpretation_id:'interpretation',question_id:'Q7',snapshot_id:'original',image_id:'image',completed_at:'2026-10-24T20:00:00Z',validation_status:'VALIDATED',inferences:['Personas aparentemente sentadas.'],unknowns:[],recommendations:[]};
  const data={running:true,run:{mode:'E',run_id:'run',status:'RUNNING'},fsm:'WAIT',interpretations:[result],answers:{}};
  ui.render(data,phases,false);
  const card=get('measurement-interpretations').children[0];
  assert.match(card.children[0].textContent,/Con imagen · Formato validado/);
  assert.match(card.children[1].textContent,/evidencia histórica/);
  ui.render({...data,answers:{Q1:{question_id:'Q1',answer:'Presencia nueva',status:'RESOLVED'}}},phases,false);
  assert.equal(get('measurement-interpretations').children[0],card);
  assert.equal(get('measurement-interpretations-empty').hidden,true);
  ui.render({...data,run:{...data.run,mode:'B'},interpretations:[]},phases,false);
  assert.equal(get('measurement-interpretations').children.length,0);
  assert.match(get('measurement-interpretations-empty').textContent,/modo B responde mediante reglas/);
});

test('reevaluar es opcional y conserva la autoridad de los endpoints experimentales',async()=>{
  const {ui,get,calls}=fixture();
  ui.render({running:true,run:{mode:'D',run_id:'run',status:'RUNNING'},fsm:'WAIT'},phases,false);
  get('measurement-question').value='Q6';
  await get('measurement-query').onclick();
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/experiments/query');
  assert.equal(JSON.parse(calls[0].options.body).question_id,'Q6');
});

test('todos los destinos de la interfaz existen una sola vez en el HTML',()=>{
  const html=fs.readFileSync('public/index.html','utf8'),script=fs.readFileSync('public/measurement.js','utf8');
  const app=fs.readFileSync('public/app.js','utf8');
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  assert.equal(new Set(ids).size,ids.length);
  for(const match of script.matchAll(/byId\('([^']+)'\)/g))assert.ok(ids.includes(match[1]),'Falta '+match[1]);
  assert.match(html,/id="measurement-answers-title"/);
  assert.match(html,/id="measurement-interpretations-title"/);
  assert.match(html,/Cada ciclo completado guarda sus respuestas/);
  assert.match(app,/measurement\.render\(d\.measurement/);
});

test('experimentación ofrece los tres guiones y prepara la medición guiada',()=>{
  const html=fs.readFileSync('public/index.html','utf8');
  const app=fs.readFileSync('public/app.js','utf8');
  assert.match(html,/id="experimentation-tab"/);
  assert.match(html,/id="experiment-scenario"/);
  assert.match(html,/S1 · Ambiente y ocupación estables/);
  assert.match(html,/S2 · Cambios de ocupación/);
  assert.match(html,/S3 · Cambios ambientales/);
  assert.match(html,/id="experiment-mode"/);
  assert.match(html,/id="experiment-repetition"/);
  assert.match(html,/Repetición 1/);
  assert.match(html,/Repetición 2/);
  assert.match(html,/Repetición 3/);
  assert.match(html,/id="experiment-start" type="button" disabled/);
  assert.match(html,/id="measurement-guidance"/);
  assert.match(html,/src="\/public\/experiment.js"/);
  assert.match(app,/scenarioSelect\.onchange=.*guide\.hidden=guide\.dataset\.scenario!==scenarioSelect\.value/);
  assert.match(app,/\$\('experimentation-tab'\)\.disabled=preparationPending/);
});

test('F muestra controles exclusivos y solo solicita fallas al backend',async()=>{
  const {ui,get,calls}=fixture();
  const data={running:true,run:{mode:'F',run_id:'run',status:'RUNNING'},fsm:'WAIT',fault_control:{disabled:['sht40'],timeouts:{},faults:[]},component_health:{sht40:{status:'STALE'}}};
  ui.render(data,phases,false);
  assert.equal(get('measurement-fault-panel').hidden,false);
  assert.equal(get('measurement-fault-switches').children.length,4);
  const button=get('measurement-fault-switches').children[0].children[1];
  assert.equal(button.textContent,'Restaurar entrada');
  await button.onclick();
  assert.equal(calls[0].url,'/api/experiments/faults');
  assert.deepEqual(JSON.parse(calls[0].options.body),{action:'availability',component:'sht40',enabled:true});
  await get('measurement-timeout-gemma').onclick();
  assert.deepEqual(JSON.parse(calls[1].options.body),{action:'timeout',lane:'gemma'});
  ui.render({...data,fault_control:{...data.fault_control,timeouts:{gemma:'ARMED'}}},phases,false);
  assert.equal(get('measurement-timeout-gemma').disabled,true);
  assert.match(get('measurement-timeout-gemma-status').textContent,/esperando una solicitud/);
  ui.render({...data,run:{...data.run,mode:'E'}},phases,false);
  assert.equal(get('measurement-fault-panel').hidden,true);
  assert.equal(button.disabled,true);
  await button.onclick();assert.equal(calls.length,2);
});

test('B guiado conserva Auto/Manual sin inventar distancia',async()=>{
  const {ui,get,calls}=fixture();
  const data={running:true,run:{mode:'B',guided:true,run_id:'run'},presence_control:{mode:'AUTO'},reactive_trigger:{state:'FAR'},context:{observations:{presence:{value:1,status:'VALID',age_seconds:1,metadata:{trigger_distance_cm:300}}}}};
  ui.render(data,phases,false);
  const control=get('measurement-presence-readings').children[0].children[4];
  assert.equal(control.hidden,false);
  await control.children[0].onclick();
  assert.deepEqual(JSON.parse(calls[0].options.body),{mode:'manual',detected:true,near:false});
  ui.render({...data,presence_control:{mode:'MANUAL',detected:true,near:false}},phases,false);
  await control.children[1].onclick();
  assert.deepEqual(JSON.parse(calls[1].options.body),{mode:'manual',detected:true});
  ui.connection(false);
  assert.equal(control.children[0].disabled,true);assert.equal(control.children[1].disabled,true);
  await control.children[1].onclick();assert.equal(calls.length,2);
});
