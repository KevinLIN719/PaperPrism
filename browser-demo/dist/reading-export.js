/* 从已有记录组装离线阅读笔记，原文快照随导出保留。 */
function buildReadingExport(bundle) {
  const sources=[],sections=[];
  function source(item) {
    if (!item?.text) return null;
    const match=sources.find(s=>s.page===item.page && s.idx===item.idx && s.text===item.text);
    if (match) return match.id;
    const id='source-'+(sources.length+1);
    sources.push({...item,id});return id;
  }
  function current(idx) {
    const para=bundle.paras[idx];
    return para ? source({idx,page:para.page,text:para.text}) : null;
  }
  const add=(title,blocks)=>{if(blocks.length) sections.push({title,blocks});};
  const summary=bundle.summary;
  if (summary) {
    add('论文概括',(summary.tl_dr || []).map(text=>({text,refs:[]})));
    add('核心主张',(summary.claims || []).map(claim=>({
      title:claim.claim,
      text:`${claim.statement_type || '旧记录待核对'} · 强度 ${claim.strength || '未标注'}\n${claim.evidence || ''}`,
      refs:[current(claim.idx),...(claim.evidence_sources || []).map(s=>source(s))].filter(Boolean)
    })));
  }
  add('我的批注',(bundle.notes || []).map(note=>({text:note.text,refs:[current(note.idx)].filter(Boolean)})));
  add('书签与未解问题',(bundle.bookmarks || []).map(mark=>({
    title:`第 ${mark.page} 页 · ${mark.question || '未填写问题'}`,
    text:`书签颜色 ${mark.color || '#ffffff'}`,
    refs:[source({page:mark.page,text:mark.text,idx:mark.idx})].filter(Boolean)
  })));
  add('追问记录',(bundle.asks || []).filter(ask=>!ask.pending).map(ask=>{
    const evidence=ask.evidence;
    const records=evidence ? evidence.sources.filter(s=>evidence.cited.includes(s.idx)) : ask.sources || [];
    const warnings=[];
    if (evidence?.legacy) warnings.push('旧记录的当次输入未核实，以下保留当前可用来源。');
    if (evidence?.invalid.length) warnings.push('来源未核实的段号：'+evidence.invalid.join('、'));
    return {title:ask.q,text:[ask.a,...warnings].filter(Boolean).join('\n'),refs:records.map(s=>source(s)).filter(Boolean)};
  }));
  add('图表解读',(bundle.figures || []).map(record=>({
    title:record.title,
    text:[`选区坐标 ${JSON.stringify(record.bounds)}`,
      ...[['reading','怎么看'],['observations','图中观察'],['claim','作者主张与解释'],['limits','支持边界与未知项']]
        .map(([key,title])=>record.result?.[key] ? title+'\n'+record.result[key] : '')].filter(Boolean).join('\n\n'),
    refs:(record.sources || []).map(s=>source(s)).filter(Boolean)
  })));
  return {title:bundle.title,date:bundle.date,sections,sources};
}
function readingExportMarkdown(doc) {
  const lines=[`# ${doc.title}`,`导出时间 ${doc.date}`,''];
  for (const section of doc.sections) {
    lines.push('## '+section.title,'');
    for (const block of section.blocks) {
      if (block.title) lines.push('### '+block.title,'');
      lines.push(block.text || '');
      if (block.refs.length) lines.push('',block.refs.map(id=>`[原文 ${id.replace('source-','')}](#${id})`).join(' · '));
      lines.push('');
    }
  }
  if (doc.sources.length) lines.push('## 原文来源','');
  for (const s of doc.sources) lines.push(`<a id="${s.id}"></a>`,`### 原文 ${s.id.replace('source-','')} · 第 ${s.page || '未知'} 页${s.idx != null ? ' · 段号 '+s.idx : ''}`,'',s.text,'');
  return lines.join('\n');
}
function readingExportHTML(doc) {
  const escape=value=>String(value ?? '').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const sections=doc.sections.map(section=>`<section><h2>${escape(section.title)}</h2>${section.blocks.map(block=>
    `<article>${block.title ? `<h3>${escape(block.title)}</h3>` : ''}<div class="text">${escape(block.text)}</div><p>${block.refs.map(id=>`<a href="#${id}">原文 ${escape(id.replace('source-',''))}</a>`).join(' · ')}</p></article>`).join('')}</section>`).join('');
  const sources=doc.sources.map(s=>`<article id="${s.id}"><h3>原文 ${s.id.replace('source-','')} · 第 ${escape(s.page || '未知')} 页${s.idx != null ? ' · 段号 '+escape(s.idx) : ''}</h3><div class="text">${escape(s.text)}</div></article>`).join('');
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(doc.title)}</title><style>body{max-width:880px;margin:40px auto;padding:0 24px;background:#fffdf8;color:#30281f;font:15px/1.8 system-ui,sans-serif}h1,h2,h3{line-height:1.4}h2{margin-top:32px}article{margin:18px 0;padding:16px;border:1px solid #e4ddcf;border-radius:8px;break-inside:avoid}a{color:#a4512b}.text{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#8a8275}@media print{body{max-width:none;margin:0;background:white}a{color:inherit}}</style><h1>${escape(doc.title)}</h1><small>导出时间 ${escape(doc.date)}</small>${sections}${sources ? '<section><h2>原文来源</h2>'+sources+'</section>' : ''}</html>`;
}

const exportButton=document.createElement('button');exportButton.textContent='导出笔记';exportButton.id='reading-export';
$('#setbtn').before(exportButton);
const exportDialog=document.createElement('dialog');
exportDialog.style.cssText='max-width:360px;background:var(--paper);color:var(--ink);border:1px solid var(--line);border-radius:12px;padding:20px;font:inherit';
const exportTitle=document.createElement('h3');exportTitle.textContent='导出阅读笔记';
const exportHint=document.createElement('p');exportHint.textContent='保存已有阅读记录及原文来源，离线继续查看。';
const exportFormat=document.createElement('select');exportFormat.setAttribute('aria-label','导出格式');
for (const [value,text] of [['md','Markdown（便于编辑）'],['html','HTML（浏览器查看／打印）']]) {
  const option=document.createElement('option');option.value=value;option.textContent=text;exportFormat.appendChild(option);
}
const exportStatus=document.createElement('p');exportStatus.setAttribute('role','status');
const exportCancel=document.createElement('button');exportCancel.textContent='取消';exportCancel.onclick=()=>exportDialog.close();
const exportSave=document.createElement('button');exportSave.textContent='下载';
const exportActions=document.createElement('div');exportActions.style.cssText='display:flex;justify-content:flex-end;gap:8px;margin-top:16px';exportActions.append(exportCancel,exportSave);
exportDialog.append(exportTitle,exportHint,exportFormat,exportStatus,exportActions);document.body.appendChild(exportDialog);
exportButton.onclick=()=>{
  if (!state.path || !state.paras.length) {exportStatus.textContent='请先打开一篇论文。';exportSave.disabled=true;}
  else {exportStatus.textContent='包含摘要、批注、书签问题、追问和图表解读。追问保留当次来源，旧记录会注明来源限制。';exportSave.disabled=false;}
  exportDialog.showModal();
};
exportSave.onclick=()=>{
  const title=state.path.split('/').pop().replace(/\.pdf$/i,'');
  const doc=buildReadingExport({title,date:new Date().toLocaleString('zh-CN'),paras:state.paras,summary:state.summary,
    notes:state.notes,bookmarks:readingBookmark.bookmarks,figures:figureRecords,
    asks:state.asks.map(ask=>({...ask,evidence:askCitationState(ask,state.paras)}))});
  const html=exportFormat.value==='html';
  const form=document.createElement('form');form.method='POST';form.action='/api/export-notes';form.hidden=true;
  for(const [name,value] of [['name',title+'-阅读笔记.'+(html ? 'html' : 'md')],['content',html ? readingExportHTML(doc) : readingExportMarkdown(doc)]]) {
    const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;form.appendChild(field);
  }
  document.body.appendChild(form);form.submit();form.remove();exportDialog.close();
};
