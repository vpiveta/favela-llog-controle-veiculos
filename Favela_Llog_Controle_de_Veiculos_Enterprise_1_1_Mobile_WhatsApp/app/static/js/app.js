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
  const selected=Boolean(checklistVehicle.value);
  const borrowed=selected&&String(checklistVehicle.value)!==String(checklistVehicle.dataset.ownVehicle||'');
  const checklistType=(document.getElementById('checklistForm')?.dataset.checklistType||'RETIRADA');
  borrowReasonWrap.hidden=!borrowed;
  if(borrowReason)borrowReason.required=borrowed&&checklistType==='RETIRADA';
  const summary=document.getElementById('borrowSummary');
  if(summary){ summary.hidden=!borrowed; if(borrowed){ summary.innerHTML='<span>Carregando último checklist e abastecimento...</span>'; fetch('/vehicle/'+checklistVehicle.value+'/borrow-summary').then(r=>r.json()).then(d=>{ const c=d.last_checklist?`${d.last_checklist.date} · Estado ${d.last_checklist.condition}${d.last_checklist.damage?' · Com avaria':''}`:'Sem checklist anterior'; const f=d.last_fuel?`${d.last_fuel.date} · R$ ${String(d.last_fuel.amount).replace('.',',')}`:'Sem abastecimento anterior'; summary.innerHTML=`<b>${d.plate} · ${d.vehicle}</b><span>Último checklist: ${c}</span><span>Último abastecimento: ${f}</span><small>Somente estas informações da moto de terceiro estão disponíveis.</small>`; }).catch(()=>summary.innerHTML='<span>Não foi possível carregar o resumo.</span>'); } }
}
if(checklistVehicle){checklistVehicle.addEventListener('change',syncBorrowedVehicle);syncBorrowedVehicle();}

const fuelVehicle=document.getElementById('fuelVehicle');
const fuelOdometer=document.getElementById('fuelOdometer');
function syncFuelVehicle(){
  if(!fuelVehicle||!fuelOdometer)return;
  const option=fuelVehicle.selectedOptions&&fuelVehicle.selectedOptions[0];
  const currentKm=option?.dataset.currentKm;
  fuelOdometer.placeholder=currentKm?`Ex.: ${currentKm}`:'Ex.: 15480';
}
if(fuelVehicle){fuelVehicle.addEventListener('change',syncFuelVehicle);syncFuelVehicle();}
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


// Alertas em tempo real para administradores, sem arquivo de som externo.
(function(){
  if(document.body.dataset.admin!=='1') return;
  const endpoint=document.body.dataset.notificationUrl;
  const badge=document.getElementById('notificationBadge');
  const toast=document.getElementById('notificationToast');
  const title=document.getElementById('notificationToastTitle');
  const message=document.getElementById('notificationToastMessage');
  const testButton=document.getElementById('testAlertSound');
  const status=document.getElementById('soundStatus');
  let previousSignature=null, audioContext=null, unlocked=false;
  function ensureAudio(){
    try{
      audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();
      if(audioContext.state==='suspended') audioContext.resume();
      unlocked=true;
      sessionStorage.setItem('fleetSoundUnlocked','1');
      if(status) status.textContent='🔊 Som ativado para esta sessão.';
      return true;
    }catch(e){ if(status)status.textContent='O navegador bloqueou o áudio. Toque novamente em Testar som.'; return false; }
  }
  function tone(freq,start,duration,volume=.16){
    const osc=audioContext.createOscillator(), gain=audioContext.createGain();
    osc.type='sine'; osc.frequency.value=freq;
    gain.gain.setValueAtTime(.0001,start); gain.gain.exponentialRampToValueAtTime(volume,start+.02); gain.gain.exponentialRampToValueAtTime(.0001,start+duration);
    osc.connect(gain); gain.connect(audioContext.destination); osc.start(start); osc.stop(start+duration+.02);
  }
  function playAlert(){ if(!ensureAudio())return; const now=audioContext.currentTime; tone(880,now,.22); tone(1175,now+.25,.34,.20); }
  ['click','touchstart','keydown'].forEach(evt=>document.addEventListener(evt,()=>{ if(!unlocked)ensureAudio(); },{once:true,passive:true}));
  if(testButton)testButton.addEventListener('click',()=>{ensureAudio();playAlert();});
  async function poll(){
    try{
      const response=await fetch(endpoint,{headers:{'Accept':'application/json'},cache:'no-store'}); if(!response.ok)return;
      const data=await response.json();
      if(badge){badge.textContent=data.count;badge.hidden=data.count<1;}
      const sig=String(data.latest_id)+':'+String(data.count);
      if(previousSignature!==null && sig!==previousSignature && data.count>0){
        playAlert();
        if(toast){title.textContent=data.latest_title||'Novo alerta';message.textContent=data.latest_message||'Existe um novo alerta para o administrador.';toast.hidden=false;clearTimeout(toast._timer);toast._timer=setTimeout(()=>toast.hidden=true,9000);}
      }
      previousSignature=sig;
    }catch(e){}
  }
  poll();setInterval(poll,8000);
})();

// Modais administrativos.
document.querySelectorAll('[data-reset-user]').forEach(btn=>btn.addEventListener('click',()=>{const d=document.getElementById('passwordDialog'),f=document.getElementById('passwordForm');f.action='/admin/users/'+btn.dataset.resetUser+'/reset-password';document.getElementById('passwordUserName').textContent=btn.dataset.resetName;d.showModal();}));
document.querySelectorAll('[data-delete-expense]').forEach(btn=>btn.addEventListener('click',()=>{const d=document.getElementById('deleteExpenseDialog'),f=document.getElementById('deleteExpenseForm');f.action='/admin/expense/'+btn.dataset.deleteExpense+'/delete';d.showModal();}));
document.querySelectorAll('[data-close-dialog]').forEach(btn=>btn.addEventListener('click',()=>btn.closest('dialog').close()));

document.querySelectorAll('[data-delete-checklist]').forEach(btn=>btn.addEventListener('click',()=>{const d=document.getElementById('deleteChecklistDialog'),f=document.getElementById('deleteChecklistForm');f.action='/admin/checklist/'+btn.dataset.deleteChecklist+'/delete';d.showModal();}));

// Edição de veículos.
document.querySelectorAll('[data-edit-vehicle]').forEach(btn=>btn.addEventListener('click',()=>{const d=document.getElementById('vehicleDialog'+btn.dataset.editVehicle);if(d)d.showModal();}));


// Busca instantânea nas listas administrativas por motorista ou placa.
document.querySelectorAll('[data-list-search]').forEach((input) => {
  const targetId = input.dataset.listSearch;
  const target = document.getElementById(targetId);
  if (!target) return;
  const empty = document.querySelector(`[data-search-empty="${targetId}"]`);
  const filter = () => {
    const term = (input.value || '').trim().toLocaleLowerCase('pt-BR');
    const items = Array.from(target.querySelectorAll('[data-search-item]'));
    let visible = 0;
    items.forEach((item) => {
      const text = (item.dataset.searchItem || item.textContent || '').toLocaleLowerCase('pt-BR');
      const show = !term || text.includes(term);
      item.hidden = !show;
      if (show) visible += 1;
    });
    if (empty) empty.hidden = visible !== 0;
  };
  input.addEventListener('input', filter);
  input.addEventListener('search', filter);
});
