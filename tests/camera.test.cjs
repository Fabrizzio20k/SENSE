const {test}=require('node:test');
const assert=require('node:assert/strict');
const {frontend}=require('./frontend-fixture.cjs');

test('el ajuste viaja por las cuatro pestañas, previsualiza sin modelos y congela la ejecución',async()=>{
  const ui=frontend();
  await ui.get('camera-preview').click();
  assert.equal(ui.get('camera-preview-frame').hidden,false);
  assert.match(ui.get('camera-status').textContent,/simulada/);
  ui.get('camera-rotation').value='90';ui.get('camera-rotation').onchange();
  assert.equal(ui.get('camera-image').style.transform,'rotate(90deg)');
  await ui.get('camera-apply').click();
  assert.equal(ui.get('camera-current').textContent,'90°');
  for(const tab of ui.tabs){tab.click();assert.equal(ui.get('camera-setup').parent,ui.get(tab.dataset.panel+'-camera'));}
  const response=await ui.window.senseAPI.fetch('/api/experiments/start',{method:'POST',body:JSON.stringify({mode:'A'})});
  const {run_id}=await response.json();
  assert.equal(ui.get('camera-preview').disabled,true);assert.equal(ui.get('camera-rotation').disabled,true);
  assert.equal((await (await ui.window.senseAPI.fetch('/api/experiments/'+run_id)).json()).run.camera_rotation_degrees,90);
  assert.equal((await ui.window.senseAPI.fetch('/api/camera',{method:'POST',body:JSON.stringify({rotation_degrees:0})})).status,409);
  assert.equal(ui.network.length,0);
});

test('replay muestra fotos guardadas sin un segundo giro y no revela capturas futuras',()=>{
  const ui=frontend(),source=ui.window.senseOffline.demo();
  source.run.camera_rotation_degrees=90;
  source.events=[{sequence:1,timestamp:'2026-10-27T12:00:02Z',type:'TASK_COMPLETED',payload:{command:{command_id:'test',action:'vision'},result:{image_id:'test-photo',camera_rotation_degrees:90,captured_at:'2026-10-27T12:00:01Z'}}}];
  source.images={'images/test-photo.jpg':new Uint8Array([255,216,255,217])};
  ui.window.replay.load(ui.window.senseReplayData.prepare(source),'Foto de prueba');
  assert.equal(ui.get('replay-photo').hidden,true);
  ui.window.replay.seek(2);assert.equal(ui.get('replay-photo').hidden,false);
  assert.match(ui.get('replay-camera-orientation').textContent,/90°/);
  assert.equal(ui.get('replay-photo').style.transform,undefined);
  ui.window.replay.seek(0);assert.equal(ui.get('replay-photo').hidden,true);
});
