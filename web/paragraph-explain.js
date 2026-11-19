/* 选择段落不自动付费，展开讲解才请求；后台已内置原文复核。 */
const paragraphExplanationRequests = new Map();
function requestParagraphExplanation(path, idx, token) {
  const key = JSON.stringify([path,idx,token]);
  if (!paragraphExplanationRequests.has(key)) {
    const request = (async () => {
      const response = await fetch('/api/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,idx})});
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || '讲解失败');
      if (path === state.path && token === state.annoToken && !data.cached) {
        usageAdd(data.explanation.meta);saveStore({usage:state.usage},path);
      }
      return data;
    })();
    paragraphExplanationRequests.set(key,request);
    request.finally(()=>paragraphExplanationRequests.delete(key)).catch(()=>{});
  }
  return paragraphExplanationRequests.get(key);
}
function renderLayeredExplanation(idx) {
  const root = $('#layered-explanation');
  if (!root) return;
  const drawer = document.createElement('details');
  drawer.className = 'srcbox';
  const title = document.createElement('summary');title.textContent = '分层讲解';drawer.appendChild(title);
  const content = document.createElement('div');drawer.appendChild(content);root.appendChild(drawer);
  let loaded = false, pending = false;
  drawer.addEventListener('toggle',async () => {
    if (!drawer.open || loaded || pending) return;
    const path = state.path, token = state.annoToken;
    pending = true;content.textContent = '正在整理讲解并对照原文核对…';
    if (typeof setKanshanExplanationStatus === 'function') setKanshanExplanationStatus('loading');
    try {
      const data = await requestParagraphExplanation(path,idx,token);
      if (path !== state.path || token !== state.annoToken) return;
      const result = data.explanation;
      if (!root.isConnected || state.sel !== idx) return;
      content.replaceChildren();
      const add = (tag,text) => { const node=document.createElement(tag);node.textContent=text;content.appendChild(node);return node; };
      add('h4','直白解释');add('p',result.plain);
      const background = document.createElement('details');
      const backgroundTitle = document.createElement('summary'); backgroundTitle.textContent = '必要背景'; background.appendChild(backgroundTitle);
      const backgroundText = document.createElement('p'); backgroundText.textContent = result.background || '本次原文材料不足以补充可靠背景，可就具体概念继续追问。'; background.appendChild(backgroundText);
      content.appendChild(background);
      const note = document.createElement('p'); note.textContent = '理解补充：依据相关原文整理，帮助理解，不作为作者的新结论。'; note.className = 'explanation-note'; background.appendChild(note);
      if (result.expressions.length) {
        const expressions = document.createElement('details');
        const expressionsTitle = document.createElement('summary'); expressionsTitle.textContent = '英文关键表达'; expressions.appendChild(expressionsTitle); content.appendChild(expressions);
        for (const expression of result.expressions) {
          const quote = document.createElement('blockquote'); quote.textContent = expression.quote;
          const meaning = document.createElement('p'); meaning.textContent = expression.meaning;
          expressions.append(quote, meaning);
        }
      }
      loaded = true;
      if (typeof setKanshanExplanationStatus === 'function') setKanshanExplanationStatus('ready');
    } catch (error) {
      if (path === state.path && token === state.annoToken && root.isConnected && state.sel === idx) {
        content.textContent='讲解未完成：'+error.message+'。折叠后重新展开可重试。';
        if (typeof setKanshanExplanationStatus === 'function') setKanshanExplanationStatus('error');
      }
    } finally { pending = false; }
  });
}
