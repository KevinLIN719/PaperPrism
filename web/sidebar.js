/* 整体收起右侧标签页，保留面板内容与当前标签。 */
const sidebarStyle = document.createElement('style');
sidebarStyle.textContent = `
  body.sidebar-collapsed #panel {display:none}
  body #sidebar-toggle {
    position:fixed;top:50%;right:var(--sidebar-edge,460px);transform:translateY(-50%);
    z-index:75;display:inline-flex;align-items:center;justify-content:center;
    width:22px;height:70px;padding:0 1px 0 4px;
    border:1px solid var(--line);border-right:0;border-radius:24px 0 0 24px;
    background:var(--paper);color:#a78063;box-shadow:-3px 0 8px #51351e08;
    transition:background-color .15s,color .15s;
  }
  body #sidebar-toggle:hover {background:var(--paper);color:var(--accent);border-color:var(--line)}
  body.sidebar-collapsed #sidebar-toggle {right:0;width:15px;height:58px;padding:0 0 0 2px}
  #sidebar-toggle svg {width:13px;height:16px;pointer-events:none}
  body.sidebar-collapsed #sidebar-toggle svg {transform:rotate(180deg);width:11px}
`;
document.head.appendChild(sidebarStyle);
const sidebarToggle = document.createElement('button');
sidebarToggle.id = 'sidebar-toggle';
sidebarToggle.type = 'button';
sidebarToggle.setAttribute('aria-controls', 'panel');
sidebarToggle.setAttribute('aria-expanded', 'true');
sidebarToggle.setAttribute('aria-label', '折叠右侧标签页');
sidebarToggle.title = '折叠右侧标签页';
sidebarToggle.innerHTML = '<svg viewBox="0 0 16 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 7 5 5-5 5"/></svg>';
document.body.appendChild(sidebarToggle);
const sidebarPanel = document.getElementById('panel');
function positionSidebarToggle() {
  const edge = document.documentElement.clientWidth - sidebarPanel.getBoundingClientRect().left;
  sidebarToggle.style.setProperty('--sidebar-edge', Math.max(0, edge - 1) + 'px');
}
new ResizeObserver(positionSidebarToggle).observe(sidebarPanel);
window.addEventListener('resize', positionSidebarToggle);
positionSidebarToggle();
function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle('sidebar-collapsed',collapsed);
  document.getElementById('panel').hidden = collapsed;
  resetKanshanDrag();
  positionSidebarToggle();
  sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
  const label = collapsed ? '展开右侧标签页' : '折叠右侧标签页';
  sidebarToggle.setAttribute('aria-label', label);
  sidebarToggle.title = label;
  if (collapsed) closeReadAlong();
}
sidebarToggle.onclick = () => {
  setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed'));
  sidebarToggle.focus({preventScroll:true});
};
