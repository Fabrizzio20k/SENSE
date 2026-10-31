const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {frontend}=require('./frontend-fixture.cjs');

test('pestañas cambian con flechas y omiten las deshabilitadas',()=>{
  const ui=frontend(),[preparation,measurement,experimentation,replay]=ui.tabs;
  assert.equal(measurement.disabled,false);
  measurement.disabled=true;experimentation.disabled=true;
  preparation.onkeydown({key:'ArrowRight',preventDefault(){}});
  assert.equal(replay.attributes['aria-selected'],'true');
  replay.onkeydown({key:'Home',preventDefault(){}});
  assert.equal(preparation.attributes['aria-selected'],'true');
});

test('movimiento reducido y pausa manual dejan iconos estáticos',()=>{
  const source=fs.readFileSync('public/motion.js','utf8');
  for(const reduced of [false,true]){
    const root={dataset:{}},button={disabled:false,textContent:'',attributes:{},listeners:{},setAttribute(key,value){this.attributes[key]=value;},addEventListener(type,fn){this.listeners[type]=fn;}},listeners={};
    const document={documentElement:root,getElementById:()=>button,addEventListener(type,fn){listeners[type]=fn;}};
    const saved=new Map(),window={matchMedia:()=>({matches:reduced,addEventListener(){}}),localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)}};
    vm.runInNewContext(source,{document,window});listeners.DOMContentLoaded();
    assert.equal(root.dataset.motion,reduced?'off':'on');
    if(reduced)assert.equal(button.disabled,true);
    else{button.listeners.click();assert.equal(root.dataset.motion,'off');assert.equal(saved.get('sense-motion'),'off');}
  }
});

test('grafo offline permite ampliar, centrar y arrastrar sin Cytoscape',()=>{
  const ui=frontend(),graph=ui.get('measurement-graph');
  graph.clientWidth=900;graph.clientHeight=500;ui.get('measurement-inspection').open=true;
  ui.window.measurement.resizeGraph();
  const stage=graph.children.at(-1),initial=stage.style.transform;
  assert.match(initial,/scale\(/);assert.equal(ui.get('measurement-flow-controls').hidden,false);
  ui.get('measurement-flow-zoom-in').onclick();assert.notEqual(stage.style.transform,initial);
  ui.get('measurement-flow-reset').onclick();assert.equal(stage.style.transform,initial);
  graph.listeners.pointerdown({target:{closest:()=>null},clientX:100,clientY:100,pointerId:1});
  graph.listeners.pointermove({clientX:130,clientY:110});assert.notEqual(stage.style.transform,initial);
  graph.listeners.pointerup();
});

test('los estados del grafo se inspeccionan con teclado y selector sin alterar la FSM',()=>{
  const ui=frontend(),phases={yolo:{status:'ready'},text:{status:'ready'},vision:{status:'ready'}};
  ui.window.measurement.render({running:true,fsm:'WAIT',run:{run_id:'run',mode:'A'},cycle:{actions:[]}},phases,false);
  const node=ui.get('measurement-pipeline').children[0];
  node.onkeydown({key:'Enter',preventDefault(){}});
  assert.equal(ui.get('measurement-graph-inspector').hidden,false);
  assert.equal(ui.get('measurement-graph-picker').value,'WAIT');
  assert.match(ui.get('measurement-graph-inspector-status').textContent,/En curso/);
  assert.match(ui.get('measurement-graph-inspector-routes').textContent,/Hacia ACQUIRE/);
  ui.get('measurement-graph-picker').onchange({target:{value:'VISION'}});
  assert.equal(ui.get('measurement-graph-inspector-title').textContent,'VISION · YOLO');
  assert.equal(ui.get('measurement-pipeline').children[3].dataset.selected,'true');
  assert.equal(ui.network.length,0);
});

test('las conexiones SVG coinciden con las trece conexiones de la FSM',()=>{
  const html=fs.readFileSync('public/index.html','utf8'),source=fs.readFileSync('public/measurement.js','utf8');
  const routes=[...html.matchAll(/data-edge="([A-Z]+-[A-Z]+)"/g)].map(match=>match[1]);
  const graph=source.match(/const graphEdges=\[(.*?)\];/s)?.[1]||'';
  const edges=[...graph.matchAll(/\['([A-Z]+)','([A-Z]+)'\]/g)].map(match=>match[1]+'-'+match[2]);
  assert.equal(routes.length,13);assert.deepEqual(new Set(routes),new Set(edges));
});
