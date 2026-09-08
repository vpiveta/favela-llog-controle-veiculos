document.addEventListener('DOMContentLoaded',()=>{
  const goHistory=(el)=>{ const url=el?.dataset?.historyUrl; if(url) window.location.href=url; };
  document.querySelectorAll('.v5-fleet-row').forEach(row=>{
    row.classList.add('is-clickable'); row.tabIndex=0;
    row.addEventListener('click',e=>{ if(e.target.closest('form,select,a,button')) return; goHistory(row); });
    row.addEventListener('keydown',e=>{ if((e.key==='Enter'||e.key===' ')&&!e.target.closest('form,select,a,button')){e.preventDefault();goHistory(row);} });
  });
  document.querySelectorAll('.v5-fuel-cards article').forEach(card=>{
    card.classList.add('is-clickable'); card.tabIndex=0;
    card.addEventListener('click',e=>{ if(e.target.closest('a,button,form,select')) return; goHistory(card); });
    card.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();goHistory(card);}});
  });
  const pills=[...document.querySelectorAll('.v5-status-panel .filter-pills span')];
  const rows=[...document.querySelectorAll('.v5-fleet-row')];
  pills.forEach((pill,i)=>pill.addEventListener('click',()=>{
    pills.forEach(p=>p.classList.remove('active')); pill.classList.add('active');
    rows.forEach(r=>{const t=r.textContent.toLowerCase(); let show=true; if(i===1) show=t.includes('disponível'); if(i===2) show=t.includes('manutenção'); if(i===3) show=t.includes('pend'); r.style.display=show?'grid':'none';});
  }));
  const quickSearch=document.querySelector('[data-list-search="fleetStatusList"]');
  if(quickSearch){
    quickSearch.addEventListener('keydown',e=>{
      if(e.key!=='Enter') return;
      const visible=rows.filter(r=>r.style.display!=='none');
      if(visible.length===1){e.preventDefault();goHistory(visible[0]);}
    });
  }
});
