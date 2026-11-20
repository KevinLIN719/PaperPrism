/* 图表首个小单元：页面内框选、坐标归一与本地截图预览。 */
let figureRecords = [];
let figureMode = false;
let figureDrag = null;
let figureSelection = null;

function cancelFigureDrag() {
  if (!figureDrag) return;
  figureDrag.box.remove();
  if (pagesEl.hasPointerCapture(figureDrag.id)) pagesEl.releasePointerCapture(figureDrag.id);
  figureDrag = null;
}
function setFigureMode(on) {
  cancelFigureDrag();
  figureMode = on;
  pagesEl.classList.toggle('figure-mode', on);
  $('#figure-toggle').setAttribute('aria-pressed', String(on));
  $('#figure-toggle').textContent = on ? '取消框选' : '框选图表';
  if (typeof paintReadAlongLinks === 'function') paintReadAlongLinks();
  if (on && typeof closeReadAlong === 'function') closeReadAlong();
  if (typeof syncKanshan === 'function') syncKanshan();
}
function clearFigure() {
  setFigureMode(false);
  figureSelection = null;
  $('#figure-explain').hidden = true;
  $('#figure-explain').disabled = false;
  $('#figure-result').replaceChildren();
  $('#figure-preview').hidden = true;
  $('#figure-preview').removeAttribute('src');
  $('#figure-return').hidden = $('#figure-clear').hidden = true;
  $('#figure-status').textContent = '尚未选取图表。';
  pagesEl.querySelectorAll('.figure-selection').forEach(el => el.remove());
}
function figurePoint(e, wrap) {
  const r = wrap.getBoundingClientRect();
  return [Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
          Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))];
}
function figureBounds(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}
function placeFigureBox(box, b) {
  Object.assign(box.style, {left: b[0]*100+'%', top: b[1]*100+'%',
    width: (b[2]-b[0])*100+'%', height: (b[3]-b[1])*100+'%'});
}
$('#figure-toggle').onclick = () => {
  if (!state.doc) { $('#figure-status').textContent = '请先打开一篇论文。'; showTab('figure'); return; }
  setFigureMode(!figureMode);
  showTab('figure');
};
$('#figure-clear').onclick = clearFigure;
document.addEventListener('keydown', e => { if (e.key === 'Escape') setFigureMode(false); });
pagesEl.addEventListener('pointerdown', e => {
  if (!figureMode || e.button !== 0) return;
  const wrap = e.target.closest('.page');
  if (!wrap || !wrap.querySelector('canvas')) return;
  e.preventDefault();
  cancelFigureDrag();
  const box = document.createElement('div');
  box.className = 'figure-selection';
  wrap.appendChild(box);
  figureDrag = {wrap, box, start: figurePoint(e, wrap), id: e.pointerId};
  pagesEl.setPointerCapture(e.pointerId);
});
pagesEl.addEventListener('pointermove', e => {
  if (!figureDrag || figureDrag.id !== e.pointerId) return;
  placeFigureBox(figureDrag.box, figureBounds(figureDrag.start, figurePoint(e, figureDrag.wrap)));
});
pagesEl.addEventListener('pointercancel', cancelFigureDrag);
pagesEl.addEventListener('pointerup', e => {
  const d = figureDrag;
  if (!d || d.id !== e.pointerId) return;
  const b = figureBounds(d.start, figurePoint(e, d.wrap));
  const canvas = d.wrap.querySelector('canvas');
  const r = d.wrap.getBoundingClientRect();
  cancelFigureDrag();
  if ((b[2]-b[0])*r.width < 12 || (b[3]-b[1])*r.height < 12) {
    $('#figure-status').textContent = '选区太小，请拖动框出完整图表。'; return;
  }
  const crop = document.createElement('canvas');
  const x = Math.floor(b[0]*canvas.width), y = Math.floor(b[1]*canvas.height);
  crop.width = Math.max(1, Math.ceil(b[2]*canvas.width)-x);
  crop.height = Math.max(1, Math.ceil(b[3]*canvas.height)-y);
  crop.getContext('2d').drawImage(canvas, x, y, crop.width, crop.height, 0, 0, crop.width, crop.height);
  figureSelection = {page: Number(d.wrap.dataset.page), bounds: b};
  $('#figure-result').replaceChildren();
  $('#figure-explain').hidden = false;
  $('#figure-explain').disabled = false;
  $('#figure-explain').textContent = '解读图表';
  figureSelection.context = collectFigureContext(state.paras, figureSelection, state.sizes);
  $('#figure-preview').src = crop.toDataURL('image/png');
  $('#figure-preview').hidden = false;
  $('#figure-status').textContent = `第 ${figureSelection.page} 页 · 已截取图表，可重新框选替换。`;
  $('#figure-return').hidden = $('#figure-clear').hidden = false;
  setFigureMode(false);
  showTab('figure');
});
$('#figure-return').onclick = () => {
  if (!figureSelection) return;
  const wrap = pagesEl.querySelector(`.page[data-page="${figureSelection.page}"]`);
  if (!wrap) return;
  pagesEl.querySelectorAll('.figure-selection').forEach(el => el.remove());
  const box = document.createElement('div'); box.className = 'figure-selection';
  placeFigureBox(box, figureSelection.bounds); wrap.appendChild(box);
  box.scrollIntoView({block: 'center', behavior: 'smooth'});
};


// 距离仅用于候选排序，不将相邻文字直接当作证据。
function figureDistance(para, selection, sizes) {
  const size = sizes[String(selection.page)] || [612, 792];
  const b = selection.bounds;
  let best = Infinity;
  for (const r of para.rects || []) {
    if (Number(r.page) !== selection.page) continue;
    const a = r.bbox.map((v, i) => v / size[i % 2]);
    const dx = Math.max(0, a[0]-b[2], b[0]-a[2]);
    const dy = Math.max(0, a[1]-b[3], b[1]-a[3]);
    best = Math.min(best, Math.hypot(dx, dy));
  }
  return best;
}
function figureReference(text) {
  const m = String(text).match(/(?:\b(Fig(?:ure)?\.?|Table)\s*|([图表])\s*)(\d+[a-z]?)(?![\w])/i);
  if (!m) return null;
  return {type: /table/i.test(m[1] || '') || m[2] === '表' ? 'table' : 'figure', number: m[3].toLowerCase()};
}
function mentionsFigure(text, ref) {
  if (!ref) return false;
  const pattern = ref.type === 'table' ? '(?:Tables?\\.?|表)' : '(?:Figures?\\.?|Figs?\\.?|图)';
  return new RegExp(pattern + '\\s*' + ref.number + '(?![a-z0-9])', 'i').test(text);
}
// 自动收集候选上下文供后续解读使用；位置邻近不代表证据已确认。
function collectFigureContext(paras, selection, sizes) {
  const candidates = paras.map((p, i) => ({p, i, distance: figureDistance(p, selection, sizes)}));
  const captions = candidates.filter(x => x.p.kind === 'caption' && x.distance <= .12)
    .sort((a,b) => a.distance-b.distance || a.i-b.i);
  const caption = captions[0] || null;
  const ref = caption ? figureReference(caption.p.text) : null;
  const paragraphs = candidates.filter(x => x.p.kind === 'body')
    .map(x => ({...x, match: mentionsFigure(x.p.text, ref)}))
    .filter(x => x.match || x.distance <= .15)
    .sort((a,b) => Number(b.match)-Number(a.match) || a.distance-b.distance || a.i-b.i)
    .slice(0, 8)
    .map(x => ({idx: x.i, page: x.p.page, text: x.p.text,
      reason: x.match ? 'figure_reference' : 'nearby'}));
  return {
    caption: caption ? {idx: caption.i, page: caption.p.page, text: caption.p.text, reason: 'nearby'} : null,
    paragraphs,
  };
}


$('#figure-explain').onclick = async () => {
  const selection = figureSelection;
  if (!selection || selection.loading) return;
  if (selection.result) { openFigureRecord(selection.result.record.id); return; }
  const path = state.path, token = state.annoToken;
  selection.loading = true;
  $('#figure-explain').disabled = true;
  $('#figure-explain').textContent = '正在解读…';
  $('#figure-status').textContent = '正在解读并对照图像、原文核对…';
  try {
    const response = await fetch('/api/figure', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path, page: selection.page, bounds: selection.bounds, context: selection.context}),
    });
    const data = await response.json();
    if (token !== state.annoToken || path !== state.path) return;
    if (data.meta) {
      usageAdd(data.meta);
      saveStore({usage: state.usage}, path);
    }
    if (!response.ok || data.error) throw new Error(data.error || '图表解读失败');
    selection.result = data;
    figureRecords = figureRecords.filter(r => r.id !== data.record.id);
    figureRecords.push(data.record);
    renderFigureHistory();
    if (selection !== figureSelection) return;
    $('#figure-preview').hidden = true;
    $('#figure-preview').removeAttribute('src');
    openFigureRecord(data.record.id);
    $('#figure-status').textContent = `第 ${selection.page} 页 · 图表解读完成`;
  } catch (err) {
    if (selection !== figureSelection || token !== state.annoToken) return;
    $('#figure-status').textContent = '解读失败：' + (err.message || err);
  } finally {
    selection.loading = false;
    if (selection === figureSelection) {
      $('#figure-explain').disabled = false;
      $('#figure-explain').textContent = selection.result ? '查看已保存解读' : '解读图表';
    }
  }
};
function renderFigureExplanation(data, root) {
  root.replaceChildren();
  const add = (tag, text, parent = root) => {
    const el = document.createElement(tag); el.textContent = text; parent.appendChild(el); return el;
  };
  if (data.scope_corrected) {
    add('p', '选区已确认为整图；旧解读可能只覆盖了子图，请重新框选解读以更新。').className = 'hint';
  }
  for (const [key, title] of [['reading','怎么看'], ['observations','图中观察'], ['claim','作者主张与解释'], ['limits','支持边界与未知项']]) {
    add('h3', title);
    const p = add('p', data.result[key]); p.style.whiteSpace = 'pre-wrap';
  }
  add('p', `模型：${data.meta.model} · ${(data.meta.ms/1000).toFixed(1)} 秒 · 本次调用用量已统计`).className = 'hint';
  const details = document.createElement('details'); root.appendChild(details);
  add('summary', '参考原文', details);
  if (!data.sources.length) add('p', '本次依据为选区图像，未引用相关原文。', details);
  for (const source of data.sources) {
    add('p', source.text, details);
    const jump = add('button', `第 ${source.page} 页 · 查看原文`, details);
    const idx = state.paras.findIndex(p => p.text.startsWith(source.text));
    jump.disabled = idx < 0;
    jump.onclick = async () => { if (idx >= 0) await revealPara(idx); showTab('figure'); };
  }
  const review = data.meta.auto_review;
  if (review) {
    const checked = add('details', '');
    add('summary', '依据与处理', checked);
    add('p', review.revised.length ? '部分表述已收窄，并再次对照图像与原文核对。' : '已对照选区图像与提供的相关原文处理。', checked);
    for (const item of review.items || []) {
      add('p', item.reason, checked);
      for (const proof of item.evidence || []) {
        add('p', proof.kind === 'image' ? `图中依据：${proof.detail}` : `原文摘录：${proof.quote}`, checked);
      }
    }
  }
}


function renderFigureHistory() {
  if (typeof closeReadAlong === 'function') closeReadAlong();
  const root = $('#figure-history'); root.replaceChildren();
  if (!figureRecords.length) root.textContent = '暂无记录，框选图表并解读后会自动保存。';
  for (const record of [...figureRecords].reverse()) {
    const drawer = document.createElement('details');
    drawer.dataset.recordId = record.id;
    drawer.style.cssText = 'border-bottom:1px solid var(--line);padding:10px 0';
    const summary = document.createElement('summary'); summary.className = 'record-summary';
    const title = document.createElement('span'); title.className = 'record-title'; title.textContent = record.title;
    summary.appendChild(title);
    summary.appendChild(createRecordDeleteButton('删除图表解读记录', async () => {
      const path = state.path, token = state.annoToken;
      const saved = await saveStore({del_figure: record.id}, path);
      if (!saved || path !== state.path || token !== state.annoToken) return;
      figureRecords = figureRecords.filter(r => r.id !== record.id);
      if (figureSelection && figureSelection.result && figureSelection.result.record.id === record.id) clearFigure();
      pagesEl.querySelectorAll('.figure-selection').forEach(el => el.remove());
      renderFigureHistory(); renderFigureLinks(state.sel);
    }));
    drawer.appendChild(summary);
    const body = document.createElement('div'); drawer.appendChild(body);
    drawer.addEventListener('toggle', () => {
      if (!drawer.isConnected) return;
      if (!drawer.open) { body.replaceChildren(); return; }
      root.querySelectorAll('details[data-record-id]').forEach(d => { if (d !== drawer) d.open = false; });
      renderFigureExplanation(record, body);
      locateFigureRecord(record);
    });
    root.appendChild(drawer);
  }
  pagesEl.querySelectorAll('.page').forEach(wrap => paintFigureRecordTargets(wrap, Number(wrap.dataset.page)));
  if (state.sel >= 0) renderFigureLinks(state.sel);
}
function openFigureRecord(id) {
  showTab('figure');
  const drawer = [...$('#figure-history').querySelectorAll('details[data-record-id]')].find(d => d.dataset.recordId === id);
  if (!drawer) return;
  drawer.open = true;
  drawer.scrollIntoView({block:'nearest'});
  const record = figureRecords.find(r => r.id === id);
  if (record) locateFigureRecord(record);
}
function locateFigureRecord(record) {
  if (typeof readingBookmarkFigure !== 'undefined') readingBookmarkFigure = record.id;
  const wrap = pagesEl.querySelector(`.page[data-page="${record.page}"]`);
  if (!wrap) return;
  pagesEl.querySelectorAll('.figure-selection').forEach(el => el.remove());
  const box = document.createElement('div'); box.className = 'figure-selection';
  placeFigureBox(box, record.bounds); wrap.appendChild(box);
  box.scrollIntoView({block:'center', behavior:'smooth'});
}
function recordMatchesParagraph(record, p) {
  return (p.rects || []).some(r => {
    if (Number(r.page) !== record.page) return false;
    const size = state.sizes[String(record.page)] || [612,792];
    const a = r.bbox.map((v,i) => v/size[i%2]), b = record.bounds;
    const intersection = Math.max(0, Math.min(a[2],b[2])-Math.max(a[0],b[0])) * Math.max(0, Math.min(a[3],b[3])-Math.max(a[1],b[1]));
    const smaller = Math.min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]));
    return smaller > 0 && intersection/smaller > .25;
  }) || record.sources.some(s => s.kind === 'caption' && s.text === p.text);
}
function renderFigureLinks(i, onlyRecord = null) {
  const root = $('#figure-links'); if (!root) return;
  root.replaceChildren();
  const p = state.paras[i];
  const records = onlyRecord ? [onlyRecord] : p ? figureRecords.filter(r => recordMatchesParagraph(r,p)) : [];
  for (const record of records) {
    const button = document.createElement('button');
    button.textContent = '查看图表解读：' + record.title;
    button.style.cssText = 'display:block;margin:8px 0';
    button.onclick = () => openFigureRecord(record.id);
    root.appendChild(button);
  }
}
function paintFigureRecordTargets(wrap, pno) {
  wrap.querySelectorAll('.figure-record-target').forEach(el => el.remove());
  for (const record of figureRecords.filter(r => r.page === pno)) {
    const target = document.createElement('div');
    target.className = 'figure-record-target';
    target.style.cssText = 'position:absolute;cursor:pointer;z-index:1';
    target.title = record.title + ' · 查看已有解读';
    placeFigureBox(target, record.bounds);
    target.onclick = e => {
      if (figureMode) return;
      e.stopPropagation();
      const idx = state.paras.findIndex(p => p.kind === 'caption' && recordMatchesParagraph(record,p));
      if (idx >= 0) select(idx);
      else {
        showTab('para');
        $('#pbody').replaceChildren();
        const links = document.createElement('div'); links.id = 'figure-links'; $('#pbody').appendChild(links);
      }
      renderFigureLinks(idx, record);
    };
    wrap.appendChild(target);
  }
}
