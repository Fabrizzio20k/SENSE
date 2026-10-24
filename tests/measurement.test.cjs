const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.textContent='';this.value='';this.disabled=false;this.dataset={};this.attributes={};this.className='';this.classList={toggle:()=>{}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(){}
  get options(){return this.children;}
}
function fixture(){
  const elements=new Map();
  const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:tag=>new Element(tag)};
  const calls=[];
  const context={document,window:{},fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({run_id:'run',runs:[]})};},console};
  vm.runInNewContext(fs.readFileSync('public/measurement.js','utf8'),context);
  return {ui:context.window.measurement,get:id=>document.getElementById(id),calls};
}
const phases={yolo:{status:'ready'},text:{status:'ready'},vision:{status:'ready'}};

test('selector A–E y pipeline gobernados por el backend',async()=>{
  const {ui,get,calls}=fixture();
  assert.equal(get('measurement-mode').options.length,5);
  assert.equal(get('measurement-pipeline').children.length,6);
  ui.render({running:false,enabled_modes:['A','B','C','D','E']},phases,false);
  assert.equal(get('measurement-toggle').disabled,false);
  get('measurement-mode').value='E';
  await get('measurement-toggle').onclick();
  assert.equal(calls[0].url,'/api/experiments/start');
  assert.equal(JSON.parse(calls[0].options.body).mode,'E');
  ui.render({running:true,reserved:true,fsm:'VISION',run:{run_id:'run',mode:'E',status:'RUNNING'},cycle:{actions:['ACQUIRE','ASSESS','VISION']}},phases,false);
  assert.equal(get('measurement-pipeline').children[3].className,'pipeline-node active');
  assert.equal(get('measurement-toggle').textContent,'Finalizar');
  await get('measurement-toggle').onclick();
  assert.equal(calls[1].url,'/api/experiments/stop');
});

test('desconocido conserva ausencia de valor, y cero es un conteo válido',()=>{
  const {ui,get}=fixture();
  ui.render({context:{observations:{count:{value:0,status:'VALID',age_seconds:1,region:'camera_view'},presence:{value:null,status:'UNAVAILABLE',age_seconds:1,region:'radar'}}}},phases,false);
  const cards=get('measurement-observations').children;
  assert.equal(cards[0].children[1].textContent,'—');
  assert.equal(cards[1].children[1].textContent,'0');
});

test('al perder conexión bloquea comandos; el sandbox activo bloquea comenzar',()=>{
  const {ui,get}=fixture();
  ui.render({running:false},phases,true);
  assert.equal(get('measurement-toggle').disabled,true);
  ui.render({running:false},phases,false);
  ui.connection(false);
  assert.equal(get('measurement-toggle').disabled,true);
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
