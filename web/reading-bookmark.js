/* 每页最多三个彩色书签，悬浮编辑问题。 */
let readingBookmark = {bookmarks:[]};
let readingBookmarkPath = '';
let readingBookmarkFigure = null;
let bookmarkPage = 0;
const bookmarkColors = ['#ffffff','#f5dfcc','#f7e9af','#dce8da','#dae7ee','#e8def0'];
const bookmarkStyle = document.createElement('style');
bookmarkStyle.textContent = `
  #bookmark-rail {position:fixed;left:0;top:42%;z-index:40;display:flex;flex-direction:column;gap:9px}
  #bookmark-rail[hidden],#bookmark-popup[hidden] {display:none}
  #bookmark-rail .bookmark-add-slot {width:48px;height:54px;flex:none}
  #bookmark-rail .bookmark-saved {display:flex;flex-direction:column;gap:9px}
  #bookmark-rail button[hidden] {display:none}
  body #bookmark-rail button {display:flex;align-items:center;justify-content:center;width:32px;height:37px;padding:0;background:transparent;border:0;border-radius:0}
  #bookmark-rail svg {width:32px;height:36px;filter:drop-shadow(1px 2px 2px #69452b15)}
  body #bookmark-rail button.bookmark-add {width:48px;height:54px;overflow:hidden;position:relative}
  #bookmark-rail .bookmark-add img {position:absolute;width:76px;height:86px;max-width:none;left:-13px;top:-15px;pointer-events:none;filter:drop-shadow(1px 1px 1px #69452b16)}
  body #bookmark-rail button:hover {background:transparent}
  #bookmark-popup {position:fixed;left:40px;top:30%;z-index:76;width:300px;max-width:calc(100vw - 52px);max-height:65vh;overflow:auto;background:var(--paper);color:var(--ink);border:1px solid #d7b99e;border-radius:12px;padding:14px;box-shadow:0 8px 28px #58381d20;font-size:13px}
  #bookmark-popup header {display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
  #bookmark-popup textarea {width:100%;min-height:90px;resize:vertical;padding:8px;background:#fffdf9;border:1px solid var(--line);border-radius:7px;font:inherit;color:inherit}
  #bookmark-colors {display:flex;gap:8px;margin:12px 0}
  body #bookmark-colors button {width:25px;height:25px;padding:0;border:1px solid #b58b6a;border-radius:50%}
  body #bookmark-colors button[aria-pressed=true] {outline:2px solid #9d704d;outline-offset:2px}
  #bookmark-popup footer {display:flex;gap:8px;align-items:center}
`;
document.head.appendChild(bookmarkStyle);
const bookmarkRail=document.createElement('div');bookmarkRail.id='bookmark-rail';bookmarkRail.hidden=true;
const bookmarkPopup=document.createElement('section');bookmarkPopup.id='bookmark-popup';bookmarkPopup.hidden=true;
bookmarkPopup.setAttribute('role','dialog');bookmarkPopup.setAttribute('aria-label','编辑此页书签');
document.body.append(bookmarkRail,bookmarkPopup);
const bookmarkAddSlot=document.createElement('div');bookmarkAddSlot.className='bookmark-add-slot';
const bookmarkSavedIcons=document.createElement('div');bookmarkSavedIcons.className='bookmark-saved';
bookmarkRail.append(bookmarkSavedIcons,bookmarkAddSlot);
const bookmarkAddButton=addBookmarkIcon(null);
bookmarkAddSlot.appendChild(bookmarkAddButton);
function loadReadingBookmark(saved) {
  readingBookmarkPath=state.path;
  readingBookmarkFigure=null;
  readingBookmark={bookmarks:Array.isArray(saved?.bookmarks) ? saved.bookmarks : []};
  if (!readingBookmark.bookmarks.length && saved?.pinned) {
    readingBookmark.bookmarks.push({...saved.pinned,id:'migrated',color:'#ffffff'});
  }
  bookmarkPage=0;bookmarkPopup.hidden=true;updateBookmarkPage();
}
function leaveReadingBookmark() {
  readingBookmarkPath='';bookmarkPopup.hidden=bookmarkRail.hidden=true;bookmarkPage=0;
}
function currentBookmarkPage() {
  const top=$('#scroll').getBoundingClientRect().top;
  const page=[...pagesEl.querySelectorAll('.page')].find(el=>el.getBoundingClientRect().bottom>top+40);
  return page ? Number(page.dataset.page) : 0;
}
function updateBookmarkPage() {
  if (!readingBookmarkPath || readingBookmarkPath!==state.path) { bookmarkRail.hidden=true;return; }
  const page=currentBookmarkPage();
  if (page===bookmarkPage) return;
  bookmarkPage=page;bookmarkPopup.hidden=true;renderBookmarkRail();
}
function renderBookmarkRail() {
  bookmarkSavedIcons.replaceChildren();bookmarkRail.hidden=!bookmarkPage;
  if (!bookmarkPage) return;
  const records=readingBookmark.bookmarks.filter(b=>b.page===bookmarkPage);
  for (const record of records) bookmarkSavedIcons.appendChild(addBookmarkIcon(record));
  bookmarkAddButton.hidden=records.length>=3;
  bookmarkAddButton.setAttribute('aria-label',`在第${bookmarkPage}页添加书签`);
  bookmarkAddButton.title=`第${bookmarkPage}页 · 添加书签（最多三个）`;
}
function addBookmarkIcon(record) {
  const button=document.createElement('button');
  button.setAttribute('aria-label',record ? `第${bookmarkPage}页书签：${record.question || '未填写问题'}` : `在第${bookmarkPage}页添加书签`);
  button.title=record ? `第${bookmarkPage}页 · ${record.question || '编辑书签'}` : `第${bookmarkPage}页 · 添加书签（最多三个）`;
  // 横向书签的凹口朝向纸页，轮廓呈侧 M 形。
  button.innerHTML='<svg viewBox="0 0 34 38" aria-hidden="true"><path d="M-2 3 Q-2 1 1 1 H30 Q33 1 31 4 L20 19 L31 34 Q33 37 30 37 H1 Q-2 37-2 35 Z" stroke="#a77a56" stroke-width="1.4"/></svg>';
  button.querySelector('path').setAttribute('fill',bookmarkColors.includes(record?.color) ? record.color : '#ffffff');
  if (!record) {
    button.classList.add('bookmark-add');
    const still=document.createElement('img');
    still.alt='';still.draggable=false;
    button.replaceChildren(still);
    still.src='/assets/kanshan/bookmark-peek.png';
  }
  button.onclick=()=>openBookmarkEditor(record,button);
  return button;
}
function bookmarkPageNotes(page) {
  return (state.notes || []).filter(note=>{
    const para=state.paras[Number(note.idx)];
    return para && ((para.rects || []).some(rect=>Number(rect.page)===page) || Number(para.page)===page);
  });
}
async function revealReadingBookmark(mark) {
  const figure=figureRecords.find(record=>record.id===mark.figureId);
  if (figure) { locateFigureRecord(figure); return; }
  const idx=state.paras.findIndex(para=>mark.text && para.text===mark.text &&
    (Number(para.page)===mark.page || (para.rects || []).some(rect=>Number(rect.page)===mark.page)));
  if (idx>=0) { await revealPara(idx); return; }
  const scroll=$('#scroll'),page=pagesEl.querySelector(`.page[data-page="${mark.page}"]`);
  if (!page) return;
  scroll.scrollTop+=page.getBoundingClientRect().top-scroll.getBoundingClientRect().top+
    page.clientHeight*Math.max(0,Math.min(1,mark.offset || 0));
}
function openBookmarkEditor(record,trigger) {
  const path=readingBookmarkPath,page=record?.page || bookmarkPage;
  const existing=record;
  let color=record?.color || '#ffffff';
  bookmarkPopup.replaceChildren();bookmarkPopup.hidden=false;
  const header=document.createElement('header'),title=document.createElement('strong'),close=document.createElement('button');
  title.textContent=`第 ${page} 页 · ${record ? '编辑书签' : '新书签'}`;
  close.textContent='×';close.setAttribute('aria-label','关闭书签');close.onclick=()=>{bookmarkPopup.hidden=true;trigger.focus({preventScroll:true});};
  header.append(title,close);
  const question=document.createElement('textarea');question.maxLength=1000;question.placeholder='此处有什么问题？';question.setAttribute('aria-label','此处的问题');question.value=record?.question || '';
  question.style.background=bookmarkColors.includes(color) ? color : '#ffffff';
  const related=document.createElement('select');related.setAttribute('aria-label','关联本页批注');
  related.style.cssText='width:100%;margin:8px 0;font:inherit;padding:5px;border:1px solid var(--line);border-radius:6px;background:var(--paper)';
  const notes=bookmarkPageNotes(page);
  const empty=document.createElement('option');empty.value='';empty.textContent=notes.length ? '选用本页批注（可选）' : '本页暂无批注';related.appendChild(empty);
  for (const item of notes) {
    const option=document.createElement('option');option.value=JSON.stringify({kind:'note',id:item.id});
    option.textContent=item.text.slice(0,60);
    related.appendChild(option);
  }
  if (existing?.questionRef?.kind==='note' && notes.some(note=>note.id===existing.questionRef.id)) related.value=JSON.stringify(existing.questionRef);
  related.onchange=()=>{
    if (!related.value) return;
    const ref=JSON.parse(related.value);
    const item=notes.find(item=>item.id===ref.id);
    if (item) question.value=(item.text || item.q || '').slice(0,1000);
  };
  const colors=document.createElement('div');colors.id='bookmark-colors';
  bookmarkColors.forEach((value,index)=>{
    const swatch=document.createElement('button');swatch.style.background=value;
    swatch.setAttribute('aria-label',['白色','暖杏色','浅黄色','浅绿色','浅蓝色','浅紫色'][index]);
    swatch.setAttribute('aria-pressed',String(value===color));
    swatch.onclick=()=>{color=value;question.style.background=value;[...colors.children].forEach((el,i)=>el.setAttribute('aria-pressed',String(bookmarkColors[i]===color)));};
    colors.appendChild(swatch);
  });
  const footer=document.createElement('footer'),save=document.createElement('button'),status=document.createElement('p');status.setAttribute('role','status');
  save.textContent='保存书签';
  let pending=false;
  async function commit(next) {
    if (pending || path!==readingBookmarkPath) return;
    pending=true;save.disabled=true;
    try {
      const result=await saveStore({reading_bookmark:{bookmarks:next}},path);
      if (path!==readingBookmarkPath) return;
      if (!result) {status.textContent='保存未完成，请重试';return;}
      readingBookmark={bookmarks:next};bookmarkPopup.hidden=true;renderBookmarkRail();
    } finally {pending=false;save.disabled=false;}
  }
  save.onclick=()=>{
    const records=readingBookmark.bookmarks;
    if (!existing && records.filter(b=>b.page===page).length>=3) {status.textContent='此页已有三个书签';return;}
    const pageEl=pagesEl.querySelector(`.page[data-page="${page}"]`);
    const top=$('#scroll').getBoundingClientRect().top,rect=pageEl.getBoundingClientRect();
    const para=state.paras[state.sel];
    const selected=para?.rects.some(r=>Number(r.page)===page);
    const mark={...(existing || {}),id:existing?.id || crypto.randomUUID(),page,
      offset:existing?.offset ?? Math.max(0,Math.min(1,(top-rect.top)/rect.height)),
      text:existing?.text || (selected ? para.text : ''),
      figureId:existing?.figureId || figureRecords.find(r=>r.id===readingBookmarkFigure && r.page===page)?.id,
      question:question.value.trim(),questionRef:related.value ? JSON.parse(related.value) : null,color};
    commit(existing ? records.map(b=>b.id===mark.id ? mark : b) : [...records,mark]);
  };
  footer.appendChild(save);
  if (existing) {
    const remove=document.createElement('button');remove.textContent='删除书签';remove.onclick=()=>commit(readingBookmark.bookmarks.filter(b=>b.id!==existing.id));footer.appendChild(remove);
    const jump=document.createElement('button');jump.textContent='回到此处';jump.onclick=async()=>{
      await revealReadingBookmark(existing);
    };footer.appendChild(jump);
  }
  const overview=document.createElement('details');overview.style.marginTop='12px';
  const overviewTitle=document.createElement('summary');overviewTitle.textContent='这篇论文的书签';overview.appendChild(overviewTitle);
  for (const mark of [...readingBookmark.bookmarks].sort((a,b)=>a.page-b.page)) {
    const entry=document.createElement('button');entry.textContent=`第 ${mark.page} 页 · ${mark.question || '未填写问题'}`;
    entry.style.cssText='display:block;text-align:left;width:100%;margin:6px 0;font:inherit;border:1px solid #b58b6a';
    entry.style.background=bookmarkColors.includes(mark.color) ? mark.color : '#ffffff';
    entry.onclick=async()=>{
      gotoPage(mark.page);
      await revealReadingBookmark(mark);
      if (path!==readingBookmarkPath) return;
      bookmarkPage=currentBookmarkPage();renderBookmarkRail();
      openBookmarkEditor(mark,bookmarkAddButton);
    };
    overview.appendChild(entry);
  }
  bookmarkPopup.append(header,question,related,colors,footer,status,overview);question.focus({preventScroll:true});
}
let bookmarkScrollFrame=0;
function scheduleBookmarkPageUpdate() {
  if (bookmarkScrollFrame) return;
  bookmarkScrollFrame=requestAnimationFrame(()=>{bookmarkScrollFrame=0;updateBookmarkPage();});
}
$('#scroll').addEventListener('scroll',scheduleBookmarkPageUpdate,{passive:true});
window.addEventListener('resize',scheduleBookmarkPageUpdate);
document.addEventListener('keydown',event=>{if(event.key==='Escape') bookmarkPopup.hidden=true;});
