/* 追问保留当次输入选段，区分引用与未引用的输入材料。 */
function askCitationState(record, paras) {
  const references = [...new Set([...String(record.a || '').matchAll(/\[\s*#(\d+)\s*\]|#(\d+)/g)].map(m=>Number(m[1] || m[2])))];
  const legacy = record.citation_version !== 1;
  const sources = legacy ? [...new Set([...(record.used || []),...references])].filter(i=>Number.isInteger(i) && paras[i])
    .map(i=>({idx:i,page:paras[i].page,text:paras[i].text,legacy:true})) : (record.sources || []);
  const ids = new Set(sources.map(s=>s.idx));
  return {legacy, sources, references, cited:references.filter(i=>ids.has(i)), invalid:references.filter(i=>!ids.has(i))};
}
function renderAskAnswer(root, record) {
  root.replaceChildren();
  const evidence = askCitationState(record,state.paras);
  const cited = new Set(evidence.cited);
  const body = document.createElement('div'); body.style.whiteSpace='pre-wrap';
  body.innerHTML = escapeHtml(record.a || '').replace(/\[\s*#(\d+)\s*\]|#(\d+)/g, (m,x,y)=> {
    const idx=Number(x || y);
    return cited.has(idx) ? `<button class="cite" data-i="${idx}">第 ${idx} 段${evidence.legacy ? '（旧引用）' : ''}</button>`
      : `<span class="err">${escapeHtml(m)}（来源未核实）</span>`;
  });
  root.appendChild(body);
  // 旧段号漂移时不跳错位置：仅当当前原文仍匹配记录的选段才允许跳转。
  const canJump = source => state.paras[source.idx] && (evidence.legacy
    || state.paras[source.idx].text.startsWith(source.text));
  body.querySelectorAll('.cite').forEach(button=> {
    const source=evidence.sources.find(s=>s.idx===Number(button.dataset.i));
    button.disabled=!source || !canJump(source);
    if (source && canJump(source)) button.onclick=()=>revealPara(source.idx);
  });
  const addText=(tag,text,parent=root)=>{const node=document.createElement(tag);node.textContent=text;parent.appendChild(node);return node;};
  if (evidence.invalid.length) addText('p','有引用不在本次提供的材料中，不能作为已核实来源。').className='hint';
  const drawer=document.createElement('details');drawer.className='claim-evidence';
  addText('summary',evidence.legacy ? '原文来源（旧记录待核对）' : `原文来源（引用 ${evidence.cited.length} 段）`,drawer);
  addText('p', evidence.legacy ? '旧记录没有保存当次输入文本；以下是当前段落，无法确认当时是否完整提供。'
    : '下列文字是当次提供给模型的原文选段。引用段号不等于已验证答案得到支持。',drawer).className='hint';
  for (const isCited of [true,false]) {
    const group=evidence.sources.filter(s=>cited.has(s.idx)===isCited);
    if (!group.length) continue;
    addText('h4',isCited ? (evidence.legacy ? '回答中的段号' : '回答实际引用') : (evidence.legacy ? '旧记录中的材料段号（当次输入未核实）' : '仅作为输入材料，未被回答引用'),drawer);
    for (const source of group) {
      addText('p',`第 ${source.page} 页 · 第 ${source.idx} 段${source.truncated ? ` · 本次仅提供前${source.text.length}字符` : ''}`,drawer).className='hint';
      const text=document.createElement('div');text.className='source-quote';text.innerHTML=formatMathText(source.text);drawer.appendChild(text);
      const jump=addText('button','核对原文',drawer);jump.disabled=!canJump(source);
      jump.onclick=()=>revealPara(source.idx);
    }
  }
  if (!evidence.sources.length) addText('p','没有可核对的原文来源，请重新提问。',drawer);
  root.appendChild(drawer);
  const checkRoot=document.createElement("div");root.appendChild(checkRoot);
  renderAskReview(checkRoot,record);
}


function savedAskReview(record) {
  return Object.values(state.askReviews || {}).find(r=>r.ask_id===record.id && r.answer===record.a
    && JSON.stringify(r.sources)===JSON.stringify(record.sources));
}
function renderAskReview(root,record,open=false) {
  root.replaceChildren();
  const add=(tag,text,parent=root)=>{const el=document.createElement(tag);el.textContent=text;parent.appendChild(el);return el;};
  if (record.citation_version!==1 || !(record.sources || []).length) {
    return;
  }
  const review=savedAskReview(record);
  if (review) {
    const drawer=document.createElement('details');drawer.className='claim-evidence';drawer.open=open;
    add('summary',`逐项模型复核（${review.items.length} 项）`,drawer);
    add('p','以下仅核查模型识别出的判断与当次原文选段，不保证覆盖所有判断，也不代表事实认证。',drawer).className='hint';
    for (const item of review.items) {
      add('p',item.claim,drawer);add('b',item.status,drawer);add('p',item.reason,drawer);
      if (item.quote) {
        const quote=document.createElement('div');quote.innerHTML=formatMathText(item.quote);quote.className='source-quote';drawer.appendChild(quote);
        const source=record.sources.find(s=>s.idx===item.idx);
        const jump=add('button',`第 ${source ? source.page : '—'} 页 · 核对原文`,drawer);
        jump.disabled=!source || !state.paras[item.idx] || !state.paras[item.idx].text.startsWith(source.text);
        jump.onclick=()=>revealPara(item.idx);
      }
    }
    add('p',`模型：${review.meta.model}`,drawer).className='hint';root.appendChild(drawer);return;
  }
  // 旧记录不自动补发请求；新回答在服务端完成核对后才展示。
}
