/* 原句旁看图。仅临时渲染 PDF，书库仍只保存已有坐标。 */
function readingFigureRefs(text) {
  const pattern = /(?:\b(Figs?(?:ures?)?\.?)\s*|\b(Tables?\.?)\s*|([图表])\s*)(S?\d+)([A-Za-z](?:\s*[/、,，和及&]\s*[A-Za-z])*)?(?![\w])/gi;
  return [...String(text).matchAll(pattern)].map(m => {
    let partText = m[5] || '';
    let step = '';
    if (String(text)[m.index + m[0].length] === ')') {
      const roman = partText.match(/,\s*([IVXLCDM]+)$/i);
      if (roman) { step = roman[1]; partText = partText.slice(0,roman.index); }
    }
    const following = String(text).slice(m.index + m[0].length);
    const stepMatch = following.match(/^\s*(?:[,;]\s*\(?|\(\s*)([IVXLCDM]+|[ivxlcdm]+|\d+|[Ⅰ-Ⅻⅰ-ⅻ]+)\)?(?=[\s,;.):]|$)/);
    if (!step && stepMatch) step = stepMatch[1];
    return {
      start: m.index, end: m.index + m[0].length, text: m[0],
      type: m[2] || m[3] === '表' ? 'table' : 'figure',
      number: m[4].toUpperCase(), parts: partText.toUpperCase().match(/[A-Z]/g) || [],
      step,
    };
  });
}
function readingFigureCandidates(ref, records) {
  const matches = records.filter(record => readingFigureRefs(record.title).some(candidate => {
    if (candidate.type !== ref.type || candidate.number !== ref.number) return false;
    if (!ref.parts.length) return true;
    if (!candidate.parts.length) return !record.partial && !record.title.includes('一部分');
    return ref.parts.every(part => candidate.parts.includes(part));
  }));
  const exact = matches.filter(record => readingFigureRefs(record.title).some(candidate =>
    candidate.parts.length === ref.parts.length && ref.parts.every(part => candidate.parts.includes(part))));
  return exact.length ? exact : matches;
}

function readingFigureTree(records) {
  const groups = new Map();
  for (const record of records) {
    const ref = record.indexRef || readingFigureRefs(record.title)[0];
    const key = ref ? `${ref.type}:${ref.number}` : 'other';
    if (!groups.has(key)) groups.set(key, {key, ref, label:ref ? `${ref.type === 'table' ? 'Table' : 'Fig'} ${ref.number}` : '其他选区', branches:new Map()});
    const group = groups.get(key);
    const part = ref?.parts.length ? ref.parts.join('/') : record.partial || record.title.includes('一部分') ? '局部' : '整图';
    if (!group.branches.has(part)) group.branches.set(part, []);
    group.branches.get(part).push(record);
  }
  for (const group of groups.values()) {
    for (const [part, entries] of group.branches) {
      if (entries.some(entry=>entry.indexRef?.step)) {
        group.branches.set(part,entries.filter(entry=>entry.indexRef?.step));
      }
    }
  }
  return [...groups.values()].sort((a,b)=>(a.ref?.type || 'z').localeCompare(b.ref?.type || 'z') || String(a.ref?.number || '').localeCompare(String(b.ref?.number || ''),'en',{numeric:true}));
}

function paragraphFigureTargets(refs, records, paras) {
  const targets=[], seen=new Set();
  for (const ref of refs) {
    const key=JSON.stringify([ref.type,ref.number,ref.parts,ref.step || '']);
    if (seen.has(key)) continue;
    seen.add(key);
    const matches=readingFigureCandidates(ref,records);
    if (matches.length) {
      targets.push(...matches.map(record=>({...record,indexRef:ref})));
      continue;
    }
    const captionIdx=paras.findIndex(p=>{
      if (p.kind!=='caption') return false;
      const head=readingFigureRefs(p.text)[0];
      return head && head.type===ref.type && head.number===ref.number;
    });
    targets.push({indexRef:ref,title:`${ref.text} · ${captionIdx>=0 ? '前往整图图注' : '尚未定位'}`,captionIdx,unavailable:captionIdx<0});
  }
  return targets;
}

function supplementaryMaterialLocation(paras) {
  const heading=/(?:supplementary\s+(?:materials?|information)|supporting\s+information|additional\s+(?:materials?|files?)|补充材料|补充信息|扩展材料)/i;
  let fallback=-1;
  for (let i=paras.length-1;i>=0;i--) {
    if (!heading.test(paras[i].text || '')) continue;
    fallback=i;
    for (let j=i;j<Math.min(paras.length,i+5);j++) {
      if (/https?:\/\/|www\./i.test(paras[j].text || '')) return j;
    }
  }
  return fallback;
}

function hasMovieReference(text) {
  return /\b(?:movies?|videos?)\s+S?\d+|(?:视频|影片)\s*S?\d+/i.test(text);
}

const readAlongStyle = document.createElement('style');
readAlongStyle.textContent = `
  .readalong-link {font:inherit;color:var(--accent);background:transparent;border:0;border-bottom:1px dotted currentColor;padding:0 2px;cursor:pointer}
  .readalong-edge {position:absolute;right:3px;z-index:25;display:flex;gap:4px;flex-wrap:wrap;max-width:45%;background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:2px 6px;box-shadow:0 2px 8px #0001}
  #readalong-card {position:fixed;right:18px;top:90px;width:285px;max-width:calc(100vw - 24px);max-height:calc(100vh - 110px);overflow:auto;z-index:70;background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:10px;box-shadow:0 8px 32px #201a1726}
  #readalong-card header {display:flex;justify-content:space-between;align-items:center;gap:12px}
  #readalong-card .readalong-tree {display:grid;grid-template-columns:1.35fr 1fr .7fr;gap:0;margin-top:8px;max-height:260px;overflow:auto}
  #readalong-card .readalong-column {display:flex;flex-direction:column;align-items:stretch;gap:3px;padding:0 5px;min-width:0}
  #readalong-card .readalong-column + .readalong-column {border-left:1px solid var(--line)}
  body #readalong-card .readalong-column button {font-size:12px;line-height:1.6;text-align:left;padding:3px 6px;background:transparent;border:0;border-radius:4px;color:var(--button-ink)}
  body #readalong-card .readalong-column button[aria-pressed=true] {background:var(--button-soft)}
  body #readalong-card .readalong-column button:hover {background:var(--button-hover)}
  @media(max-width:750px) {#readalong-card {top:auto;bottom:12px;right:12px;max-height:65vh}}
`;
document.head.appendChild(readAlongStyle);
const readAlongCard = document.createElement('section');
readAlongCard.id = 'readalong-card';
readAlongCard.hidden = true;
readAlongCard.setAttribute('role', 'dialog');
readAlongCard.setAttribute('aria-label', '图表索引');
document.body.appendChild(readAlongCard);
let readAlongVersion = 0;
let readAlongTrigger = null;
let readAlongKey = '';
let readAlongIndex = -1;
function closeReadAlong() {
  const wasOpen = !readAlongCard.hidden;
  readAlongVersion++;
  readAlongCard.hidden = true;
  readAlongCard.replaceChildren();
  readAlongKey = '';
  readAlongIndex = -1;
  if (wasOpen && readAlongTrigger?.isConnected) readAlongTrigger.focus({preventScroll:true});
  readAlongTrigger = null;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !readAlongCard.hidden) closeReadAlong(); });

function makeReadingFigureButton(ref, i) {
  const button = document.createElement('button');
  button.className = 'readalong-link';
  button.textContent = ref.text;
  button.title = '展开图表索引';
  button.onclick = e => { e.stopPropagation(); openReadAlong(ref, i, button); };
  return button;
}
function renderReadAlongLinks(i) {
  closeReadAlong();
  const para = state.paras[i];
  const text = document.querySelector('#pbody .srcbox .text');
  if (!para || !text || para.kind === 'code') return;
  const refs = readingFigureRefs(para.text);
  if (refs.length) {
    text.replaceChildren();
    let offset = 0;
    for (const ref of refs) {
      const span = document.createElement('span');
      span.innerHTML = formatMathText(para.text.slice(offset, ref.start));
      text.append(span, makeReadingFigureButton(ref, i));
      offset = ref.end;
    }
    const tail = document.createElement('span');
    tail.innerHTML = formatMathText(para.text.slice(offset));
    text.appendChild(tail);
  }
  paintReadAlongLinks();
  if ((refs.length || hasMovieReference(para.text)) && para.kind === 'body' && !figureMode) {
    openReadAlong(refs[0] || {start:0,text:'',parts:[]}, i, null);
  }
}
function paintReadAlongLinks() {
  pagesEl.querySelectorAll('.readalong-edge').forEach(el => el.remove());
  if (!readAlongCard.hidden && readAlongIndex >= 0) positionReadAlong(readAlongIndex);
}
function openReadAlong(ref, i, trigger) {
  const key = `${i}:${ref.start}`;
  if (!readAlongCard.hidden && readAlongKey === key) { closeReadAlong(); return; }
  closeReadAlong();
  readAlongKey = key; readAlongTrigger = trigger;
  readAlongIndex = i;
  readAlongCard.hidden = false;
  const header = document.createElement('header');
  const title = document.createElement('strong'); title.textContent = '图表索引';
  const close = document.createElement('button'); close.textContent = '×'; close.setAttribute('aria-label','关闭图表索引'); close.onclick = closeReadAlong;
  header.append(title, close); readAlongCard.appendChild(header);
  const paragraphText=state.paras[i]?.text || ref.text;
  const refs=readingFigureRefs(paragraphText);
  const targets=paragraphFigureTargets(refs,figureRecords,state.paras);
  const groups = readingFigureTree(targets.filter(record=>!record.unavailable));
  const hasExternal=targets.some(record=>record.unavailable) || hasMovieReference(paragraphText);
  const tree = document.createElement('div'); tree.className = 'readalong-tree';
  tree.setAttribute('aria-label','图号、子图与选区记录');
  const columns = Array.from({length:3},()=>{const el=document.createElement('div');el.className='readalong-column';tree.appendChild(el);return el;});
  if (groups.length) readAlongCard.appendChild(tree);
  function locate(record) {
    if (record.unavailable) return;
    if (record.captionIdx != null) revealPara(record.captionIdx);
    else locateFigureRecord(record);
  }
  function jump(record) { closeReadAlong(); locate(record); }
  function button(label, parent, action) {
    const el=document.createElement('button');el.textContent=label;
    el.setAttribute('aria-pressed','false');
    el.onclick=()=>{[...parent.children].forEach(node=>node.setAttribute('aria-pressed',String(node===el)));action();};
    parent.appendChild(el);return el;
  }
  function showRecords(part, records) {
    columns[2].replaceChildren();
    records.forEach((record,index)=>{
      const label=record.indexRef?.step || String(index+1);
      const leaf=button(label,columns[2],()=>jump(record));
      leaf.title=record.title;
      leaf.disabled=!!record.unavailable;
      leaf.setAttribute('aria-label',`${record.title} · ${label}`);
    });
  }
  function showParts(group) {
    columns[1].replaceChildren();columns[2].replaceChildren();
    for (const [part,records] of [...group.branches].sort(([a],[b])=>a.localeCompare(b,'en'))) {
      const node=button(part,columns[1],()=>{
        showRecords(part,records);
        // 点击子图直接回到该子图的首条保存选区；其余记录由第三列选择。
        locate(records[0]);
      });
      node.disabled=records.every(record=>record.unavailable);
      node.title=records[0].title;
      if (ref.parts.length && part === ref.parts.join('/')) {
        node.setAttribute('aria-pressed','true');showRecords(part,records);
      }
    }
    if (!columns[2].children.length && group.branches.size===1) {
      const [part,records]=[...group.branches][0];showRecords(part,records);
    }
  }
  const activeGroup=groups.find(group=>group.ref?.type===ref.type && group.ref.number===ref.number) || groups[0];
  for (const group of groups) {
    const node=button(group.label,columns[0],()=>showParts(group));
    if (group===activeGroup) {
      node.setAttribute('aria-pressed','true');showParts(group);
    }
  }
  if (hasExternal) {
    const row=document.createElement('div');row.style.cssText='margin-top:8px;padding-top:7px;border-top:1px solid var(--line)';
    const location=supplementaryMaterialLocation(state.paras);
    const entry=button('补充材料 · 图表／视频 ↗',row,()=>{closeReadAlong();revealPara(location);});
    entry.disabled=location<0;
    entry.title=location>=0 ? '前往文末提供的扩展材料入口' : '当前PDF未找到扩展材料入口';
    if (location<0) {
      const hint=document.createElement('small');hint.textContent='当前PDF未找到扩展链接';row.appendChild(hint);
    }
    readAlongCard.appendChild(row);
  }
  positionReadAlong(i);
}

function positionReadAlong(i) {
  if (typeof pagesEl==='undefined') return;
  const rect=state.paras[i]?.rects?.[0];
  if (!rect) return;
  const page=pagesEl.querySelector(`.page[data-page="${rect.page}"]`);
  if (!page) return;
  page.appendChild(readAlongCard);
  const zoom=state.zoom || 1;
  Object.assign(readAlongCard.style,{position:'absolute',left:(rect.bbox[2]+8)*zoom+'px',right:'auto',
    top:rect.bbox[1]*zoom+'px',bottom:'auto',width:'240px',maxWidth:'none',maxHeight:'360px',
    transform:'none',transformOrigin:'top left'});
}
