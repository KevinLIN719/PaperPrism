/* 拖放复用分层讲解的入口，拖动预览不调用模型。 */
const kanshanStyle = document.createElement('style');
kanshanStyle.textContent = `
  #kanshan {position:relative;flex:none;z-index:35;display:flex;align-items:flex-end;gap:3px;padding:6px 16px 10px;background:transparent;border:0}
  #kanshan[hidden] {display:none}
  #kanshan-dock {position:relative;flex:none}
  #kanshan-dock[hidden] {display:none}
  #kanshan-dock::before {content:'';position:absolute;left:16px;right:16px;top:0;height:1px;background:rgba(169,139,111,.22)}
  body #panel #kanshan-handle {touch-action:none;background:transparent;border:0;padding:0;width:88px;height:88px;cursor:grab;box-shadow:none}
  body #panel #kanshan-handle:hover:not(:disabled) {background:transparent;border:0;box-shadow:none}
  #kanshan-handle img {width:100%;height:100%;object-fit:contain;pointer-events:none;user-select:none}
  #kanshan .kanshan-speech {position:relative;align-self:center;flex:0 1 240px;min-width:0;max-width:240px;padding:10px 14px;background:#fff;border:1px solid #b38b6d;border-radius:11px}
  #kanshan .kanshan-speech::before {content:'';position:absolute;left:-6px;top:50%;width:10px;height:10px;background:#fff;border-left:1px solid #b38b6d;border-bottom:1px solid #b38b6d;transform:translateY(-50%) rotate(45deg)}
  #kanshan small {display:block;color:var(--button-ink);background:transparent;padding:0;font-size:11px;line-height:1.7;white-space:pre-line}
  #kanshan.dragging {pointer-events:none}
  #kanshan.dragging #kanshan-handle {cursor:grabbing}
  .hit.kanshan-target {background:#efcf8b66;outline:2px solid var(--accent);outline-offset:1px}
`;
document.head.appendChild(kanshanStyle);
const kanshan = document.createElement('div');
kanshan.id = 'kanshan';
const kanshanDock = document.createElement('div');
kanshanDock.id = 'kanshan-dock';
const kanshanHandle = document.createElement('button');
kanshanHandle.id = 'kanshan-handle';
kanshanHandle.setAttribute('aria-label', '看山讲解选中段落，也可拖到段落上');
const kanshanImage = document.createElement('img');
kanshanImage.src = '/assets/kanshan/idle.gif'; kanshanImage.alt = ''; kanshanImage.draggable = false;
kanshanHandle.appendChild(kanshanImage);
const kanshanActions = document.createElement('div');
kanshanActions.className = 'kanshan-speech';
const kanshanHint = document.createElement('small'); kanshanHint.textContent = '读到哪里卡住了？\n把我拖到那一段，我们一起读。\n也可以先选段，再点我。';
kanshanActions.appendChild(kanshanHint);
kanshan.append(kanshanHandle, kanshanActions);
kanshanDock.appendChild(kanshan); $('#panel').appendChild(kanshanDock);
let kanshanDrag = null;
function clearKanshanTarget() {
  pagesEl.querySelectorAll('.kanshan-target').forEach(el => el.classList.remove('kanshan-target'));
}
function resetKanshanDrag() {
  const drag = kanshanDrag; kanshanDrag = null;
  if (drag && kanshanHandle.hasPointerCapture(drag.id)) kanshanHandle.releasePointerCapture(drag.id);
  kanshan.style.transform = ''; kanshan.classList.remove('dragging'); clearKanshanTarget();
}
function syncKanshan() {
  kanshan.hidden = figureMode;
  kanshanDock.hidden = figureMode;
  if (figureMode) resetKanshanDrag();
}
function setKanshanExplanationStatus(status) {
  kanshanImage.src = status === 'loading' ? '/assets/kanshan/reading.gif' : '/assets/kanshan/idle.gif';
  if (status === 'ready') kanshanHint.textContent = '这一段的讲解准备好了。\n对着原文看看，哪里还不明白？\n换一段时，再把我拖过去。';
  if (status === 'error') kanshanHint.textContent = '这一段暂时没讲解成功。\n折叠后再展开，可以重试。\n也可以先看看原文。';
}
function explainWithKanshan(idx) {
  if (!state.doc || !state.paras[idx]) { kanshanHint.textContent = '想一起读哪一段？\n先在原文里选一段，再点我。\n也可以直接把我拖过去。'; return; }
  select(idx);
  const drawer = $('#layered-explanation details');
  if (drawer) {
    drawer.open = true;
    drawer.scrollIntoView({block:'nearest'});
    kanshanImage.src = '/assets/kanshan/reading.gif';
    kanshanHint.textContent = '就从这一段开始！\n讲解已展开，我们对着原文读。\n换一段时，再把我拖过去。';
  }
}
kanshanHandle.onclick = event => { if (event.detail === 0) explainWithKanshan(state.sel); };
kanshanHandle.addEventListener('pointerdown', event => {
  if (event.button !== 0 || figureMode) return;
  kanshanDrag = {id:event.pointerId,x:event.clientX,y:event.clientY,moved:false,idx:-1,path:state.path};
  kanshanHandle.setPointerCapture(event.pointerId);
});
kanshanHandle.addEventListener('pointermove', event => {
  const drag = kanshanDrag;
  if (!drag || drag.id !== event.pointerId) return;
  const dx = event.clientX-drag.x, dy = event.clientY-drag.y;
  if (!drag.moved && Math.hypot(dx,dy) < 6) return;
  drag.moved = true; kanshan.classList.add('dragging');
  kanshan.style.transform = `translate(${dx}px,${dy}px)`;
  clearKanshanTarget();
  const hit = document.elementsFromPoint(event.clientX,event.clientY).find(el => el.matches('.hit'));
  drag.idx = hit ? Number(hit.dataset.i) : -1;
  if (drag.idx >= 0) pagesEl.querySelectorAll(`.hit[data-i="${drag.idx}"]`).forEach(el => el.classList.add('kanshan-target'));
});
kanshanHandle.addEventListener('pointerup', event => {
  const drag = kanshanDrag;
  if (!drag || drag.id !== event.pointerId) return;
  resetKanshanDrag();
  if (drag.path !== state.path) return;
  if (!drag.moved) explainWithKanshan(state.sel);
  else if (drag.idx >= 0) explainWithKanshan(drag.idx);
});
kanshanHandle.addEventListener('pointercancel', resetKanshanDrag);
kanshanHandle.addEventListener('lostpointercapture', resetKanshanDrag);
document.addEventListener('keydown', event => { if (event.key === 'Escape') resetKanshanDrag(); });
