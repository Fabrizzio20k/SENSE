/* ZIP local: sin subir archivos, extraer rutas ni ejecutar el contenido importado. */
(() => {
  'use strict';
  const MAX_ZIP=64*1024*1024,MAX_DATA=128*1024*1024,MAX_ROWS=200000;
  const encoder=new TextEncoder(),decoder=new TextDecoder('utf-8',{fatal:true});
  const files=['metadata.json','replay-manifest.json','samples_1s.csv','events.csv','ground_truth.csv','power_readings.csv','observer_requests.csv'];
  const crcTable=Uint32Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
  function crc(bytes){let n=0xffffffff;for(const byte of bytes)n=crcTable[(n^byte)&255]^(n>>>8);return (n^0xffffffff)>>>0;}
  function check(ok,message){if(!ok)throw Error(message);}
  function time(value){check(typeof value==='string'&&value.length<=64,'El archivo contiene una fecha inválida.');const result=Date.parse(value);check(Number.isFinite(result),'El archivo contiene una fecha inválida.');return result;}
  async function unzip(file){
    check(file.size>0&&file.size<=MAX_ZIP,'Importa un ZIP de hasta 64 MB.');
    const bytes=new Uint8Array(await file.arrayBuffer()),view=new DataView(bytes.buffer);
    let end=-1;
    for(let i=bytes.length-22;i>=Math.max(0,bytes.length-65557);i--)if(view.getUint32(i,true)===0x06054b50&&i+22+view.getUint16(i+20,true)===bytes.length){end=i;break;}
    check(end>=0,'El archivo no es un ZIP válido.');
    const count=view.getUint16(end+10,true),directory=view.getUint32(end+16,true),directorySize=view.getUint32(end+12,true);
    check(!view.getUint16(end+4,true)&&!view.getUint16(end+6,true)&&view.getUint16(end+8,true)===count,'No se admiten ZIP divididos.');
    check(count<=4096&&directory+directorySize<=end,'Directorio ZIP inválido o demasiado grande.');
    const selected=[],names=new Set();let position=directory,total=0;
    for(let i=0;i<count;i++){
      check(position+46<=directory+directorySize&&view.getUint32(position,true)===0x02014b50,'Directorio ZIP incompleto.');
      const length=view.getUint16(position+28,true),extra=view.getUint16(position+30,true),comment=view.getUint16(position+32,true),next=position+46+length+extra+comment;
      check(next<=directory+directorySize,'Entrada ZIP incompleta.');
      const name=decoder.decode(bytes.subarray(position+46,position+46+length));
      check(!names.has(name)&&!name.includes('\\')&&!name.startsWith('/')&&!name.split('/').includes('..'),'Nombres duplicados o rutas inválidas en el ZIP.');names.add(name);
      if(files.includes(name)){
        const flags=view.getUint16(position+8,true),method=view.getUint16(position+10,true),compressed=view.getUint32(position+20,true),size=view.getUint32(position+24,true),offset=view.getUint32(position+42,true);
        check(!(flags&1)&&[0,8].includes(method),'El ZIP está cifrado o usa una compresión no compatible.');
        check(size!==0xffffffff&&compressed!==0xffffffff&&offset!==0xffffffff,'ZIP64 no compatible; exporta un archivo menor.');
        total+=size;check(total<=MAX_DATA,'El contenido descomprimido supera 128 MB.');
        check(offset+30<=directory&&view.getUint32(offset,true)===0x04034b50,'Cabecera ZIP inválida.');
        const localLength=view.getUint16(offset+26,true),start=offset+30+localLength+view.getUint16(offset+28,true);
        check(start+compressed<=directory&&view.getUint16(offset+8,true)===method&&!(view.getUint16(offset+6,true)&1),'Datos ZIP incompletos.');
        check(decoder.decode(bytes.subarray(offset+30,offset+30+localLength))===name,'La entrada ZIP no coincide con su cabecera.');
        selected.push({name,method,size,compressed,start,checksum:view.getUint32(position+16,true)});
      }
      position=next;
    }
    check(position===directory+directorySize,'Tamaño del directorio ZIP inválido.');
    const output=Object.create(null);
    for(const entry of selected){
      let data=bytes.subarray(entry.start,entry.start+entry.compressed);
      if(entry.method===8){
        let decompressor;
        try{decompressor=new DecompressionStream('deflate-raw');}catch{throw Error('Este navegador no admite ZIP comprimidos. Usa una versión reciente de Chrome, Edge, Firefox o Safari.');}
        const reader=new Blob([data]).stream().pipeThrough(decompressor).getReader(),inflated=new Uint8Array(entry.size);let written=0;
        try{while(true){const {done,value}=await reader.read();if(done)break;check(written+value.length<=entry.size,'El ZIP supera su tamaño declarado.');inflated.set(value,written);written+=value.length;}}
        catch(error){await reader.cancel().catch(()=>{});throw error;}
        check(written===entry.size,'El ZIP está truncado.');data=inflated;
      }
      check(data.length===entry.size&&crc(data)===entry.checksum,'El ZIP está dañado (tamaño o CRC incorrecto).');
      output[entry.name]=decoder.decode(data).replace(/^\uFEFF/,'');
    }
    return output;
  }
  function csv(text){
    const rows=[];let row=[],cell='',quoted=false,closed=false;
    const push=()=>{row.push(cell);cell='';closed=false;check(row.length<=256,'Demasiadas columnas CSV.');};
    const end=()=>{push();rows.push(row);row=[];check(rows.length<=MAX_ROWS+1,'Demasiadas filas para Replay.');};
    for(let i=0;i<text.length;i++){
      const c=text[i];
      if(quoted){if(c==='"'){if(text[i+1]==='"'){cell+='"';i++;}else{quoted=false;closed=true;}}else cell+=c;}
      else if(c==='"'){check(!cell&&!closed,'Comillas CSV inválidas.');quoted=true;}
      else if(c===',')push();
      else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;end();}
      else{check(!closed,'Contenido después de una celda CSV entrecomillada.');cell+=c;}
      check(cell.length<=4*1024*1024,'Celda CSV demasiado grande.');
    }
    check(!quoted,'CSV truncado.');if(cell||row.length||closed)end();
    if(!rows.length)return [];
    const headers=rows.shift();check(new Set(headers).size===headers.length&&!headers.some(h=>['__proto__','constructor','prototype'].includes(h)),'Cabeceras CSV inválidas.');
    return rows.map(values=>{check(values.length===headers.length,'Cantidad de columnas CSV incorrecta.');const result=Object.create(null);headers.forEach((key,i)=>{result[key]=values[i].replace(/^'(?=[=+@-])/,'');});return result;});
  }
  const jsonFields=new Set(['component_health','gemma_processes','active_question','information_need','fault_ids','unavailable_fields','repeated_fields','fields']);
  const textFields=new Set(['notes','action','reason','observer','instrument','equipment','scope','unit','type','kind','region','status']);
  function typed(row){
    return Object.fromEntries(Object.entries(row).map(([key,value])=>{
      if(value==='')value=null;
      else if(key.endsWith('_json')||jsonFields.has(key))value=JSON.parse(value);
      else if(!textFields.has(key)&&!/(?:^|_)id$/.test(key)){
        if(/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(value)){value=Number(value);check(Number.isFinite(value),'Número no finito en CSV.');}
        else if(value==='true'||value==='false')value=value==='true';
      }
      return [key,value];
    }));
  }
  function latestIndex(items,at){let lo=0,hi=items.length;while(lo<hi){const mid=(lo+hi)>>>1;if(items[mid].at<=at)lo=mid+1;else hi=mid;}return lo-1;}
  const latest=(items,at)=>items[latestIndex(items,at)]||null;
  function category(type){return /^(OBSERVER|GROUND_TRUTH|EXTERNAL_)/.test(type)?'observer':/FAULT|COMPONENT_HEALTH/.test(type)?'faults':/^FSM_/.test(type)?'state':/TASK_|COMMAND_|VISION_|SLM_|MULTIMODAL_|TEXT_/.test(type)?'tasks':'context';}
  function prepare(source){
    const run=source.run;check(run&&typeof run==='object'&&typeof run.run_id==='string'&&run.run_id.length>0&&typeof run.mode==='string'&&'ABCDEF'.includes(run.mode)&&run.mode.length===1&&typeof run.status==='string'&&(run.scenario_id==null||typeof run.scenario_id==='string')&&(run.elapsed_s==null||Number.isFinite(run.elapsed_s)&&run.elapsed_s>=0),'Metadatos de ejecución inválidos.');
    const start=time(run.start_time),relative=value=>Math.max(0,(time(value)-start)/1000);
    const ownRun=row=>check(!row.run_id||row.run_id===run.run_id,'El ZIP mezcla ejecuciones diferentes.');
    check(source.samples.length<=MAX_ROWS&&source.events.length<=MAX_ROWS,'La traza es demasiado grande.');
    const samples=source.samples.map(row=>{
      ownRun(row);check(Number.isInteger(row.second)&&row.second>=0&&Number.isFinite(row.elapsed_s)&&row.elapsed_s>=0,'Muestra temporal inválida.');
      for(const key of ['temperature_c','humidity_pct','aqi','eco2_ppm_equiv','tvoc_ppb','presence','visible_count','distance_cm','cpu_percent','ram_used_mb','process_rss_mb','pi_temp_c'])check(row[key]==null||Number.isFinite(row[key]),'Lectura numérica inválida.');
      for(const [key,value] of Object.entries(row)){
        if(key.endsWith('_age_s'))check(value==null||Number.isFinite(value)&&value>=0,'Edad de evidencia inválida.');
        if(key.endsWith('_status')||key.endsWith('_worker_state')||key==='fsm_state')check(value==null||typeof value==='string','Estado de muestra inválido.');
      }
      return {...row,at:row.elapsed_s};
    }).sort((a,b)=>a.at-b.at);
    check(new Set(samples.map(s=>s.second)).size===samples.length,'Hay muestras duplicadas.');
    const sequences=new Set();
    const events=source.events.map(row=>{
      ownRun(row);check(Number.isInteger(row.sequence)&&!sequences.has(row.sequence)&&typeof row.type==='string'&&row.type.length>0&&row.payload&&typeof row.payload==='object'&&!Array.isArray(row.payload),'Evento inválido o duplicado.');sequences.add(row.sequence);
      if(row.type==='RESULT_PUBLISHED')check(row.payload.answers&&typeof row.payload.answers==='object'&&!Array.isArray(row.payload.answers)&&Object.values(row.payload.answers).every(a=>{
        if(!a||typeof a!=='object'||typeof a.question_id!=='string'||typeof a.question!=='string'||a.status!=null&&typeof a.status!=='string'||a.evaluated_at!=null&&typeof a.evaluated_at!=='string')return false;
        if(a.question_id==='Q3'&&a.answer&&typeof a.answer==='object'&&!Array.isArray(a.answer))return Object.values(a.answer).every(r=>r&&typeof r==='object'&&(r.value==null||Number.isFinite(r.value))&&(r.unit==null||typeof r.unit==='string')&&(r.status==null||typeof r.status==='string'));
        if(a.question_id==='Q4'&&Array.isArray(a.answer))return a.answer.every(e=>e&&typeof e==='object'&&typeof e.event_type==='string');
        return true;
      }),'Contrato de respuestas inválido.');
      return {...row,at:relative(row.timestamp),category:category(row.type)};
    }).sort((a,b)=>a.at-b.at||a.sequence-b.sequence);
    const records=source.records.map(row=>{ownRun(row);return {...row,at:relative(row.recorded_at||row.observed_at),category:'observer',type:row.kind||'OBSERVER_RECORD',payload:row};}).sort((a,b)=>a.at-b.at);
    const byType=Object.create(null),tasks=new Map();
    for(const event of events){(byType[event.type]??=[]).push(event);const id=event.payload.command?.command_id||event.payload.command_id;if(id&&/^TASK_/.test(event.type)){if(!tasks.has(id))tasks.set(id,[]);tasks.get(id).push(event);}}
    const duration=Math.max(0,Number(run.elapsed_s)||0,samples.at(-1)?.at||0,events.at(-1)?.at||0,records.at(-1)?.at||0);
    const timeline=[...events,...records].sort((a,b)=>a.at-b.at||(a.sequence||0)-(b.sequence||0));
    const important=timeline.filter(e=>e.category==='observer'||/^(RUN_|FSM_|TASK_|FAULT_|SAMPLE_GAP|COMPONENT_HEALTH|RESULT_PUBLISHED|HISTORICAL_INTERPRETATION)/.test(e.type));
    const seenInterpretations=new Set();
    const interpretationEvents=events.filter(e=>{
      if(!((/^TASK_/.test(e.type)&&e.payload.command?.target_agent==='InterpretationAgent'&&e.payload.result)||e.type==='HISTORICAL_INTERPRETATION'))return false;
      const key=(e.type==='HISTORICAL_INTERPRETATION'?e.payload:e.payload.result).interpretation_id||e.sequence;
      if(seenInterpretations.has(key))return false;seenInterpretations.add(key);return true;
    });
    return {run,samples,events,records,requests:source.requests||[],duration,byType,tasks,timeline,important,interpretationEvents,legacy:!!source.legacy};
  }
  async function read(file){
    const entries=await unzip(file);
    for(const name of ['metadata.json','events.csv','samples_1s.csv'])check(entries[name]!=null,'Falta '+name+' en el ZIP de SENSE.');
    const run=JSON.parse(entries['metadata.json']);
    if(entries['replay-manifest.json']){const manifest=JSON.parse(entries['replay-manifest.json']);check(manifest.schema==='sense-replay.v1'&&manifest.run_id===run.run_id,'Versión o ejecución del manifiesto incompatible.');}
    const parse=name=>entries[name]?csv(entries[name]).map(typed):[];
    const humans=new Map();
    for(const row of [...parse('ground_truth.csv'),...parse('power_readings.csv')]){check(!row.run_id||row.run_id===run.run_id,'El ZIP mezcla ejecuciones diferentes.');check(typeof row.record_id==='string','Registro humano sin identificador.');const record=humans.get(row.record_id)||{};for(const [key,value] of Object.entries(row))if(value!=null||record[key]==null)record[key]=value;humans.set(row.record_id,record);}
    return prepare({run,samples:parse('samples_1s.csv'),events:parse('events.csv').map(row=>({...row,timestamp:row.timestamp_utc,payload:row.payload_json})),records:[...humans.values()],requests:parse('observer_requests.csv'),legacy:!entries['replay-manifest.json']});
  }
  function frame(trace,at){
    const sample=latest(trace.samples,at),transition=latest(trace.byType.FSM_TRANSITION||[],at),result=latest(trace.byType.RESULT_PUBLISHED||[],at);
    const taskEvents=[...trace.tasks.values()].map(items=>latest(items,at)).filter(Boolean).sort((a,b)=>b.at-a.at);
    const interpretationEnd=latestIndex(trace.interpretationEvents,at)+1,recordEnd=latestIndex(trace.records,at)+1;
    const interpretations=trace.interpretationEvents.slice(Math.max(0,interpretationEnd-10),interpretationEnd);
    return {sample,gap:!sample||Math.floor(sample.at)!==Math.floor(at),sampleAge:sample?Math.max(0,at-sample.at):null,
      state:transition&&(!sample||transition.at>=sample.at)?transition.payload.to:sample?.fsm_state||'WAIT',answers:result?.payload.answers||{},
      tasks:taskEvents.slice(0,12),interpretations,records:trace.records.slice(Math.max(0,recordEnd-10),recordEnd)};
  }
  function csvText(rows,fields){
    const cell=value=>{if(value==null)return '';let text=typeof value==='object'?JSON.stringify(value):String(value);if(typeof value==='string'&&/^[\s]*[=+@-]/.test(text))text="'"+text;return /[",\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;};
    return '\uFEFF'+[fields.map(cell).join(','),...rows.map(row=>fields.map(key=>cell(row[key])).join(','))].join('\r\n')+'\r\n';
  }
  function pack(entries){
    const chunks=[],directory=[];let offset=0,total=0;
    for(const [name,text] of Object.entries(entries)){
      const filename=encoder.encode(name),data=encoder.encode(text),checksum=crc(data),local=new Uint8Array(30+filename.length),lv=new DataView(local.buffer),central=new Uint8Array(46+filename.length),cv=new DataView(central.buffer);
      total+=data.length;check(total<=MAX_ZIP-65536,'El ZIP simulado supera 64 MB.');
      lv.setUint32(0,0x04034b50,true);lv.setUint16(4,20,true);lv.setUint16(10,0,true);lv.setUint16(12,33,true);lv.setUint32(14,checksum,true);lv.setUint32(18,data.length,true);lv.setUint32(22,data.length,true);lv.setUint16(26,filename.length,true);local.set(filename,30);
      cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(14,33,true);cv.setUint32(16,checksum,true);cv.setUint32(20,data.length,true);cv.setUint32(24,data.length,true);cv.setUint16(28,filename.length,true);cv.setUint32(42,offset,true);central.set(filename,46);
      chunks.push(local,data);directory.push(central);offset+=local.length+data.length;
    }
    const length=directory.reduce((n,item)=>n+item.length,0),end=new Uint8Array(22),ev=new DataView(end.buffer);
    ev.setUint32(0,0x06054b50,true);ev.setUint16(8,directory.length,true);ev.setUint16(10,directory.length,true);ev.setUint32(12,length,true);ev.setUint32(16,offset,true);
    return new Blob([...chunks,...directory,end],{type:'application/zip'});
  }
  function toZip(trace){
    const run=trace.run,entries={'metadata.json':JSON.stringify({...run,exported_samples:trace.samples.length}),
      'replay-manifest.json':JSON.stringify({schema:'sense-replay.v1',run_id:run.run_id,files:files.filter(name=>name!=='replay-manifest.json'),images_stored:false})};
    const rows={
      'samples_1s.csv':trace.samples,
      'events.csv':trace.events.map(e=>({run_id:run.run_id,sequence:e.sequence,timestamp_utc:e.timestamp,recorded_at:e.recorded_at||e.timestamp,type:e.type,payload_json:e.payload})),
      'ground_truth.csv':trace.records.filter(r=>r.visible_people!=null||r.action||r.kind==='GROUND_TRUTH'),
      'power_readings.csv':trace.records.filter(r=>r.power_w!=null||r.unavailable_fields?.includes('power_w')||/^EXTERNAL_/.test(r.kind)),
      'observer_requests.csv':trace.requests||[]
    };
    const defaults={'samples_1s.csv':['second','elapsed_s'],'events.csv':['sequence','timestamp_utc','type','payload_json'],'ground_truth.csv':['record_id'],'power_readings.csv':['record_id'],'observer_requests.csv':['request_id']};
    for(const [name,values] of Object.entries(rows))entries[name]=csvText(values,[...new Set([...defaults[name],...values.flatMap(Object.keys)])].filter(k=>!['at','category','payload'].includes(k)));
    entries['LEEME.txt']='Datos simulados de /offline. No son mediciones físicas. Importa este ZIP en Replay.';
    return pack(entries);
  }
  window.senseReplayData={read,prepare,frame,latestIndex,pack,toZip,csv};
})();
