/* La vista previa gira en pantalla; el backend orienta los bytes antes de analizarlos. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), api=window.senseAPI;
  let applied=null, pending=false, blocked=true, previewURL=null;
  function controls(){
    $('camera-preview').disabled=blocked||pending;
    $('camera-rotation').disabled=blocked||pending;
    $('camera-apply').disabled=blocked||pending||$('camera-preview-frame').hidden||Number($('camera-rotation').value)===applied;
  }
  function rotate(){
    $('camera-image').style.transform='rotate('+$('camera-rotation').value+'deg)';
    controls();
  }
  async function post(path,body){
    const response=await api.fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    if(!response.ok)throw Error((await response.json()).error||'No se pudo ajustar la cámara.');
    return response;
  }
  $('camera-rotation').onchange=rotate;
  $('camera-preview').onclick=async()=>{
    pending=true;controls();$('camera-status').textContent='Tomando foto actual…';
    try{
      const response=await post('/api/camera/preview');
      if(previewURL)URL.revokeObjectURL(previewURL);
      $('camera-image').src=api.offline?window.senseOffline.captureURL:(previewURL=URL.createObjectURL(await response.blob()));
      $('camera-preview-frame').hidden=false;rotate();
      $('camera-status').textContent=api.offline?'Imagen simulada · no se utilizó la cámara.':'Foto actual lista. Elige el giro y aplica la orientación.';
    }catch(error){$('camera-status').textContent=error.message;}
    finally{pending=false;controls();}
  };
  $('camera-apply').onclick=async()=>{
    const rotation=Number($('camera-rotation').value);
    pending=true;controls();
    try{
      await post('/api/camera',{rotation_degrees:rotation});
      applied=rotation;$('camera-current').textContent=rotation+'°';
      window.senseUI?.clearCapture();
      $('camera-status').textContent='Orientación aplicada: '+rotation+'°. Las nuevas capturas se analizarán y guardarán así. El archivo de replay conserva su orientación original.';
    }catch(error){$('camera-status').textContent=error.message;}
    finally{pending=false;controls();}
  };
  api.subscribe(state=>{
    const rotation=state.camera_rotation_degrees??0;
    if(applied!==rotation){applied=rotation;$('camera-rotation').value=String(rotation);rotate();}
    $('camera-current').textContent=rotation+'°';
    const wasBlocked=blocked;
    blocked=!!(state.measurement?.running||state.measurement?.reserved||state.sandbox?.busy);
    if(blocked)$('camera-status').textContent='Orientación fija durante la ejecución. Espera a que terminen sus workers para ajustar la cámara.';
    else if(wasBlocked)$('camera-status').textContent='Cámara disponible. Toma una foto actual para revisar la orientación antes de comenzar.';
    controls();
  },()=>{blocked=true;controls();$('camera-status').textContent='Sin conexión: espera a recuperar el estado de la cámara.';});
})();
