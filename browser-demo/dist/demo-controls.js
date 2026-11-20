/* Keep the original reader, sidebar, notes and bookmark behavior. */
const demoLockedMessage='浏览器体验版：实时 AI 暂时锁定，预生成结果可在右侧查看。完整版可从 GitHub 克隆到本地运行。';
const originalRestoreBundle=restoreBundle;
restoreBundle=async function(b){
  // The real PDF filename is used by the original reader's PDF URL builder.
  const path=state.path,d=await paperPrismDemo.load(path);
  await originalRestoreBundle(b);
  $('#stats').textContent='浏览器体验版 · 已加载预生成结果 · 笔记与书签保存在此浏览器';
  updateDemoControls();
};
initDemo=async function(){
  $('#demostrip').hidden=true;
  updateDemoControls();
};
function updateDemoControls(){
  compareButton.disabled=true;compareButton.title=demoLockedMessage;
  for(const id of ['forget','sum','askgo','figure-explain','repro-evaluate','setbtn','delete-paper','zhre','compare-explain']){
    const node=document.getElementById(id);if(node){node.disabled=true;node.title=demoLockedMessage;}
  }
  $('#go').textContent='打开';
  $('#askq').disabled=true;$('#askq').placeholder='实时追问已锁定；展开下方预生成追问记录查看回答。';
  $('#askhint').textContent='预生成追问可展开查看，引用仍可跳回原文。';
  $('#zhhint').textContent='浏览器体验版已锁定联网搜索。';
  document.querySelectorAll('.record-delete').forEach(b=>{if(b.closest('#askhist,#figure-history')){b.disabled=true;b.title='预生成示例保留供体验'}});
}
const nativeLayeredExplanation=renderLayeredExplanation;
renderLayeredExplanation=function(idx){
  const d=window.demoCurrent;
  if(d&&idx!==d.idx){const root=$('#layered-explanation');if(root){const p=document.createElement('p');p.className='hint';p.textContent='本段实时讲解已锁定，可点击上方“预生成讲解”查看缓存示例。';root.appendChild(p)}return}
  nativeLayeredExplanation(idx);
};
// Dynamic controls may be rebuilt by the original reader after selecting a paragraph.
const lockObserver=new MutationObserver(()=>updateDemoControlsIfNeeded());
function updateDemoControlsIfNeeded(){for(const id of ['figure-explain','zhre']){const b=document.getElementById(id);if(b&&!b.disabled){b.disabled=true;b.title=demoLockedMessage}}}
lockObserver.observe($('#panel'),{childList:true,subtree:true});
const nativeRun=run;
run=function(){const path=$('#pick').value;if(!path)return;window.demoReady=(async()=>{window.demoCurrent=await paperPrismDemo.load(path);await nativeRun()})();return window.demoReady;};
$('#go').onclick=run;
$('#pick').addEventListener('change',run);
const demoIntro=document.createElement('div');demoIntro.style.cssText='padding:14px 16px;border-bottom:1px solid var(--line);font-size:13px;line-height:1.7';
demoIntro.innerHTML='<b>浏览器体验版</b><p style="margin:6px 0">三篇不同领域论文，预生成讲解、追问与图表解析。实时 AI 暂时锁定。</p><div style="display:flex;gap:6px;flex-wrap:wrap"><button id="demo-explanation">预生成讲解</button><button id="demo-ask">追问示例</button><button id="demo-figure">图表示例</button></div><p style="margin:8px 0 0">完整版可前往 <a href="https://github.com/KevinLIN719/PaperPrism" target="_blank" rel="noopener">GitHub 克隆到本地运行</a>。</p>';
$('#panel').prepend(demoIntro);
$('#demo-explanation').onclick=async()=>{await window.demoReady;if(!window.demoCurrent)return;await revealPara(demoCurrent.idx);showTab('para');const drawer=$('#layered-explanation details');if(drawer)drawer.open=true;};
$('#demo-ask').onclick=async()=>{await window.demoReady;showTab('ask');const drawer=$('#askhist details');if(drawer)drawer.open=true;};
$('#demo-figure').onclick=async()=>{await window.demoReady;showTab('figure');const drawer=$('#figure-history details');if(drawer)drawer.open=true;};
// No drop handler is installed in this build, and no API call can reach a model.
document.addEventListener('dragover',e=>e.preventDefault());document.addEventListener('drop',e=>{e.preventDefault();warnBar('体验版仅提供三篇示例论文，自行导入请使用本地完整版。')});
const nativeAnnotateAll=annotateAll;annotateAll=async()=>{};
maybeZhihu=()=>{};
// Browser download replaces the full version's server-generated export.
exportSave.onclick=()=>{
  const title=window.demoCurrent?.title||'PaperPrism';
  const doc=buildReadingExport({title,date:new Date().toLocaleString('zh-CN'),paras:state.paras,summary:state.summary,
    notes:state.notes,bookmarks:readingBookmark.bookmarks,figures:figureRecords,
    asks:state.asks.map(ask=>({...ask,evidence:askCitationState(ask,state.paras)}))});
  const html=exportFormat.value==='html',blob=new Blob(['\ufeff',html?readingExportHTML(doc):readingExportMarkdown(doc)],{type:html?'text/html;charset=utf-8':'text/markdown;charset=utf-8'});
  const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=title+'-阅读笔记.'+(html?'html':'md');link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);exportDialog.close();
};
