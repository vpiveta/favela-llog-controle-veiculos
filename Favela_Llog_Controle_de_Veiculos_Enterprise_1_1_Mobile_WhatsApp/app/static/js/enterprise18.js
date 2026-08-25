document.addEventListener('DOMContentLoaded', () => {
  if (window.location.pathname === '/') {
    document.querySelectorAll('.panel h3').forEach((title) => {
      if (title.textContent.trim() === 'Frota' || title.textContent.trim() === 'Minha moto') {
        const panel = title.closest('.panel');
        if (panel) panel.remove();
      }
    });
    document.querySelectorAll('.grid2').forEach((grid) => {
      if (grid.children.length === 1) grid.style.gridTemplateColumns = '1fr';
      if (grid.children.length === 0) grid.remove();
    });
  }
});
