const fs=require('fs'),vm=require('vm'),assert=require('assert');
let breakpoint,observer,frame;
const collapsed=[],zooms=[];
const media={matches:true,addEventListener:(event,fn)=>breakpoint=fn};
const scroll={clientWidth:700};
const context={document:{createElement:()=>({}),head:{appendChild(){}},body:{classList:{contains:()=>false}}},
  window:{matchMedia:()=>media},ResizeObserver:class{constructor(fn){observer=fn;}observe(){}},
  setSidebarCollapsed:value=>collapsed.push(value),$:()=>scroll,
  requestAnimationFrame:fn=>{frame=fn;return 1;},cancelAnimationFrame(){},state:{doc:{},sizes:{'1':[612,792]},zoom:2},
  pagesEl:{querySelectorAll:()=>[]},captureZoomAnchor:()=>({page:'1'}),fitWidth:()=>1.05,zoomBy:k=>zooms.push(k)};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/responsive-reader.js','utf8'),context);
assert.deepStrictEqual(collapsed,[true]);
observer();frame();assert.deepStrictEqual(zooms,[.525]);
observer();assert.strictEqual(zooms.length,1);
media.matches=false;breakpoint();assert.deepStrictEqual(collapsed,[true,false]);
console.log('PASS initial narrow collapse, center-preserving fit request, unchanged-width guard and wide-state restore');
