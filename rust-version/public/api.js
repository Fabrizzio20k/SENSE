/* Único punto de acceso al backend; /offline instala un transporte local. */
(() => {
  'use strict';
  const offline=/^\/offline\/?$/.test(window.location.pathname);
  const api=window.senseAPI={offline,
    fetch:(...args)=>offline?window.senseOffline.fetch(...args):fetch(...args),
    subscribe(message,error){
      if(offline)return window.senseOffline.subscribe(message);
      const stream=new EventSource('/events');
      stream.onmessage=event=>message(JSON.parse(event.data));stream.onerror=error;
      return ()=>stream.close();
    },
    captureURL:()=>offline?window.senseOffline.captureURL:'/api/capture?t='+Date.now(),
    setExportLink(link,runId,format='csv'){
      const url='/api/experiments/'+encodeURIComponent(runId)+'/export'+(format==='csv'?'?format=csv':'');
      link.href=offline?'#':url;
      link.onclick=offline?async event=>{
        event.preventDefault();
        const response=await api.fetch(url),blob=await response.blob(),href=URL.createObjectURL(blob),anchor=document.createElement('a');
        anchor.href=href;anchor.download='sense-demo-'+runId+(format==='csv'?'.zip':'.ndjson');
        anchor.click();setTimeout(()=>URL.revokeObjectURL(href),1000);
      }:null;
    }
  };
})();
