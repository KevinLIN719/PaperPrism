/* 窄窗口自动让出阅读区域，改变可用宽度时沿视图中心适配PDF。 */
const readerResponsiveStyle=document.createElement('style');
readerResponsiveStyle.textContent=`
  @media(max-width:1250px){#pick{max-width:min(260px,40vw)}#panel{width:min(460px,85vw)}#bar{gap:4px 7px;padding:6px 10px}}
  @media(max-width:650px){#bar #pick{max-width:40vw}#bar-meta{width:100%;text-align:left}#scroll{padding:12px}}
`;
document.head.appendChild(readerResponsiveStyle);
const narrowReader=window.matchMedia('(max-width:1250px)');
let wideReaderCollapsed=document.body.classList.contains('sidebar-collapsed');
function applyReaderBreakpoint(){
  if(narrowReader.matches){
    wideReaderCollapsed=document.body.classList.contains('sidebar-collapsed');
    setSidebarCollapsed(true);
  }else setSidebarCollapsed(wideReaderCollapsed);
}
narrowReader.addEventListener('change',applyReaderBreakpoint);
if(narrowReader.matches)applyReaderBreakpoint();
let readerResizeFrame=0,readerLastWidth=0;
new ResizeObserver(()=>{
  const width=$('#scroll').clientWidth;
  if(width===readerLastWidth)return;
  readerLastWidth=width;
  if(readerResizeFrame)cancelAnimationFrame(readerResizeFrame);
  readerResizeFrame=requestAnimationFrame(()=>{
    readerResizeFrame=0;
    if(!state.doc)return;
    const anchor=captureZoomAnchor($('#scroll'),pagesEl.querySelectorAll('.page'));
    const pageWidth=(state.sizes[String(anchor?.page || 1)] || [612,792])[0];
    const target=fitWidth(pageWidth);
    if(Math.abs(target-state.zoom)>.005)zoomBy(target/state.zoom);
  });
}).observe($('#scroll'));
