// Additions selected from the implemented SENSE UI screenshots.
export function additionalEntries({gemma,clock,person,brackets,page}){
 const ring=(p)=>p.ring(12,12,9,2);
 const check=(p,x=6,y=10)=>p.line(x,y,x+4,y+4,2).line(x+4,y+4,x+11,y-3,2);
 const molecule=(p,mode)=>{p.line(6,8,12,15,1).line(12,15,18,8,1);p.ring(6,7,4,2).ring(18,7,4,2).ring(12,17,4,2);if(mode==='tvoc')p.rect(11,1,2,3);};
 const question=p=>{const rows=['01110','11011','00011','00110','00100','00000','00100'];rows.forEach((row,y)=>[...row].forEach((v,x)=>{if(v==='1')p.rect(7+x*2,4+y*2,2,2);}));};
 return [
 ['timer','Tiempo de ejecución','Recursos',false,0,p=>{p.ring(12,14,8,2).rect(9,1,6,2).rect(11,3,2,3).rect(18,5,3,2).line(11,13,11,8,2).rect(11,13,5,2);}],
 ['presence','Presencia observada','Lecturas',false,0,p=>{p.disk(10,6,3).rect(6,10,8,7).rect(7,17,2,5).rect(11,17,2,5);p.line(17,6,20,9,1).line(20,9,20,15,1).line(20,15,17,18,1);}],
 ['distance','Distancia del radar','Lecturas',false,0,p=>{p.box(2,8,20,10,2);for(const x of [6,10,14,18])p.rect(x,10,1,x%8===6?5:3);p.line(2,4,6,4,1).line(17,4,21,4,1).line(2,4,4,2,1).line(19,2,21,4,1);}],
 ['aqi','AQI · índice de calidad del aire','Lecturas',false,0,p=>{p.rect(3,17,4,5).rect(10,12,4,10).rect(17,6,4,16);p.rect(3,4,9,2).rect(3,7,6,2);}],
 ['tvoc','TVOC · compuestos orgánicos volátiles','Lecturas',false,0,p=>molecule(p,'tvoc')],
 ['eco2','eCO₂ estimado','Lecturas',false,0,p=>{p.line(5,12,19,12,2).ring(4,12,3,2).ring(12,12,4,2).ring(20,12,3,2);p.rect(10,3,4,2).rect(10,19,4,2);}],
 ['gemma-text','Gemma · tarea de texto','Modelos',true,1600,(p,f)=>{p.box(2,3,12,18,2).rect(5,7,6,2).rect(5,11,5,2).rect(5,15,4,2);p.line(17,7,20,12,1).line(20,12,17,17,1);p.disk(17,6,2,f>0&&f<3?'accent':'ink').disk(21,12,2,f>=3&&f<5?'accent':'ink').disk(17,18,2,f>=5?'accent':'ink');}],
 ['gemma-image','Gemma · tarea con imagen','Modelos',true,1600,(p,f)=>{p.box(2,2,20,14,2).disk(16,7,2).poly([[5,13],[9,7],[14,13]]);p.line(7,18,12,21,1).line(12,21,17,18,1);for(const [i,[x,y]]of [[7,18],[12,21],[17,18]].entries())p.disk(x,y,2,f>0&&Math.floor((f-1)/2)%3===i?'accent':'ink');}],
 ['changes','Cambios ambientales','Preguntas',false,0,p=>{p.rect(3,16,4,6).rect(10,11,4,11).rect(17,5,4,17);p.line(2,9,7,4,2).line(3,4,7,4,2).line(7,4,7,8,2);}],
 ['evidence','Suficiencia de evidencia','Preguntas',false,0,p=>{page(p);p.rect(7,10,11,8,null);check(p,7,12);}],
 ['context','Relación contextual','Preguntas',false,0,p=>{p.box(1,4,9,10,2).box(14,10,9,10,2).line(8,8,16,16,2);}],
 ['image','Imagen y descripción visual','Preguntas',false,0,p=>{p.box(2,3,20,18,2).disk(16,8,2).poly([[4,19],[9,11],[13,16],[16,13],[20,19]]);}],
 ['tasks','Tareas y cola de trabajo','Secciones',true,1600,(p,f)=>{for(let i=0;i<3;i++){p.box(2,3+i*7,4,4,1).rect(9,4+i*7,12,2);if(f>0&&(f-1)%3===i)p.rect(9,4+i*7,4,2,'accent');}}],
 ['pending','Observaciones pendientes','Estados',false,0,p=>{p.box(3,2,15,19,2).rect(7,6,7,2).rect(7,10,5,2);p.disk(17,17,6).disk(17,17,4,null).rect(16,13,2,5).rect(16,17,4,2);}],
 ['history','Historial de ejecuciones','Secciones',false,0,p=>{clock(p);p.rect(1,1,10,8,null).line(2,3,2,9,2).line(2,9,8,9,2).line(3,7,7,3,2);}],
 ['health','Salud de componentes','Secciones',false,0,p=>{p.poly([[7,2],[17,2],[22,7],[22,17],[17,22],[7,22],[2,17],[2,7]]).poly([[8,4],[16,4],[20,8],[20,16],[16,20],[8,20],[4,16],[4,8]],null);p.rect(10,7,4,10).rect(7,10,10,4);}],
 ['diagnostic','Diagnóstico técnico','Secciones',false,0,p=>{p.poly([[3,2],[7,2],[7,7],[11,7],[11,2],[15,2],[15,9],[12,12],[20,20],[18,22],[9,13],[5,13],[2,10],[2,3]]);}],
 ['telemetry','Telemetría recibida','Secciones',true,1600,(p,f)=>{p.box(1,6,6,12,2).box(17,6,6,12,2).rect(7,11,10,2);p.rect(3,8,2,2,null).rect(19,14,2,2,null);if(f>0)p.rect(7+(f%7),10,2,4,'accent');}],
 ['play','Reproducir','Replay',false,0,p=>p.poly([[6,3],[21,12],[6,21]])],
 ['pause','Pausar','Replay',false,0,p=>p.rect(5,3,5,18).rect(14,3,5,18)],
 ['stop','Finalizar o detener','Acciones',false,0,p=>p.rect(4,4,16,16)],
 ['previous','Hito anterior','Replay',false,0,p=>p.rect(3,4,3,16).poly([[20,3],[7,12],[20,21]])],
 ['next','Hito siguiente','Replay',false,0,p=>p.rect(18,4,3,16).poly([[4,3],[17,12],[4,21]])],
 ['refresh','Reevaluar o reiniciar','Acciones',true,1600,(p,f)=>{ring(p);p.rect(1,1,12,6,null).line(3,2,3,8,2).line(3,8,9,8,2);const pts=[[15,3],[19,6],[20,11],[18,17],[12,20],[6,17],[3,12]];if(f>0)p.rect(...pts[f-1],2,2,'accent');}],
 ['upload','Importar ZIP local','Replay',true,1600,(p,f)=>{p.box(2,16,20,6,2).rect(11,3,2,12).line(6,8,11,3,2).line(11,3,16,8,2);if(f>0)p.rect(11,16-f,2,2,'accent');}],
 ['filter','Filtrar eventos','Replay',false,0,p=>{p.poly([[2,3],[22,3],[14,12],[14,20],[10,22],[10,12]]).poly([[6,5],[18,5],[12,11]],null);}],
 ['event','Registrar evento real','Observación',false,0,p=>{p.rect(5,2,2,21).poly([[7,3],[20,3],[17,7],[20,11],[7,11]]);}],
 ['observer','Observador y registro humano','Observación',false,0,p=>{p.disk(8,6,3).rect(3,10,10,9).rect(14,7,8,15).rect(16,10,4,2,null).rect(16,14,4,2,null).rect(16,18,3,2,null);}],
 ['quality','Calidad y cobertura del registro','Secciones',false,0,p=>{p.poly([[3,3],[12,1],[21,3],[21,14],[18,19],[12,23],[6,19],[3,14]]).poly([[5,5],[12,3],[19,5],[19,13],[16,17],[12,20],[8,17],[5,13]],null).rect(7,11,2,4).rect(11,8,2,7).rect(15,6,2,9);}],
 ['stale','Evidencia vencida','Estados',false,0,p=>{p.ring(10,11,8,2).rect(9,6,2,6).rect(10,10,4,2).rect(19,12,2,6).rect(19,20,2,2);}],
 ['unknown','Dato desconocido','Estados',false,0,question],
 ['conflict','Evidencia en conflicto','Estados',false,0,p=>{p.line(2,7,18,7,2).line(14,3,18,7,2).line(18,7,14,11,2);p.line(4,16,21,16,2).line(4,16,8,12,2).line(4,16,8,20,2);}],
 ['error','Error o fallo','Estados',false,0,p=>{p.poly([[7,2],[17,2],[22,7],[22,17],[17,22],[7,22],[2,17],[2,7]]).poly([[8,4],[16,4],[20,8],[20,16],[16,20],[8,20],[4,16],[4,8]],null).line(7,7,15,15,2).line(7,15,15,7,2);}],
 ['check','Operación confirmada','Estados',false,0,p=>check(p,4,11)],
 ['theme-light','Tema claro','Apariencia',false,0,p=>{p.ring(12,12,5,2);for(const [x,y]of [[11,1],[11,20],[1,11],[20,11],[3,3],[18,3],[3,18],[18,18]])p.rect(x,y,3,3);}],
 ['theme-dark','Tema oscuro','Apariencia',false,0,p=>{p.disk(12,12,10).disk(17,7,9,null);}],
 ];
}
