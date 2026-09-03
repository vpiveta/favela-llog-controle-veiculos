document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('a[href*="type=CAR"],a[href*="type%3DCAR"]').forEach(el=>el.remove());
  document.querySelectorAll('option[value="CAR"]').forEach(el=>el.remove());
  document.querySelectorAll('[data-fuel-section="CAR"]').forEach(el=>el.remove());
  document.querySelectorAll('label,span,small').forEach(el=>{
    const t=(el.textContent||'').trim().toLowerCase();
    if(t==='abastecimento · carros'||t==='abastecimento · carro'){
      const card=el.closest('article'); if(card) card.remove();
    }
  });
});
