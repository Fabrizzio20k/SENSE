const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function fixture({saved=null,dark=false,blocked=false}={}){
  const listeners={},events=[],writes=[];
  const button={textContent:'',setAttribute(key,value){this[key]=value;}};
  const system={matches:dark,addEventListener(type,fn){this.changed=fn;}};
  const document={documentElement:{dataset:{}},getElementById:()=>button,
    addEventListener(type,fn){listeners[type]=fn;},dispatchEvent(event){events.push(event.type);}};
  const localStorage={getItem(){if(blocked)throw Error('Blocked');return saved;},setItem(key,value){if(blocked)throw Error('Blocked');writes.push([key,value]);}};
  vm.runInNewContext(fs.readFileSync('public/theme.js','utf8'),{document,window:{matchMedia:()=>system},localStorage,Event:class{constructor(type){this.type=type;}}});
  listeners.DOMContentLoaded();
  return {document,button,system,events,writes};
}

test('sigue el tema del sistema hasta que el usuario elige otro',()=>{
  const {document,button,system,writes,events}=fixture();
  assert.equal(document.documentElement.dataset.theme,'light');
  system.matches=true;system.changed();
  assert.equal(document.documentElement.dataset.theme,'dark');
  assert.equal(button.textContent,'Modo claro');
  button.onclick();
  assert.equal(document.documentElement.dataset.theme,'light');
  assert.deepEqual(writes,[['sense-theme','light']]);
  system.changed();
  assert.equal(document.documentElement.dataset.theme,'light');
  assert.ok(events.every(type=>type==='themechange'));
  assert.equal(button['aria-label'],'Cambiar a modo oscuro');
});

test('recupera una elección guardada y permite alternar sin recargar',()=>{
  const {document,button}=fixture({saved:'dark'});
  assert.equal(document.documentElement.dataset.theme,'dark');
  button.onclick();
  assert.equal(document.documentElement.dataset.theme,'light');
  button.onclick();
  assert.equal(document.documentElement.dataset.theme,'dark');
});

test('funciona aunque el navegador no permita almacenamiento local',()=>{
  const {document,button}=fixture({blocked:true,dark:true});
  assert.equal(document.documentElement.dataset.theme,'dark');
  assert.doesNotThrow(()=>button.onclick());
  assert.equal(document.documentElement.dataset.theme,'light');
});
