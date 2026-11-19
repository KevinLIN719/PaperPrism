const compareButton=document.createElement('button');compareButton.textContent='跨论文对照';
$('#brand-menu-panel').appendChild(compareButton);
const compareDialog=document.createElement('dialog');
compareDialog.style.cssText='position:fixed;inset:0;width:100vw;height:100dvh;max-width:none;max-height:none;margin:0;overflow:auto;padding:24px;background:var(--paper);color:var(--ink);border:0;border-radius:0;font:inherit';
document.body.appendChild(compareDialog);
compareButton.onclick=()=>{
  compareDialog.replaceChildren();
  const title=document.createElement('h3');title.textContent='跨论文对照';
  const choices=document.createElement('div');choices.style.cssText='display:flex;gap:12px;flex-wrap:wrap';
  for (const option of $('#pick').options) {
    const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=option.value;input.checked=option.value===state.path;
    label.append(input,document.createTextNode(option.textContent.split(' · ')[0]));choices.appendChild(label);
  }
  const status=document.createElement('p');status.setAttribute('role','status');status.textContent='选择两到三篇已解析论文，开始后自动生成中文对照并核对原文，已有结果优先读取本地记录。';
  const go=document.createElement('button');go.textContent='开始对照';
  let selectedPaths=[],hasSummary=false;
  const close=document.createElement('button');close.textContent='← 返回单篇论文';close.onclick=()=>compareDialog.close();
  const output=document.createElement('div');
  compareDialog.append(close,title,choices,status,go,output);compareDialog.showModal();
  go.onclick=async()=>{
    const paths=[...choices.querySelectorAll('input:checked')].map(input=>input.value);
    if(paths.length<2 || paths.length>3){status.textContent='请选择两到三篇论文';return;}
    const refresh=hasSummary && JSON.stringify(paths)===JSON.stringify(selectedPaths);
    selectedPaths=paths;
    await loadComparison(refresh);
  };
  for(const input of choices.querySelectorAll('input'))input.onchange=()=>{hasSummary=false;go.textContent='开始对照';output.replaceChildren();};
  async function loadComparison(refresh=false){
    go.disabled=true;
    for(const input of choices.querySelectorAll('input'))input.disabled=true;
    status.textContent='正在整理原文、逐篇生成中文概括并自动核对，请稍候…';
    if(!refresh)output.replaceChildren();
    try {
      const response=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paths:selectedPaths,explain:true,refresh})});
      const data=await response.json();if(!response.ok || data.error)throw new Error(data.error || '对照失败');
      status.textContent=data.note;
      if(data.meta){
        const cost=data.meta.cost;
        status.textContent+=` 本次新增用量 ${cost.tokens} tokens${cost.cost_cny==null?' · 成本未估算':` · 约 ¥${Number(cost.cost_cny).toFixed(4)}`}。`;
        if(data.summaries.every(item=>item.cached))status.textContent+=' 已读取本地记录。';
      }
      hasSummary=true;
      go.textContent=data.summaries.every(item=>Object.keys(item.items).length===data.rows.length)?'开始对照':'重试未完成论文';
      const table=document.createElement('table');table.style.cssText='width:100%;table-layout:fixed;border-collapse:collapse;font-size:12px';
      const heading=document.createElement('tr');
      for(const text of ['主题',...data.papers.map(p=>p.file)]){const cell=document.createElement('th');cell.textContent=text;cell.style.cssText='padding:10px;border:1px solid var(--line);text-align:left';heading.appendChild(cell);}
      table.appendChild(heading);
      for(const row of data.rows){
        const tr=document.createElement('tr'),label=document.createElement('th');label.textContent=row.topic;label.style.cssText='width:90px;vertical-align:top;padding:8px;border:1px solid var(--line)';tr.appendChild(label);
        row.cells.forEach((sources,index)=>{
          const td=document.createElement('td');td.style.cssText='vertical-align:top;padding:10px;border:1px solid var(--line)';
          const paperSummary=data.summaries?.[index],item=paperSummary?.items?.[row.topic];
          if(paperSummary){
            const chinese=document.createElement('p');chinese.style.cssText='font-size:14px;line-height:1.7;margin:0 0 12px';
            const issue=paperSummary.issues?.[row.topic];
            const missing=issue==='not_explicit'?'本次读取的原文未明确说明此项。':issue==='no_sources'?'尚未定位到相关原文。':'本项概括尚未通过原文核对，暂不展示；已保留原文入口。';
            chinese.textContent=item?.text || (paperSummary.error?'本篇中文概括暂未完成，可重试；原文仍可查看。':missing);
            td.appendChild(chinese);
          }
          if(!sources.length && !paperSummary)td.textContent='当前原文检索未定位到候选，可进一步查看全文。';
          const displaySources=[...sources];
          for(const proof of item?.evidence || []){
            if(displaySources.some(source=>source.idx===proof.idx))continue;
            const source=(paperSummary?.sources || data.rows.flatMap(topic=>topic.cells[index])).find(source=>source.idx===proof.idx);
            if(source)displaySources.push(source);
          }
          for(const source of displaySources){
            const block=document.createElement('details');const summary=document.createElement('summary');
            const proof=item?.evidence?.find(e=>e.idx===source.idx);
            summary.textContent=`${proof?'概括依据 · ':''}第 ${source.page} 页 · 段号 ${source.idx}`;
            if(proof){const quote=document.createElement('blockquote');quote.textContent=proof.quote;quote.style.cssText='margin:8px 0;padding-left:10px;border-left:2px solid var(--line)';block.appendChild(quote);}
            const text=document.createElement('p');text.textContent=source.text;
            const jump=document.createElement('button');jump.textContent='查看原文';
            jump.onclick=async()=>{
              const path=data.papers[index].path;compareDialog.close();
              if(state.path!==path){$('#pick').value=path;await run();}
              const idx=state.paras.findIndex(p=>p.page===source.page && p.text===source.text);
              if(idx>=0)await revealPara(idx);else gotoPage(source.page);
            };
            block.prepend(summary);block.append(text,jump);td.appendChild(block);
          }
          tr.appendChild(td);
        });table.appendChild(tr);
      }
      output.replaceChildren(table);
    }catch(error){status.textContent=error.message || String(error);}finally{
      go.disabled=false;
      for(const input of choices.querySelectorAll('input'))input.disabled=false;
    }
  }
};
