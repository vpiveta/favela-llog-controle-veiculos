document.querySelectorAll('[data-attention-select]').forEach((select)=>{
  const sync=()=>{
    const key=select.dataset.reasonTarget;
    const wrap=document.querySelector(`[data-attention-reason="${key}"]`);
    if(!wrap)return;
    const value=String(select.value||'').toUpperCase();
    const attention=value==='ATTENTION'||value==='MAINTENANCE';
    wrap.hidden=!attention;
    const field=wrap.querySelector('textarea,input');
    if(field)field.required=attention;
  };
  select.addEventListener('change',sync);sync();
});

document.querySelectorAll('[data-share-pdf]').forEach((button)=>{
  button.addEventListener('click',async()=>{
    const url=button.dataset.sharePdf;
    const name=button.dataset.pdfName||'favela-llog.pdf';
    const original=button.textContent;
    try{
      button.disabled=true;button.textContent='Gerando PDF...';
      const response=await fetch(url,{credentials:'same-origin'});
      if(!response.ok)throw new Error('PDF indisponível');
      const blob=await response.blob();
      const file=new File([blob],name,{type:'application/pdf'});
      if(navigator.canShare&&navigator.canShare({files:[file]})&&navigator.share){
        await navigator.share({title:'Favela Llog - Controle de Veículos',files:[file]});
      }else{
        const objectUrl=URL.createObjectURL(blob);
        const a=document.createElement('a');a.href=objectUrl;a.download=name;document.body.appendChild(a);a.click();a.remove();
        setTimeout(()=>URL.revokeObjectURL(objectUrl),3000);
        alert('PDF gerado. No seu aparelho, anexe o arquivo baixado na conversa do WhatsApp.');
      }
    }catch(err){if(err?.name!=='AbortError')alert('Não foi possível compartilhar o PDF. Tente novamente.');}
    finally{button.disabled=false;button.textContent=original;}
  });
});
