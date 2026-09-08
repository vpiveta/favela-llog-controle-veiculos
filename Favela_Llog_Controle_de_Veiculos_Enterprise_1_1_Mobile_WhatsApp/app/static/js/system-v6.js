document.addEventListener('DOMContentLoaded',()=>{
  const openPlate=(plate)=>{ if(!plate) return; window.location.href='/buscar?q='+encodeURIComponent(plate); };
  document.querySelectorAll('.v5-fleet-row').forEach(row=>{
    row.classList.add('is-clickable'); row.tabIndex=0;
    const plate=row.querySelector('b')?.textContent?.trim();
    const go=()=>openPlate(plate); row.addEventListener('click',go); row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});
  });
  document.querySelectorAll('.v5-fuel-cards article').forEach(card=>{
    card.classList.add('is-clickable'); card.tabIndex=0;
    const plate=card.querySelector('b')?.textContent?.trim();
    const go=()=>openPlate(plate); card.addEventListener('click',go); card.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});
  });
  const pills=[...document.querySelectorAll('.v5-status-panel .filter-pills span')];
  const rows=[...document.querySelectorAll('.v5-fleet-row')];
  pills.forEach((pill,i)=>pill.addEventListener('click',()=>{
    pills.forEach(p=>p.classList.remove('active')); pill.classList.add('active');
    rows.forEach(r=>{const t=r.textContent.toLowerCase(); let show=true; if(i===1) show=t.includes('disponível'); if(i===2) show=t.includes('manutenção'); if(i===3) show=t.includes('pend'); r.style.display=show?'grid':'none';});
  }));
});
