const brandMenu = document.getElementById('brand-menu');
document.addEventListener('pointerdown', event => {
  if (!brandMenu.contains(event.target)) brandMenu.open = false;
});
document.getElementById('brand-menu-panel').addEventListener('click', event => {
  if (event.target.closest('button')) brandMenu.open = false;
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && brandMenu.open) {
    brandMenu.open = false;
    brandMenu.querySelector('summary').focus({preventScroll:true});
  }
});
