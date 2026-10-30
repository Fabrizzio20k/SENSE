const fs=require('node:fs');
const vm=require('node:vm');

function frontend(){
  const html=fs.readFileSync('public/index.html','utf8'),elements=new Map(),intervals=new Map(),timeouts=[],network=[];
  let now=0,serial=0;
  class Element{
    constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.open=false;this.style={};this.files=[];this.listeners={};this.classList={toggle(){},add(){},remove(){}};}
    append(...nodes){for(const node of nodes){if(node.parent)node.parent.children=node.parent.children.filter(n=>n!==node);node.parent=this;this.children.push(node);}}
    replaceChildren(...nodes){this.children=[];this.append(...nodes);}
    setAttribute(key,value){this.attributes[key]=String(value);}
    removeAttribute(key){delete this.attributes[key];}
    addEventListener(type,fn){this.listeners[type]=fn;}
    get options(){return this.children;}
    showModal(){this.open=true;}
    close(){this.open=false;}
    reportValidity(){return true;}
    scrollIntoView(){}
    focus(){}
    click(){return this.onclick?.({preventDefault(){},target:this});}
    reset(){for(const [id,node] of elements)if(id.startsWith('observer-')){node.value='';node.checked=false;}}
  }
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  for(const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
    const node=get(match[3]);node.tagName=match[1];node.hidden=/\bhidden\b/.test(match[2]);node.disabled=/\bdisabled\b/.test(match[2]);node.open=/\bopen\b/.test(match[2]);
    const value=match[2].match(/\bvalue="([^"]*)"/);if(value)node.value=value[1];
  }
  for(const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>(.*?)<\/select>/gs)){
    const select=get(match[1]);for(const option of match[2].matchAll(/<option\b[^>]*value="([^"]+)"[^>]*>(.*?)<\/option>/gs)){const node=new Element('option');node.value=option[1];node.textContent=option[2];select.append(node);}select.value=select.options[0]?.value||'';
  }
  const tabs=[...html.matchAll(/<button\b([^>]*\bclass="tab"[^>]*)>/g)].map(match=>{const panel=match[1].match(/data-panel="([^"]+)"/)[1],id=match[1].match(/\bid="([^"]+)"/),node=id?get(id[1]):new Element('button');node.dataset.panel=panel;return node;});
  const guides=['S1','S2','S3'].map(s=>Object.assign(new Element(),{dataset:{scenario:s}})),listeners={};
  const document={documentElement:{dataset:{}},head:new Element('head'),getElementById:get,createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='.tab'?tabs:selector==='.panel'?['preparation','measurement','experimentation','replay'].map(get):selector==='.experiment-guide'?guides:[],addEventListener(type,fn){(listeners[type]??=[]).push(fn);},dispatchEvent(event){for(const listener of listeners[event.type]||[])listener(event);}};
  get('measurement').append(get('measurement-workspace'));
  const window={location:{pathname:'/offline'},matchMedia:()=>({matches:false,addEventListener(){}}),setInterval(fn){const key=++serial;intervals.set(key,fn);return key;},clearInterval(key){intervals.delete(key);},setTimeout(fn){timeouts.push(fn);return ++serial;}};
  const context=vm.createContext({window,document,console,TextEncoder,TextDecoder,Blob,Response,URL,DecompressionStream,structuredClone,performance:{now:()=>now},Event,requestAnimationFrame:fn=>fn(),setTimeout:window.setTimeout,fetch(...args){network.push(args);throw Error('Unexpected real fetch');},EventSource:class{constructor(){throw Error('Unexpected real SSE');}}});
  for(const name of ['api.js','replay-data.js','offline.js','measurement.js','experiment.js','replay.js','app.js'])vm.runInContext(fs.readFileSync('public/'+name,'utf8'),context,{filename:name});
  return {get,window,document,network,context,tabs,async flush(){while(timeouts.length)timeouts.shift()();await new Promise(setImmediate);},tick(ms=1000){now+=ms;for(const fn of [...intervals.values()])fn();}};
}
module.exports={frontend};
