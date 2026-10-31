const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {frontend}=require('./frontend-fixture.cjs');

test('CPU y RAM usan dos decimales en Preparación y Medición sin convertir desconocidos en cero',()=>{
  const ui=frontend();let publish;
  ui.window.senseAPI.subscribe=callback=>{publish=callback;return ()=>{};};
  vm.runInContext(fs.readFileSync('public/app.js','utf8'),ui.context);
  const payload={system:{cpu_percent:10.1234567,memory_percent:42.3,memory_used_mb:1024.98765},phases:{yolo:{status:'error'},text:{status:'ready'},vision:{status:'ready'}},sandbox:{ready:false,busy:false},tasks:{},measurement:{running:true,reserved:true,run:{run_id:'run',mode:'C',status:'RUNNING'},resources:{cpu_total_percent:17.987654,ram_used_mb:2048,main:{rss_mb:123.456789}}}};
  publish(payload);
  assert.equal(ui.get('cpu').textContent,'10.12 %');
  assert.equal(ui.get('memory').textContent,'42.30 %');
  assert.equal(ui.get('memory-detail').textContent,'1024.99 MB en uso');
  assert.equal(ui.get('measurement-cpu').textContent,'17.99 %');
  assert.equal(ui.get('measurement-ram').textContent,'2048.00 MB');
  assert.equal(ui.get('measurement-rss').textContent,'123.46 MB');
  assert.equal(payload.system.cpu_percent,10.1234567,'El formato no altera los datos originales');
  publish({...payload,system:{cpu_percent:null,memory_percent:0,memory_used_mb:0},measurement:{...payload.measurement,resources:{cpu_total_percent:null,ram_used_mb:null,main:{rss_mb:0}}}});
  assert.equal(ui.get('cpu').textContent,'—');
  assert.equal(ui.get('memory').textContent,'0.00 %');
  assert.equal(ui.get('measurement-cpu').textContent,'—');
  assert.equal(ui.get('measurement-ram').textContent,'—');
  assert.equal(ui.get('measurement-rss').textContent,'0.00 MB');
});

test('Replay presenta CPU y RAM con el mismo formato',()=>{
  const ui=frontend();ui.get('replay-demo').click();ui.window.replay.seek(0);
  const resources=ui.get('replay-readings').children[2].children[1].children;
  assert.equal(resources[0].children[1].textContent,'20.00 %');
  assert.equal(resources[1].children[1].textContent,'3300.00 MB');
  assert.equal(resources[2].children[1].textContent,'650.00 MB');
});
