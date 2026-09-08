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

  const panel=document.querySelector('.v5-status-panel');
  if(panel){
    const pills=[...panel.querySelectorAll('[data-fleet-filter]')];
    const rows=[...panel.querySelectorAll('.v5-fleet-row')];
    const quickSearch=panel.querySelector('#fleetQuickSearch');
    const empty=panel.querySelector('.fleet-filter-empty');
    let activeFilter='all';

    const rowMatchesFilter=row=>{
      const status=(row.dataset.fleetStatus||'').toLowerCase();
      const pending=row.dataset.hasPending==='1';
      if(activeFilter==='available') return status==='available';
      if(activeFilter==='maintenance') return status==='maintenance';
      if(activeFilter==='pending') return pending;
      return true;
    };

    const applyFleetFilters=()=>{
      const term=(quickSearch?.value||'').trim().toLowerCase();
      let visible=0;
      rows.forEach(row=>{
        const text=(row.dataset.searchItem||row.textContent||'').toLowerCase();
        const show=rowMatchesFilter(row)&&(!term||text.includes(term));
        row.style.display=show?'grid':'none';
        if(show) visible++;
      });
      if(empty) empty.hidden=visible!==0;
      return visible;
    };

    pills.forEach(pill=>pill.addEventListener('click',()=>{
      activeFilter=pill.dataset.fleetFilter||'all';
      pills.forEach(p=>p.classList.toggle('active',p===pill));
      applyFleetFilters();
    }));

    if(quickSearch){
      quickSearch.addEventListener('input',applyFleetFilters);
      quickSearch.addEventListener('keydown',e=>{
        if(e.key!=='Enter') return;
        const visible=rows.filter(r=>r.style.display!=='none');
        if(visible.length===1){e.preventDefault();goHistory(visible[0]);}
      });
    }

    applyFleetFilters();
  }
});
