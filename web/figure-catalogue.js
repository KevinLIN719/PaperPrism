const catalogueDrawer=document.createElement('details');catalogueDrawer.style.margin='10px 0';
const catalogueTitle=document.createElement('summary');catalogueTitle.textContent='自动图表目录';
const catalogueBody=document.createElement('div');catalogueDrawer.append(catalogueTitle,catalogueBody);
$('#figure-history').before(catalogueDrawer);
let cataloguePath='',cataloguePending=false;
let catalogueVersion=0;
const tableReaderDialog=document.createElement('dialog');
tableReaderDialog.style.cssText='width:min(1100px,calc(100vw - 40px));max-height:calc(100dvh - 40px);padding:20px;background:var(--paper);color:var(--ink);border:1px solid var(--line);border-radius:14px;overflow:auto;font:inherit';
document.body.appendChild(tableReaderDialog);
let tableReaderRequest=0;
function resetFigureCatalogue(){catalogueVersion++;cataloguePath='';cataloguePending=false;catalogueBody.replaceChildren();catalogueDrawer.open=false;tableReaderRequest++;tableReaderDialog.close();}
async function openTableReader(item){
  const path=state.path,token=state.annoToken,request=++tableReaderRequest;
  const close=document.createElement('button');close.textContent='← 返回论文';close.onclick=()=>tableReaderDialog.close();
  const title=document.createElement('h3');title.textContent=`${item.label} · 表格阅读`;
  const status=document.createElement('p');status.className='hint';status.setAttribute('role','status');status.textContent='正在提取原生表格与续页…';
  const content=document.createElement('div');
  tableReaderDialog.replaceChildren(close,title,status,content);if(!tableReaderDialog.open)tableReaderDialog.showModal();
  const sourceButton=(text,source)=>{
    const button=document.createElement('button');button.textContent=text;
    button.onclick=()=>{tableReaderDialog.close();if(source.bounds)locateFigureRecord(source);else revealPara(source.idx);};
    return button;
  };
  function drawTable(header,rows){
    const scroll=document.createElement('div');scroll.style.cssText='overflow-x:auto;margin:12px 0';
    const table=document.createElement('table');table.style.cssText='width:100%;border-collapse:collapse;font-size:13px;line-height:1.6';
    const columns=Math.max(header.length,...rows.map(row=>row.cells.length),0);
    const head=document.createElement('tr');
    for(const text of [...(header.length?header:Array.from({length:columns},(_,i)=>`列 ${i+1}`)),'原文']){
      const th=document.createElement('th');th.textContent=text;th.style.cssText='text-align:left;padding:8px 10px;background:var(--button-soft);border-bottom:1px solid var(--line);white-space:pre-wrap';head.appendChild(th);
    }
    const thead=document.createElement('thead');thead.appendChild(head);table.appendChild(thead);
    const body=document.createElement('tbody');
    for(const row of rows){
      const tr=document.createElement('tr');
      for(let index=0;index<columns;index++){
        const td=document.createElement('td');td.textContent=row.cells[index] || '';td.style.cssText='vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line);white-space:pre-wrap';tr.appendChild(td);
      }
      const source=document.createElement('td');source.style.cssText='padding:5px;white-space:nowrap;vertical-align:top';
      source.appendChild(sourceButton(`第 ${row.page} 页`,row));tr.appendChild(source);body.appendChild(tr);
    }
    table.appendChild(body);scroll.appendChild(table);content.appendChild(scroll);
  }
  try{
    const response=await fetch('/api/table-read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,idx:item.idx})});
    const data=await response.json();if(!response.ok || data.error)throw new Error(data.error || '表格读取失败');
    if(path!==state.path || token!==state.annoToken || request!==tableReaderRequest)return;
    status.textContent=`${data.message} ${data.note}`;
    for(const segment of data.segments){
      const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=`第 ${segment.page} 页 · 表注与原文`;
      const caption=document.createElement('p');caption.textContent=segment.caption;
      details.append(summary,caption,sourceButton('查看原页',segment));content.appendChild(details);
      if(data.mode==='separate'){
        if(segment.warning){const hint=document.createElement('p');hint.className='hint';hint.textContent=segment.warning;content.appendChild(hint);}
        if(segment.rows.length)drawTable(segment.header,segment.rows);
      }
    }
    if(data.mode==='merged')drawTable(data.header,data.rows);
  }catch(error){if(request===tableReaderRequest)status.textContent=error.message || String(error);}
}
catalogueDrawer.addEventListener('toggle',async()=>{
  if(!catalogueDrawer.open)return;
  if(cataloguePath===state.path && catalogueBody.childElementCount)return;
  if(cataloguePending)return;
  const path=state.path,token=state.annoToken;
  const version=catalogueVersion;
  if(!path){catalogueBody.textContent='请先打开论文';return;}
  cataloguePending=true;catalogueBody.textContent='正在整理图表与可识别标签…';
  try{
    const response=await fetch('/api/figure-catalogue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
    const data=await response.json();if(!response.ok || data.error)throw new Error(data.error || '目录生成失败');
    if(path!==state.path || token!==state.annoToken || version!==catalogueVersion)return;
    cataloguePath=path;catalogueBody.replaceChildren();
    const hint=document.createElement('p');hint.className='hint';hint.textContent='范围来自现有图注热区，可能包含图注或相邻内容。子图入口定位标签，续表入口逐页查看。';catalogueBody.appendChild(hint);
    for(const item of data.items){
      const row=document.createElement('details'),title=document.createElement('summary');title.textContent=`${item.label} · 第 ${item.page} 页${item.continued ? ' · 续表' : ''}`;row.appendChild(title);
      const caption=document.createElement('p');caption.textContent=item.caption;row.appendChild(caption);
      const button=(text,action)=>{const b=document.createElement('button');b.textContent=text;b.style.margin='3px';b.onclick=action;row.appendChild(b);return b;};
      button('查看图注',()=>revealPara(item.idx));
      if(item.kind==='table')button(item.continuations.length?'合并阅读续表':'阅读表格',()=>openTableReader(item));
      item.regions.forEach((region,index)=>button(`选区 ${index+1}`,()=>{
        figureSelection={...region,context:collectFigureContext(state.paras,region,state.sizes)};
        $('#figure-preview').hidden=true;$('#figure-preview').removeAttribute('src');$('#figure-result').replaceChildren();
        $('#figure-explain').hidden=false;$('#figure-explain').disabled=false;$('#figure-explain').textContent='解读图表';
        $('#figure-return').hidden=$('#figure-clear').hidden=false;
        $('#figure-status').textContent=`${item.label} · 自动候选范围，请确认后解读或重新框选。`;
        locateFigureRecord(region);showTab('figure');
      }));
      for(const panel of item.panels)button(panel.label,()=>{
        const size=state.sizes[String(panel.page)] || [612,792];
        locateFigureRecord({page:panel.page,bounds:panel.bbox.map((v,n)=>v/size[n%2])});
      });
      for(const idx of item.continuations)button('查看续接页',()=>revealPara(idx));
      catalogueBody.appendChild(row);
    }
    if(!data.items.length)catalogueBody.textContent='当前解析未识别到图注，可继续手动框选。';
  }catch(error){if(version===catalogueVersion)catalogueBody.textContent=error.message || String(error);}finally{if(version===catalogueVersion)cataloguePending=false;}
});
