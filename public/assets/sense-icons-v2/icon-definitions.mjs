import {additionalEntries} from './additional-icons.mjs';
// SENSE original pixel icon family. Logical 24 x 24 grid.
// Drawings are deterministic SVG source assets, not crops of the mockups.
export const GRID=24;
export const COLORS={light:{ink:'#24251F',accent:'#C9F75A'},dark:{ink:'#EAE4D3',accent:'#C9F75A'}};
class Pixel {
  constructor(){this.cells=new Map();}
  dot(x,y,c='ink'){if(x>=0&&x<24&&y>=0&&y<24){const k=y*24+x;if(c)this.cells.set(k,c);else this.cells.delete(k);}return this;}
  rect(x,y,w,h,c='ink'){for(let j=y;j<y+h;j++)for(let i=x;i<x+w;i++)this.dot(i,j,c);return this;}
  box(x,y,w,h,t=2,c='ink'){return this.rect(x,y,w,t,c).rect(x,y+h-t,w,t,c).rect(x,y,t,h,c).rect(x+w-t,y,t,h,c);}
  disk(cx,cy,r,c='ink'){for(let y=0;y<24;y++)for(let x=0;x<24;x++)if((x+.5-cx)**2+(y+.5-cy)**2<=r*r)this.dot(x,y,c);return this;}
  ring(cx,cy,r,t=2,c='ink'){for(let y=0;y<24;y++)for(let x=0;x<24;x++){const d=(x+.5-cx)**2+(y+.5-cy)**2;if(d<=r*r&&d>(r-t)**2)this.dot(x,y,c);}return this;}
  line(x0,y0,x1,y1,t=2,c='ink'){let dx=Math.abs(x1-x0),sx=x0<x1?1:-1,dy=-Math.abs(y1-y0),sy=y0<y1?1:-1,err=dx+dy;for(;;){this.rect(x0,y0,t,t,c);if(x0===x1&&y0===y1)break;const e=2*err;if(e>=dy){err+=dy;x0+=sx;}if(e<=dx){err+=dx;y0+=sy;}}return this;}
  poly(points,c='ink'){for(let y=0;y<24;y++)for(let x=0;x<24;x++){let inside=false;for(let i=0,j=points.length-1;i<points.length;j=i++){const [xi,yi]=points[i],[xj,yj]=points[j];if((yi>y+.5)!==(yj>y+.5)&&(x+.5<(xj-xi)*(y+.5-yi)/(yj-yi)+xi))inside=!inside;}if(inside)this.dot(x,y,c);}return this;}
  rects(){const out=[];for(let y=0;y<24;y++){let x=0;while(x<24){const c=this.cells.get(y*24+x);if(!c){x++;continue;}const start=x++;while(x<24&&this.cells.get(y*24+x)===c)x++;out.push([start,y,x-start,1,c]);}}return out;}
}
const chip=(p)=>{p.box(4,4,16,16);for(const k of [6,10,14,18]){p.rect(k,1,2,3).rect(k,20,2,3).rect(1,k,3,2).rect(20,k,3,2);}return p;};
const person=(p)=>p.disk(12,7,2.5).rect(9,10,6,6).rect(7,11,2,4).rect(15,11,2,4).rect(9,16,2,4).rect(13,16,2,4);
const brackets=(p,c='ink',inset=2)=>{const k=inset,e=24-k;p.rect(k,k,5,2,c).rect(k,k,2,5,c).rect(e-5,k,5,2,c).rect(e-2,k,2,5,c).rect(k,e-2,5,2,c).rect(k,e-5,2,5,c).rect(e-5,e-2,5,2,c).rect(e-2,e-5,2,5,c);return p;};
const diamond=(p,cx,cy,r=3,c='ink')=>p.poly([[cx,cy-r],[cx+r,cy],[cx,cy+r],[cx-r,cy]],c);
const gemma=(p,f=0)=>{p.line(11,8,6,15,1).line(12,8,17,15,1);diamond(p,12,6,4,f>0&&f<3?'accent':'ink');diamond(p,6,17,4,f>=3&&f<5?'accent':'ink');diamond(p,18,17,4,f>=5?'accent':'ink');return p;};
const page=(p)=>p.poly([[5,2],[15,2],[20,7],[20,22],[4,22],[4,3]]).poly([[6,4],[14,4],[14,9],[18,9],[18,20],[6,20]],null).rect(8,11,8,2).rect(8,15,6,2);
const camera=(p,f=0)=>{p.poly([[3,7],[6,7],[6,5],[11,5],[13,7],[21,7],[22,8],[22,21],[2,21],[2,8]]);p.disk(12,14,5,null).ring(12,14,3,1);if(f===2||f===3)p.rect(8,12,8,4);if(f>=1&&f<=4)p.rect(18,9,2,2,'accent');else p.rect(18,9,2,2,null);return p;};
const radar=(p,f=0)=>{p.rect(2,7,5,11);for(let y=9;y<=14;y+=3)p.rect(3,y,1,1,null);const waves=[[[9,9],[11,11],[11,14],[9,16]],[[12,6],[16,10],[16,15],[12,19]],[[16,3],[21,8],[21,17],[16,22]]];waves.forEach((w,i)=>{const c=f>0&&Math.floor((f-1)/2)%3===i?'accent':'ink';for(let j=0;j<w.length-1;j++)p.line(...w[j],...w[j+1],1,c);});return p;};
const clock=(p,f=0)=>{p.ring(12,12,10,2);const hands=[[12,5],[16,7],[18,12],[16,16]];const h=hands[Math.floor(f/2)%4];p.line(11,11,...h,1).rect(11,11,5,2);return p;};
const arrowDown=(p,c='ink')=>p.rect(11,3,2,11,c).line(7,10,11,14,2,c).line(11,14,15,10,2,c);
const entries=[
 ['sht40','SHT40 · temperatura y humedad','Fuentes',false,0,p=>{chip(p);p.box(7,7,4,8,1).disk(9,15,2).rect(8,10,2,5);p.poly([[16,9],[19,14],[19,17],[16,19],[13,17],[13,14]]);}],
 ['ens160','ENS160 · calidad del aire','Fuentes',false,0,p=>{p.poly([[8,2],[16,2],[22,8],[22,16],[16,22],[8,22],[2,16],[2,8]]).poly([[9,4],[15,4],[20,9],[20,15],[15,20],[9,20],[4,15],[4,9]],null);for(const [x,y]of [[10,7],[14,7],[7,11],[11,11],[15,11],[8,15],[12,15],[16,15]])p.rect(x,y,2,2);}],
 ['radar','Radar · presencia','Fuentes',true,1600,radar],
 ['camera','Cámara · captura visual','Fuentes',true,1600,camera],
 ['yolo','YOLO · detección visual','Modelos',true,1600,(p,f)=>{person(p);brackets(p,f>0&&f<6?'accent':'ink',f===3||f===4?3:2);}],
 ['gemma','Gemma · interpretación','Modelos',true,1600,gemma],
 ['power','Vatímetro · potencia W','Fuentes',false,0,p=>{p.box(1,5,15,13,2).rect(4,9,2,6).rect(8,11,2,4).rect(12,9,2,6).rect(5,14,8,2).rect(18,8,5,8).rect(18,4,1,4).rect(22,4,1,4).rect(20,16,2,4).line(15,19,20,19,1);}],
 ['wait','WAIT · espera','Máquina',true,1600,clock],
 ['acquire','ACQUIRE · adquisición','Máquina',true,1600,(p,f)=>{arrowDown(p,f>0?'accent':'ink');p.box(4,16,16,6,2);if(f)p.rect(6+2*(f%6),18,2,2,'accent');}],
 ['assess','ASSESS · evaluación','Máquina',true,1600,(p,f)=>{p.box(9,8,6,6,2).line(11,3,11,7,2).line(4,11,8,11,2).line(15,11,19,11,2).line(11,14,11,19,2);[[10,1],[1,10],[19,10],[10,19]].forEach(([x,y],i)=>p.rect(x,y,4,4,f>0&&(f-1)%4===i?'accent':'ink'));}],
 ['vision','VISION · análisis visual','Máquina',true,1600,(p,f)=>{brackets(p);p.ring(12,12,5,2);if(f>0)p.rect(5,5+f*2,14,1,'accent');}],
 ['interpret','INTERPRET · interpretación','Máquina',true,1600,gemma],
 ['report','REPORT · publicación','Máquina',true,1600,(p,f)=>{page(p);if(f>0)p.rect(8,11,Math.min(8,f+1),2,'accent');}],
 ['degraded','DEGRADED · evidencia parcial','Máquina',true,2400,(p,f)=>{p.poly([[10,2],[14,2],[23,21],[1,21]]).poly([[11,6],[13,6],[20,19],[4,19]],null).rect(11,8,2,6).rect(11,16,2,2);if(f>=3&&f<=5)p.rect(11,16,2,2,'accent');}],
 ['preparation','Preparación','Navegación',false,0,p=>{p.box(4,2,16,20,2).rect(8,0,8,5);p.line(7,10,9,12,2).line(9,12,13,8,2).rect(8,16,8,2);}],
 ['measurement','Medición y pruebas','Navegación',false,0,p=>{p.rect(3,14,4,8).rect(10,9,4,13).rect(17,3,4,19);}],
 ['experiment','Experimentación','Navegación',false,0,p=>{p.rect(8,2,8,2).rect(9,4,2,7).rect(13,4,2,7).poly([[9,9],[15,9],[21,20],[19,22],[5,22],[3,20]]).poly([[10,11],[14,11],[18,19],[6,19]],null).rect(8,16,8,3);}],
 ['replay','Replay','Navegación',false,0,p=>{p.ring(12,12,10,2).rect(1,1,10,6,null).line(3,2,3,8,2).line(3,8,8,8,2).poly([[10,7],[17,12],[10,17]]);}],
 ['observe','Registrar observación','Acciones',false,0,p=>{p.poly([[1,11],[6,6],[18,6],[23,11],[23,13],[18,18],[6,18],[1,13]]).poly([[4,11],[7,8],[17,8],[20,11],[20,13],[17,16],[7,16],[4,13]],null).disk(12,12,3);}],
 ['save','Guardar observación','Acciones',false,0,p=>{p.poly([[3,2],[19,2],[22,5],[22,22],[2,22],[2,3]]).rect(6,3,11,6,null).rect(7,13,10,9,null).rect(13,4,2,4).rect(9,15,6,2).rect(9,19,6,2);}],
 ['export','Exportar registro','Acciones',false,0,p=>{arrowDown(p);p.rect(3,17,2,5).rect(19,17,2,5).rect(3,20,18,2);}],
 ['lock','Conteo protegido','Estados',false,0,p=>{p.box(7,2,10,12,2).rect(4,10,16,12).rect(11,14,2,4,null);}],
 ['connection','Conexión y transporte','Estados',true,1600,(p,f)=>{p.box(2,7,6,10,2).box(16,7,6,10,2).rect(8,11,8,2);if(f)p.rect(7+f,11,2,2,'accent');}],
 ['pi','Raspberry Pi','Recursos',false,0,p=>{chip(p);p.rect(8,8,3,3).rect(13,8,3,3).rect(8,13,8,3);}],
 ['cpu','CPU del sistema','Recursos',false,0,p=>{chip(p);p.box(8,8,8,8,2);}],
 ['memory','Memoria RAM','Recursos',false,0,p=>{p.box(2,6,20,12,2);for(const x of [5,10,15])p.rect(x,9,3,6);for(const x of [4,8,12,16,20])p.rect(x,18,1,3);}],
 ['temperature','Temperatura','Lecturas',false,0,p=>{p.box(9,2,6,15,2).disk(12,17,5).disk(12,17,2,null).rect(11,6,2,11);}],
 ['humidity','Humedad','Lecturas',false,0,p=>{p.poly([[11,2],[13,2],[14,6],[19,13],[20,17],[18,21],[14,23],[10,23],[6,21],[4,17],[5,13],[10,6]]).rect(7,16,2,3,null);}],
];
entries.push(...additionalEntries({gemma,clock,person,brackets,page}));
export const definitions=entries.map(([id,label,category,animated,duration,draw])=>({id,label,category,animated,duration,frames:Array.from({length:animated?8:1},(_,i)=>{const p=new Pixel();draw(p,i);return p.rects();})}));
export function markup(rects,palette={ink:'currentColor',accent:'#C9F75A'}){return rects.map(([x,y,w,h,c])=>'<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" fill="'+palette[c]+'"'+(c==='accent'?' class="sense-accent"':'')+'/>').join('');}
