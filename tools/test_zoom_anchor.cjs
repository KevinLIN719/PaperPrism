const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('web/reader.html','utf8');
const start=html.indexOf('function captureZoomAnchor(');
const end=html.indexOf('let zoomRevision',start);
const context={};vm.createContext(context);vm.runInContext(html.slice(start,end),context);
let scale=1;
const scroll={scrollTop:1200,scrollLeft:0,clientTop:0,clientLeft:0,clientWidth:1000,clientHeight:600,
  getBoundingClientRect:()=>({left:0,top:0})};
const pages=[0,1,2,3].map(index=>({dataset:{page:String(index+1)},getBoundingClientRect(){
  const top=index*(1000*scale+20)-scroll.scrollTop;
  return {left:500-300*scale-scroll.scrollLeft,top,width:600*scale,height:1000*scale,bottom:top+1000*scale};
}}));
for (const next of [1.15,1.9,.7,1]) {
  const anchor=context.captureZoomAnchor(scroll,pages);
  assert.strictEqual(anchor.page,'2');
  scale=next;
  context.restoreZoomAnchor(scroll,pages[1],anchor);
  const rect=pages[1].getBoundingClientRect();
  assert(Math.abs(rect.top+anchor.y*rect.height-300)<1e-8);
  assert(Math.abs(rect.left+anchor.x*rect.width-500)<1e-8);
}
scroll.scrollTop=710; // 视图中心落在第一页与第二页的20px空隙中。
const gap=context.captureZoomAnchor(scroll,pages);
assert.strictEqual(gap.page,'1');assert.strictEqual(gap.y,1);
assert.strictEqual(context.captureZoomAnchor(scroll,[]),null);
assert(html.includes('if (state.obs) state.obs.disconnect()'));
assert(!html.slice(html.indexOf('async function zoomBy('),html.indexOf('$("#go").onclick')).includes('select(keep)'));
console.log('PASS center point preserved through zoom in/out on middle page, nearest gap edge, empty document and no repeated paragraph selection');
