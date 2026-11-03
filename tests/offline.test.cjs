const {test}=require('node:test');
const assert=require('node:assert/strict');
const {frontend}=require('./frontend-fixture.cjs');

test('/offline inicia toda la UI sin fetch, SSE ni recursos externos del backend',()=>{
  const ui=frontend();
  assert.equal(ui.get('offline-banner').hidden,false);assert.match(ui.get('connection').textContent,/simulado/);
  assert.equal(ui.get('measurement-tab').disabled,false);assert.equal(ui.document.head.children.length,0);assert.equal(ui.network.length,0);
  ui.window.senseOffline.scene('loading');assert.equal(ui.get('measurement-tab').disabled,true);assert.equal(ui.get('replay-tab').disabled,false);
  ui.window.senseOffline.scene('failure');assert.equal(ui.get('measurement-fault-panel').hidden,false);
  ui.window.senseOffline.scene('missing');assert.equal(ui.get('measurement-environment-readings').children[0].children[1].textContent,'—');
});

test('ejecución guiada, pendientes, repetir, exportar e importar funcionan sin API real',async()=>{
  const ui=frontend();ui.get('experiment-start').click();
  assert.equal(ui.get('observer-dialog').open,true);
  for(const [key,value] of [['observer-name','Ana'],['observer-instrument','Demo'],['observer-power','9'],['observer-people','0']])ui.get(key).value=value;
  await ui.get('observer-form').onsubmit({preventDefault(){}});
  ui.window.senseOffline.advance();assert.equal(ui.get('observer-dialog').open,false);
  assert.equal(ui.get('measurement-pending-list').children.length,1);
  ui.get('measurement-observe').click();assert.equal(ui.get('observer-dialog').open,true);
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

test('cierre completo descarga el ZIP, bloquea la repetición y permite volver a medir sin perder el resultado',async()=>{
  const ui=frontend(),api=ui.window.senseAPI,fetchMock=api.fetch;let exports=0;
  api.fetch=(url,...args)=>{if(url.includes('/export'))exports++;return fetchMock(url,...args);};
  ui.window.senseOffline.scene('finished');
  assert.equal(exports,0);
  ui.get('measurement-observe').click();
  for(const [key,value] of [['observer-power','2.9'],['observer-people','0'],['observer-action','Terminó el guion']])ui.get(key).value=value;
  await ui.get('observer-form').onsubmit({preventDefault(){}});await ui.flush();
  assert.equal(exports,1);assert.equal(ui.get('experiment-start').disabled,true);
  assert.equal(ui.get('experiment-completed').hidden,false);
  assert.match(ui.get('experiment-download-note').textContent,/Descarga del ZIP solicitada/);
  ui.tick();assert.equal(exports,1);
  const history=await (await api.fetch('/api/experiments')).json(),old=history.completed_repetitions.find(r=>r.mode==='E');
  const body={mode:'E',guided:true,scenario_id:'S2',repetition:1,initial_observation:{power_w:2.9,visible_people:0}};
  assert.equal((await api.fetch('/api/experiments/start',{method:'POST',body:JSON.stringify(body)})).status,409);
  ui.get('experiment-remeasure').click();
  for(const [key,value] of [['observer-name','Ana'],['observer-instrument','Demo'],['observer-power','2.9'],['observer-people','0']])ui.get(key).value=value;
  await ui.get('observer-form').onsubmit({preventDefault(){}});
  let runs=await (await api.fetch('/api/experiments')).json();
  assert.equal(runs.runs[0].replaces_run_id,old.run_id);
  assert.equal(runs.completed_repetitions.find(r=>r.mode==='E').run_id,old.run_id);
  await api.fetch('/api/experiments/stop',{method:'POST'});
  runs=await (await api.fetch('/api/experiments')).json();
  assert.equal(runs.completed_repetitions.find(r=>r.mode==='E').run_id,old.run_id);
  const archive=await (await api.fetch('/api/experiments/'+old.run_id+'/export?format=csv')).blob();
  const trace=await ui.window.senseReplayData.read(archive);
  assert.equal(trace.records.at(-1).power_w,2.9);assert.equal(trace.run.finish_reason,'MAX_RUN_DURATION');
  assert.equal(ui.network.length,0);
});
