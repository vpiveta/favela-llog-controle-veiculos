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
