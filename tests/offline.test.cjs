const {test}=require('node:test');
const assert=require('node:assert/strict');
const {frontend}=require('./frontend-fixture.cjs');

test('/offline inicia toda la UI sin fetch, SSE ni recursos externos del backend',()=>{
  const ui=frontend();
  assert.equal(ui.get('offline-banner').hidden,false);assert.match(ui.get('connection').textContent,/simulado/);
  assert.equal(ui.get('measurement-tab').disabled,false);assert.equal(ui.document.head.children.length,0);assert.equal(ui.network.length,0);
  ui.window.senseOffline.scene('loading');assert.equal(ui.get('measurement-tab').disabled,true);assert.equal(ui.get('replay-tab').disabled,false);
  ui.window.senseOffline.scene('failure');assert.equal(ui.get('measurement-fault-panel').hidden,false);
  ui.window.senseOffline.scene('missing');assert.equal(ui.get('measurement-observations').children[2].children[1].textContent,'—');
});

test('ejecución guiada, pendientes, repetir, exportar e importar funcionan sin API real',async()=>{
  const ui=frontend();ui.get('experiment-start').click();
  assert.equal(ui.get('observer-dialog').open,true);
  for(const [key,value] of [['observer-name','Ana'],['observer-instrument','Demo'],['observer-power','9'],['observer-people','0']])ui.get(key).value=value;
  await ui.get('observer-form').onsubmit({preventDefault(){}});
  ui.window.senseOffline.advance();assert.equal(ui.get('observer-dialog').open,true);
  ui.get('observer-power-repeat').click();await ui.get('observer-form').onsubmit({preventDefault(){}});
  assert.equal(ui.get('observer-dialog').open,false);
  const history=await (await ui.window.senseAPI.fetch('/api/experiments')).json(),run=history.runs[0];
  const archive=await (await ui.window.senseAPI.fetch('/api/experiments/'+run.run_id+'/export?format=csv')).blob();
  const trace=await ui.window.senseReplayData.read(archive);
  assert.equal(trace.run.simulated,true);assert.equal(trace.records.at(-1).power_w,9);assert.equal(trace.samples.length,61);
  ui.tabs.find(t=>t.dataset.panel==='replay').click();ui.window.replay.load(trace,'Demo exportada');ui.window.replay.seek(30);
  const position=ui.get('replay-position').textContent;ui.window.senseOffline.advance();
  assert.equal(ui.get('replay-position').textContent,position);assert.equal(ui.get('observer-dialog').open,false);
  assert.match(ui.get('observer-pending-toggle').textContent,/1/);assert.equal(ui.network.length,0);
});

test('sandbox y presencia/fallas son simulados, y una ruta desconocida falla sin salir al backend',async()=>{
  const ui=frontend();await ui.get('take-photo').click();await ui.flush();
  assert.match(ui.get('draft-image').src,/^data:image\/svg/);
  ui.window.senseOffline.scene('failure');
  const response=await ui.window.senseAPI.fetch('/api/experiments/presence',{method:'POST',body:JSON.stringify({mode:'manual',detected:true})});assert.equal(response.status,202);
  ui.tick();
  const fault=await ui.window.senseAPI.fetch('/api/experiments/faults',{method:'POST',body:JSON.stringify({action:'availability',component:'camera',enabled:true})});assert.equal(fault.status,202);
  const unknown=await ui.window.senseAPI.fetch('/api/not-implemented');assert.equal(unknown.status,404);
  assert.equal(ui.network.length,0);
});
