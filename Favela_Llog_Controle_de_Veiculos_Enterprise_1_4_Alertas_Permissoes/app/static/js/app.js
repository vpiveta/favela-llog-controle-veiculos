const same=document.getElementById('sameDay');const endWrap=document.getElementById('endDateWrap');function syncEnd(){if(!same||!endWrap)return;endWrap.style.display=same.checked?'none':'grid';const input=endWrap.querySelector('input');if(input)input.required=!same.checked}if(same){same.addEventListener('change',syncEnd);syncEnd()}const oil=document.getElementById('oilChange');const oilFields=document.getElementById('oilFields');function syncOil(){if(oil&&oilFields)oilFields.style.display=oil.checked?'grid':'none'}if(oil){oil.addEventListener('change',syncOil);syncOil()}


async function prepareReceipt(input) {
  const file = input.files && input.files[0];
  if (!file || !file.type.startsWith('image/')) return;
  const previewId = input.dataset.preview;
  const preview = previewId ? document.getElementById(previewId) : null;
  const image = new Image();
  image.src = URL.createObjectURL(file);
  await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; });
  const max = 1600;
  const scale = Math.min(1, max / Math.max(image.width, image.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.width * scale));
  canvas.height = Math.max(1, Math.round(image.height * scale));
  canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
  if (preview) { preview.src = canvas.toDataURL('image/jpeg', .82); preview.hidden = false; }
  if (file.size > 900000 || scale < 1) {
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .82));
    if (blob && typeof DataTransfer !== 'undefined') {
      const dt = new DataTransfer();
      dt.items.add(new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', {type:'image/jpeg'}));
      input.files = dt.files;
    }
  }
  URL.revokeObjectURL(image.src);
}
document.querySelectorAll('.camera-input').forEach(input => input.addEventListener('change', () => prepareReceipt(input).catch(() => {})));


const checklistVehicle=document.getElementById('checklistVehicle');
const borrowReasonWrap=document.getElementById('borrowReasonWrap');
const borrowReason=document.getElementById('borrowReason');
function syncBorrowedVehicle(){
  if(!checklistVehicle||!borrowReasonWrap)return;
  const borrowed=String(checklistVehicle.value)!==String(checklistVehicle.dataset.ownVehicle||'');
  borrowReasonWrap.hidden=!borrowed;
  if(borrowReason)borrowReason.required=borrowed;
}
if(checklistVehicle){checklistVehicle.addEventListener('change',syncBorrowedVehicle);syncBorrowedVehicle();}
const hasDamage=document.getElementById('hasDamage');
const damageFields=document.getElementById('damageFields');
const damageDescription=document.getElementById('damageDescription');
const damagePhoto=document.getElementById('damagePhoto');
function syncDamage(){
  if(!hasDamage||!damageFields)return;
  const yes=hasDamage.value==='yes';
  damageFields.hidden=!yes;
  if(damageDescription)damageDescription.required=yes;
  if(damagePhoto)damagePhoto.required=yes;
}
if(hasDamage){hasDamage.addEventListener('change',syncDamage);syncDamage();}


// Alertas em tempo real para administradores. O navegador exige uma interação antes de liberar áudio.
(function(){
  if(document.body.dataset.admin!=='1') return;
  const endpoint=document.body.dataset.notificationUrl;
  const badge=document.getElementById('notificationBadge');
  const toast=document.getElementById('notificationToast');
  const title=document.getElementById('notificationToastTitle');
  const message=document.getElementById('notificationToastMessage');
  let previousCount=null;
  let audioUnlocked=false;
  let audioContext=null;
  function unlock(){
    try{ audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)(); if(audioContext.state==='suspended') audioContext.resume(); audioUnlocked=true; }catch(e){}
  }
  ['click','touchstart','keydown'].forEach(evt=>document.addEventListener(evt,unlock,{once:true,passive:true}));
  function beep(){
    if(!audioUnlocked||!audioContext) return;
    const osc=audioContext.createOscillator(), gain=audioContext.createGain();
    osc.type='sine'; osc.frequency.setValueAtTime(880,audioContext.currentTime);
    gain.gain.setValueAtTime(.0001,audioContext.currentTime); gain.gain.exponentialRampToValueAtTime(.18,audioContext.currentTime+.02); gain.gain.exponentialRampToValueAtTime(.0001,audioContext.currentTime+.42);
    osc.connect(gain); gain.connect(audioContext.destination); osc.start(); osc.stop(audioContext.currentTime+.45);
  }
  async function poll(){
    try{
      const response=await fetch(endpoint,{headers:{'Accept':'application/json'},cache:'no-store'}); if(!response.ok)return;
      const data=await response.json();
      if(badge){ badge.textContent=data.count; badge.hidden=data.count<1; }
      if(previousCount!==null && data.count>previousCount){
        beep();
        if(toast){ title.textContent=data.latest_title||'Novo alerta'; message.textContent=data.latest_message||''; toast.hidden=false; clearTimeout(toast._timer); toast._timer=setTimeout(()=>toast.hidden=true,9000); }
      }
      previousCount=data.count;
    }catch(e){}
  }
  poll(); setInterval(poll,10000);
})();
