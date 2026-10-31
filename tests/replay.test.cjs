const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {frontend}=require('./frontend-fixture.cjs');

function library(){const context={window:{},TextEncoder,TextDecoder,Blob,DecompressionStream};vm.runInNewContext(fs.readFileSync('public/replay-data.js','utf8'),context);return context.window.senseReplayData;}
const start='2026-10-27T12:00:00Z',at=second=>new Date(Date.parse(start)+second*1000).toISOString();
function source(){return {run:{run_id:'12345',mode:'E',status:'COMPLETED',start_time:start,duration_seconds:30,elapsed_s:30},samples:[{second:0,elapsed_s:0,visible_count:0,presence:0,fsm_state:'WAIT'},{second:2,elapsed_s:2,visible_count:3,presence:1,fsm_state:'VISION'}],events:[{sequence:1,type:'RESULT_PUBLISHED',timestamp:at(2),payload:{answers:{Q2:{question_id:'Q2',question:'Personas',answer:3}}}},{sequence:2,type:'FSM_TRANSITION',timestamp:at(3),payload:{from:'VISION',to:'ASSESS'}},{sequence:3,type:'HISTORICAL_INTERPRETATION',timestamp:at(35),payload:{question_id:'Q7',validation_status:'VALIDATED',inferences:['Simulado']}}],records:[{run_id:'12345',record_id:'98765',kind:'OBSERVER_RECORD',power_w:0,visible_people:0,observed_at:at(1),recorded_at:at(9),notes:'=2+2\n<img src=x onerror=alert(1)>',repeated_fields:['power_w']}],requests:[]};}

test('ZIP de ida y vuelta conserva ceros, texto, campos repetidos y registros sin duplicarlos',async()=>{
  const data=library(),trace=await data.read(data.toZip(source()));
  assert.equal(trace.run.run_id,'12345');assert.equal(trace.records.length,1);assert.equal(trace.records[0].record_id,'98765');
  assert.equal(trace.records[0].power_w,0);assert.equal(trace.records[0].visible_people,0);
  assert.equal(trace.records[0].notes,source().records[0].notes);
  assert.deepEqual(Array.from(trace.records[0].repeated_fields),['power_w']);
  assert.equal(trace.duration,35);assert.equal(trace.legacy,false);
});

test('buscar hacia atrás no filtra respuestas futuras y conserva huecos, edad y resultados tardíos',()=>{
  const data=library(),trace=data.prepare(source());
  const first=data.frame(trace,0),gap=data.frame(trace,1),after=data.frame(trace,4);
  assert.equal(first.sample.visible_count,0);assert.equal(gap.gap,true);assert.equal(gap.sampleAge,1);
  assert.equal(Object.keys(gap.answers).length,0);assert.equal(after.answers.Q2.answer,3);assert.equal(after.state,'ASSESS');
  assert.equal(data.frame(trace,1).records.length,0);assert.equal(data.frame(trace,10).records.length,1);
  assert.equal(data.frame(trace,30).interpretations.length,0);assert.equal(data.frame(trace,35).interpretations.length,1);
  assert.equal(Object.keys(data.frame(trace,0).answers).length,0);
});

function legacyEntries(){return {'metadata.json':JSON.stringify(source().run),'samples_1s.csv':'second,elapsed_s,visible_count\r\n0,0,0\r\n2,2,3\r\n','events.csv':'sequence,timestamp_utc,type,payload_json\r\n1,'+at(2)+',RESULT_PUBLISHED,"{""answers"":{}}"\r\n'};}

test('importa ZIP comprimido con Rust y acepta exportaciones anteriores sin manifiesto',async()=>{
  const data=library(),entries=legacyEntries();
  const binary=fs.readFileSync(process.env.SENSE_RUST_LEGACY_ZIP);
  const trace=await data.read(new Blob([binary]));assert.equal(trace.legacy,true);assert.equal(trace.samples[0].visible_count,0);assert.equal(trace.events[0].type,'RESULT_PUBLISHED');
});

test('importa directamente el ZIP de producción con su manifiesto, JSON anidado y texto del observador',async()=>{
  const binary=fs.readFileSync(process.env.SENSE_RUST_PRODUCTION_ZIP);
  const trace=await library().read(new Blob([binary]));
  assert.equal(trace.legacy,false);assert.equal(trace.samples.length,2);assert.equal(trace.records.length,1);
  assert.equal(trace.records[0].power_w,0);assert.equal(trace.records[0].notes,source().records[0].notes);
  assert.equal(trace.byType.RESULT_PUBLISHED[0].payload.answers.Q2.answer,3);
});

test('rechaza ZIP dañados, versiones desconocidas, tamaños abusivos y CSV con cabeceras peligrosas',async()=>{
  const data=library();
  await assert.rejects(data.read(new Blob(['not zip'])),/ZIP válido/);
  await assert.rejects(data.read({size:65*1024*1024,arrayBuffer(){throw Error('No debe leerse');}}),/64 MB/);
  await assert.rejects(data.read(data.pack({...legacyEntries(),'replay-manifest.json':JSON.stringify({schema:'future',run_id:'12345'})})),/incompatible/);
  const bytes=new Uint8Array(await data.toZip(source()).arrayBuffer());bytes[45]^=1;
  await assert.rejects(data.read(new Blob([bytes])),/CRC|cabecera|dañado/);
  assert.throws(()=>data.csv('__proto__,second\nhello,0\n'),/Cabeceras/);
  assert.throws(()=>data.csv('notes\n"unterminated'),/truncado/);
  assert.throws(()=>data.prepare({...source(),samples:[...source().samples,source().samples[0]]}),/duplicadas/);
  assert.throws(()=>data.prepare({...source(),events:[{sequence:1,type:'RESULT_PUBLISHED',timestamp:at(2),payload:{answers:{Q2:null}}}]}),/Contrato/);
  assert.throws(()=>data.prepare({...source(),events:[{sequence:1,type:'RESULT_PUBLISHED',timestamp:at(2),payload:{answers:{Q3:{question_id:'Q3',question:'Ambiente',answer:{temperature:null}}}}}]}),/Contrato/);
  await assert.rejects(data.read(data.pack({...legacyEntries(),'../invalid.txt':'x'})),/rutas/);
  const inflated=new Uint8Array(await data.pack(legacyEntries()).arrayBuffer()),view=new DataView(inflated.buffer),directory=view.getUint32(inflated.length-22+16,true);
  view.setUint32(directory+24,128*1024*1024+1,true);
  await assert.rejects(data.read(new Blob([inflated])),/128 MB/);
  const entries=legacyEntries();entries['samples_1s.csv']='run_id,second,elapsed_s\nother,0,0\n';
  await assert.rejects(data.read(data.pack(entries)),/mezcla ejecuciones/);
});

test('la UI Replay recorre el ejemplo y mantiene el archivo anterior si falla otra importación',async()=>{
  const ui=frontend();ui.tabs.find(t=>t.dataset.panel==='replay').click();
  ui.get('replay-demo').click();assert.equal(ui.get('replay-view').hidden,false);assert.match(ui.get('replay-title').textContent,/Simulación/);
  ui.window.replay.seek(601);assert.match(ui.get('replay-gap').textContent,/Sin muestra/);
  ui.window.replay.seek(1026);assert.ok(ui.get('replay-models').children.length>0);
  ui.window.replay.seek(0);assert.equal(ui.get('replay-models').children.length,0);
  const title=ui.get('replay-title').textContent;ui.get('replay-file').files=[new Blob(['bad'])];
  await ui.get('replay-file').onchange();assert.match(ui.get('replay-error').textContent,/No se pudo importar/);assert.equal(ui.get('replay-title').textContent,title);
  assert.equal(ui.network.length,0);
});

test('play/pausa, velocidad y saltos funcionan y los detalles abiertos no se reinician en cada cuadro',()=>{
  const ui=frontend();ui.tabs.find(t=>t.dataset.panel==='replay').click();ui.get('replay-demo').click();
  ui.get('replay-play').click();ui.tick(1000);assert.match(ui.get('replay-position').textContent,/^00:01/);
  assert.equal(ui.get('replay-play').dataset.sprite,'pause');
  ui.get('replay-play').click();assert.equal(ui.get('replay-play').textContent,'Reproducir');
  assert.equal(ui.get('replay-play').dataset.sprite,'play');
  const stopped=ui.get('replay-position').textContent;ui.tick(1000);assert.equal(ui.get('replay-position').textContent,stopped);
  ui.get('replay-speed').value='5';ui.get('replay-play').click();ui.tick(1000);assert.match(ui.get('replay-position').textContent,/^00:06/);ui.window.replay.pause();
  ui.get('replay-next').click();assert.match(ui.get('replay-position').textContent,/^01:00/);
  ui.get('replay-prev').click();assert.match(ui.get('replay-position').textContent,/^00:05/);
  const card=ui.get('replay-answers').children[0],detail=card.children.at(-1);detail.open=true;
  ui.window.replay.seek(10);assert.equal(ui.get('replay-answers').children[0],card);assert.equal(detail.open,true);
});

test('Replay agrupa las 14 métricas y la leyenda coincide con los marcadores',()=>{
  const ui=frontend();ui.tabs.find(t=>t.dataset.panel==='replay').click();ui.get('replay-demo').click();
  assert.equal(ui.get('replay-scale').children.length,3);
  ui.window.replay.seek(902);
  assert.match(ui.get('replay-seek').style['--replay-progress'],/^49\./);
  assert.equal(ui.get('replay-event-list').children.filter(item=>item.attributes['aria-current']==='true').length,1);
  const groups=ui.get('replay-readings').children;
  assert.deepEqual(groups.map(group=>group.children[0].textContent),['Ambiente','Presencia y visión','Recursos','Tareas']);
  assert.equal(groups.reduce((sum,group)=>sum+group.children[1].children.length,0),14);
  assert.deepEqual(groups.flatMap(group=>group.children[1].children.map(card=>card.dataset.sprite)),['temperature','humidity','aqi','eco2','tvoc','radar','yolo','distance','cpu','memory','memory','pi','yolo','gemma-text']);
  const markers=new Set(ui.get('replay-markers').children.map(marker=>marker.dataset.category));
  const legend=new Set(ui.get('replay-legend').children.map(item=>item.dataset.category));
  assert.deepEqual(legend,markers);
});
