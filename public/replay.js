/* Proyección de una traza guardada: no utiliza el transporte de la ejecución. */
(() => {
  'use strict';
  const byId=id=>document.getElementById(id),data=window.senseReplayData;
  const make=(tag,value,className)=>{const node=document.createElement(tag);if(value!=null)node.textContent=String(value);if(className)node.className=className;return node;};
  const clock=value=>{const seconds=Math.max(0,Math.floor(value));return String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');};
  const names={RUN_STARTED:'Inicio de ejecución',RUN_FINISHED:'Fin de ejecución',FSM_TRANSITION:'Transición de estado',TASK_STARTED:'Tarea iniciada',TASK_COMPLETED:'Tarea completada',TASK_FAILED:'Tarea fallida',TASK_TIMEOUT:'Tiempo agotado',RESULT_PUBLISHED:'Respuestas guardadas',OBSERVER_REQUESTED:'Observación solicitada',OBSERVER_RECORDED:'Observación guardada',OBSERVER_RECORD:'Registro humano',SAMPLE_GAP:'Muestras ausentes',SLM_INPUT:'Entrada a Gemma'};
  const readingIcons={temperature_c:'temperature',humidity_pct:'humidity',aqi:'aqi',eco2_ppm_equiv:'eco2',tvoc_ppb:'tvoc',presence:'radar',visible_count:'yolo',distance_cm:'distance',cpu_percent:'cpu',ram_used_mb:'memory',process_rss_mb:'memory',pi_temp_c:'pi',vision_worker_state:'yolo',gemma_worker_state:'gemma-text'};
  const evidenceLabels={VALID:'Vigente',UNKNOWN:'Desconocido',STALE:'Vencido',CONFLICTING:'Conflicto',UNAVAILABLE:'Sin datos',ERROR:'Error'};
  let trace=null,cursor=0,timer=null,lastTick=0,selected=null,loading=0;
  let lastAnswers=null,lastTasks='',lastModels='',lastHumans='',lastPage='',lastSelected;
  function pause(){if(timer!=null)window.clearInterval(timer);timer=null;byId('replay-play').textContent='Reproducir';byId('replay-play').dataset.sprite='play';}
  function events(){return byId('replay-filter').value==='important'?trace.important:byId('replay-filter').value==='all'?trace.timeline:trace.timeline.filter(e=>e.category===byId('replay-filter').value);}
  function describe(event){const command=event.payload?.command;return (names[event.type]||event.type)+(command?' · '+(command.action==='vision'?'YOLO':'Gemma'):'');}
  function showEvents(){
    const items=events(),center=Math.max(0,data.latestIndex(items,cursor)),start=Math.max(0,center-4),page=items.slice(start,start+50);
    const pageKey=byId('replay-filter').value+':'+start;
    if(lastPage!==pageKey){lastPage=pageKey;byId('replay-event-list').replaceChildren(...page.map((event,index)=>{
      const button=make('button',clock(event.at)+' · '+describe(event));button.type='button';button.dataset.category=event.category;button.dataset.eventIndex=String(start+index);
      button.onclick=()=>{pause();selected=event;seek(event.at);};return button;
    }));}
    byId('replay-event-count').textContent=items.length?(start+1)+'–'+(start+page.length)+' de '+items.length+' eventos':'Sin eventos para este filtro.';
    const highlighted=selected&&items.includes(selected)?selected:items[center]||null,activeIndex=items.indexOf(highlighted);
    for(const button of byId('replay-event-list').children)button.setAttribute('aria-current',String(Number(button.dataset.eventIndex)===activeIndex));
    if(lastSelected!==selected){lastSelected=selected;byId('replay-event-detail').textContent=selected?JSON.stringify(selected,null,2):'Selecciona un evento para ver su registro completo.';}
  }
  function seek(value){
    if(!trace)return;cursor=Math.min(trace.duration,Math.max(0,Number(value)||0));lastTick=performance.now();
    byId('replay-seek').value=cursor;byId('replay-position').textContent=clock(cursor)+' / '+clock(trace.duration);
    const progress=(cursor/Math.max(1,trace.duration)*100).toFixed(2)+'%',seekStyle=byId('replay-seek').style;
    if(seekStyle.setProperty)seekStyle.setProperty('--replay-progress',progress);else seekStyle['--replay-progress']=progress;
    byId('replay-seek').setAttribute('aria-valuetext',clock(cursor)+' de '+clock(trace.duration));
    byId('replay-wall-time').textContent=new Date(Date.parse(trace.run.start_time)+cursor*1000).toLocaleString();
    const frame=data.frame(trace,cursor),sample=frame.sample;
    byId('replay-state').textContent=frame.state;
    byId('replay-gap').textContent=!sample?'Sin muestra todavía.':frame.gap?'Sin muestra en este segundo. Última muestra hace '+frame.sampleAge.toFixed(1)+' s; no se interpola.':'Muestra guardada · segundo '+sample.second;
    byId('replay-gap').dataset.gap=String(frame.gap);
    const groups=[['Ambiente',[['temperature_c','Temperatura','°C'],['humidity_pct','Humedad','%'],['aqi','AQI',''],['eco2_ppm_equiv','eCO₂','ppm eq.'],['tvoc_ppb','TVOC','ppb']]],['Presencia y visión',[['presence','Presencia',''],['visible_count','Conteo YOLO','personas'],['distance_cm','Distancia radar','cm']]],['Recursos',[['cpu_percent','CPU','%'],['ram_used_mb','RAM sistema','MB'],['process_rss_mb','RAM SENSE','MB'],['pi_temp_c','Temp. Pi','°C']]],['Tareas',[['vision_worker_state','Worker YOLO',''],['gemma_worker_state','Worker Gemma','']]]];
    const observationKeys={temperature_c:'temperature',humidity_pct:'humidity',aqi:'aqi',eco2_ppm_equiv:'eco2',tvoc_ppb:'tvoc',presence:'presence',visible_count:'count'};
    byId('replay-readings').replaceChildren(...groups.map(([title,readings])=>{
      const section=make('section',null,'replay-reading-group'),items=make('div',null,'replay-reading-items');
      section.append(make('h3',title));
      items.append(...readings.map(([key,label,unit])=>{
        const card=make('article',null,'card'),value=sample?.[key];card.dataset.sprite=readingIcons[key];card.append(make('span',label,'sub'),make('strong',value==null?'—':String(value)+(unit?' '+unit:'')));
        const source=observationKeys[key];if(source&&sample){const age=sample[source+'_age_s'],status=sample[source+'_status']||'UNKNOWN',meta=make('span',(evidenceLabels[status]||status)+(age==null?'':' · '+(age+frame.sampleAge).toFixed(1)+' s'),'sub replay-reading-meta');meta.dataset.status=status;card.append(meta);}
        return card;
      }));section.append(items);return section;
    }));
    if(lastAnswers!==frame.answers){lastAnswers=frame.answers;byId('replay-answers').replaceChildren(...Object.values(frame.answers).map(answer=>{
      const card=make('article',null,'card');card.append(make('h3',answer.question_id+' · '+answer.question),make('p',window.measurement.formatAnswer(answer)),make('p',(answer.status||'')+' · '+(answer.evaluated_at||''),'sub'));
      const detail=make('details');detail.append(make('summary','Evidencia guardada'),make('pre',JSON.stringify(answer,null,2)));card.append(detail);return card;
    }));}
    byId('replay-answers-empty').hidden=Object.keys(frame.answers).length>0;
    const taskKey=frame.tasks.map(e=>e.sequence).join(','),modelKey=frame.interpretations.map(e=>e.sequence).join(','),humanKey=frame.records.map(r=>r.record_id).join(',');
    if(lastTasks!==taskKey){lastTasks=taskKey;byId('replay-tasks').replaceChildren(...frame.tasks.map(event=>make('p',describe(event)+' · '+clock(event.at)+(event.payload.late?' · resultado tardío':''))));}
    if(lastModels!==modelKey){lastModels=modelKey;byId('replay-models').replaceChildren(...frame.interpretations.map(event=>{const result=event.type==='HISTORICAL_INTERPRETATION'?event.payload:event.payload.result,card=make('article',null,'card');card.append(make('strong',(result.question_id||'Gemma')+' · '+(result.validation_status||'Sin validación')),make('pre',JSON.stringify(result,null,2)));return card;}));}
    if(lastHumans!==humanKey){lastHumans=humanKey;byId('replay-human').replaceChildren(...frame.records.map(record=>{
      const card=make('article',null,'card');card.append(make('strong',clock(record.at)+' · '+(record.reason||record.kind||'Observación')));
      if(record.kind==='EXTERNAL_ENERGY')card.append(make('p',record.value+' '+record.unit+' · energía externa medida'));
      else if('power_w' in record)card.append(make('p',record.power_w==null?'W no observados':record.power_w+' W · lectura humana puntual'));
      if('visible_people' in record)card.append(make('p',record.visible_people==null?'Personas no observadas':record.visible_people+' personas observadas'));
      if(record.action)card.append(make('p',record.action));if(record.notes)card.append(make('p',record.notes,'sub'));
      const detail=make('details');detail.append(make('summary','Horas y registro original'),make('pre',JSON.stringify(record,null,2)));card.append(detail);return card;
    }));}
    byId('replay-snapshot').textContent=JSON.stringify({sample,requests:trace.requests},null,2);
    showEvents();
    if(cursor>=trace.duration)pause();
  }
  function load(next,label){
    pause();trace=next;selected=null;lastAnswers=null;lastTasks=lastModels=lastHumans=lastPage='reset';lastSelected=undefined;byId('replay-view').hidden=false;
    const runStatus={RUNNING:'En ejecución',COMPLETED:'Finalizada',FAILED:'Con error',INTERRUPTED:'Interrumpida'}[trace.run.status]||trace.run.status;
    byId('replay-title').textContent=(trace.run.simulated?'Simulación · ':'')+'Modo '+trace.run.mode+' · '+(trace.run.scenario_id||'Sin escenario')+' · '+runStatus;
    byId('replay-file-note').textContent=label+' · '+trace.samples.length+' muestras · '+trace.events.length+' eventos · '+trace.records.length+' registros humanos'+(trace.legacy?' · ZIP anterior, compatible sin manifiesto.':'.');
    byId('replay-seek').max=trace.duration;byId('replay-filter').value='important';
    byId('replay-scale').replaceChildren(...[0,.5,1].map(fraction=>make('span',clock(trace.duration*fraction))));
    const markers=trace.important,bins=new Map();
    for(const event of markers)bins.set(event.category+':'+Math.floor(event.at/Math.max(1,trace.duration)*200),event);
    byId('replay-markers').replaceChildren(...[...bins.values()].map(event=>{const marker=make('span');marker.dataset.category=event.category;marker.style.left=(event.at/Math.max(1,trace.duration)*100)+'%';return marker;}));
    const categoryNames={tasks:'Tareas',faults:'Fallas',observer:'Observaciones',state:'Estados',context:'Contexto'};
    byId('replay-legend').replaceChildren(...Object.keys(categoryNames).filter(category=>[...bins.values()].some(event=>event.category===category)).map(category=>{const item=make('span',categoryNames[category],'replay-legend-item');item.dataset.category=category;return item;}));
    seek(0);
  }
  byId('replay-file').onchange=async()=>{
    const file=byId('replay-file').files[0];if(!file)return;
    const token=++loading;pause();byId('replay-error').textContent='';byId('replay-file-note').textContent='Leyendo ZIP local…';
    try{const imported=await data.read(file);if(token===loading)load(imported,file.name);}
    catch(error){if(token===loading){byId('replay-error').textContent='No se pudo importar: '+error.message;byId('replay-file-note').textContent=trace?'Se conserva la traza anterior.':'Selecciona un ZIP exportado por SENSE.';}}
    finally{byId('replay-file').value='';}
  };
  byId('replay-seek').oninput=event=>{selected=null;seek(event.target.value);};
  byId('replay-play').onclick=()=>{
    if(!trace)return;if(timer!=null){pause();return;}if(cursor>=trace.duration)seek(0);
    selected=null;lastTick=performance.now();byId('replay-play').textContent='Pausar';byId('replay-play').dataset.sprite='pause';
    timer=window.setInterval(()=>{const now=performance.now(),next=cursor+(now-lastTick)/1000*Number(byId('replay-speed').value);seek(next);},150);
  };
  byId('replay-prev').onclick=()=>{if(!trace)return;pause();const index=data.latestIndex(trace.important,cursor-.001);selected=trace.important[index]||null;seek(selected?.at||0);};
  byId('replay-next').onclick=()=>{if(!trace)return;pause();selected=trace.important[data.latestIndex(trace.important,cursor+.001)+1]||null;seek(selected?.at??trace.duration);};
  byId('replay-filter').onchange=()=>{if(trace)showEvents();};
  byId('replay-demo').hidden=!window.senseAPI.offline;
  byId('replay-demo').onclick=()=>load(data.prepare(window.senseOffline.demo()),'Ejemplo simulado de 30 minutos');
  window.replay={pause,load,seek};
})();
