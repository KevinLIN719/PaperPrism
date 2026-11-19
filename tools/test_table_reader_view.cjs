const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.open=false;}
  append(...items){this.children.push(...items);}
  appendChild(item){this.append(item);return item;}
  replaceChildren(...items){this.children=items;}
  before(){} addEventListener(){} setAttribute(){}
  showModal(){this.open=true;} close(){this.open=false;}
}
function all(e){return e.children.flatMap(c=>c instanceof Element?[c,...all(c)]:[]);}
const body=new Element('body'),history=new Element('history'),jumps=[],requests=[];
const row={cells:['Steel','12.5'],page:2,bounds:[.1,.2,.7,.3]};
const data={mode:'merged',header:['Object','Force (N)'],rows:[row],message:'已整理',note:'无OCR',
  segments:[{idx:3,page:2,caption:'Table 1. Continued.',header:['Object','Force (N)'],rows:[row],bounds:row.bounds}]};
const context={document:{body,createElement:tag=>new Element(tag)},$:()=>history,state:{path:'sample.pdf',annoToken:4},
  locateFigureRecord:source=>jumps.push(source),revealPara:idx=>jumps.push(idx),
  fetch:async(url,options)=>{requests.push({url,payload:JSON.parse(options.body)});return {ok:true,json:async()=>data};}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/figure-catalogue.js','utf8'),context);
(async()=>{
  await context.openTableReader({idx:3,label:'Table 1'});
  assert.strictEqual(requests[0].url,'/api/table-read');
  const dialog=body.children[0];assert(dialog.open);
  assert(all(dialog).some(e=>e.textContent==='12.5'));
  all(dialog).find(e=>e.textContent==='第 2 页').onclick();assert(!dialog.open);assert.strictEqual(jumps[0].page,2);
  data.mode='separate';data.message='列不一致';data.segments[0].warning='单位不同';
  await context.openTableReader({idx:3,label:'Table 1'});
  assert(all(dialog).some(e=>e.textContent==='单位不同'));
  context.resetFigureCatalogue();assert(!dialog.open);
  console.log('PASS merged/separate table display, row source jump and paper-switch cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
