/* Se aplica antes de pintar la página para evitar un cambio de tema al cargar. */
(() => {
  'use strict';
  const system=window.matchMedia('(prefers-color-scheme: dark)');
  let preference;
  try{preference=localStorage.getItem('sense-theme');}catch{}
  if(!['light','dark'].includes(preference))preference=null;
  function apply(){
    const theme=preference||(system.matches?'dark':'light');
    document.documentElement.dataset.theme=theme;
    const button=document.getElementById('theme-toggle');
    if(button){button.textContent=theme==='dark'?'Modo claro':'Modo oscuro';button.setAttribute('aria-label','Cambiar a '+button.textContent.toLowerCase());}
    document.dispatchEvent(new Event('themechange'));
  }
  apply();
  system.addEventListener('change',()=>{if(!preference)apply();});
  document.addEventListener('DOMContentLoaded',()=>{
    apply();
    document.getElementById('theme-toggle').onclick=()=>{
      preference=document.documentElement.dataset.theme==='dark'?'light':'dark';
      try{localStorage.setItem('sense-theme',preference);}catch{}
      apply();
    };
  });
})();
