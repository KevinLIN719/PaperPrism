const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.hidden=false;}
  append(...items){this.children.push(...items);}
  appendChild(item){this.append(item);return item;}
  prepend(item){this.children.unshift(item);}
  replaceChildren(...items){this.children=items;}
  setAttribute(){}
  showModal(){this.open=true;}
  close(){this.open=false;}
  querySelectorAll(selector){return all(this).filter(e=>e.tag==='input' && (selector!=='input:checked' || e.checked));}
}
function all(e){return e.children.flatMap(c=>c instanceof Element?[c,...all(c)]:[]);}
const body=new Element('body'),menu=new Element('menu'),pick={options:[{value:'a.pdf',textContent:'a.pdf'},{value:'b.pdf',textContent:'b.pdf'}]};
const requests=[],jumps=[],state={path:'a.pdf',paras:[]};
const sourceA={idx:0,page:1,text:'Dataset A.'},sourceB={idx:0,page:2,text:'Dataset B.'},contextSource={idx:8,page:4,text:'Method context.'};
const raw={papers:[{path:'a.pdf',file:'a.pdf'},{path:'b.pdf',file:'b.pdf'}],rows:[
  {topic:'研究问题',cells:[[],[]]}, {topic:'实验条件',cells:[[sourceA],[sourceB]]}],note:'原文'};
const context={document:{body,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})},state,
  $:selector=>selector==='#pick'?pick:menu,
  fetch:async(url,options)=>{
    const request=JSON.parse(options.body);requests.push(request);
    const data=structuredClone(raw);
    if(request.explain){data.summaries=[{sources:[sourceA,contextSource],items:{'研究问题':{text:'甲的中文概括',evidence:[{idx:0,quote:'Dataset A.'},{idx:8,quote:'Method context.'}]}},issues:{'实验条件':'review_incomplete'}},{items:{},error:'测试失败'}];data.meta={cost:{tokens:12,cost_cny:0.001}};}
    return {ok:true,json:async()=>data};
  },run:async()=>{state.path=pick.value;state.paras=[sourceB];},revealPara:async idx=>jumps.push(idx),gotoPage:page=>jumps.push(page)};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/paper-compare.js','utf8'),context);
(async()=>{
  menu.children[0].onclick();
  const dialog=body.children[0],inputs=dialog.querySelectorAll('input');
  const go=all(dialog).find(e=>e.textContent==='开始对照');
  await go.onclick();assert.strictEqual(requests.length,0); // 选项不足时不调用。
  inputs[1].checked=true;
  await go.onclick();
  assert.strictEqual(requests.length,1);
  assert.strictEqual(requests[0].explain,true);
  assert.strictEqual(requests[0].refresh,false);
  assert(!all(dialog).some(e=>String(e.textContent).startsWith('生成中文对照')));
  const paragraphs=all(dialog).filter(e=>e.tag==='p');assert(paragraphs.some(e=>e.textContent==='甲的中文概括'));
  assert(paragraphs.some(e=>String(e.textContent).includes('本篇中文概括暂未完成')));
  const summaries=all(dialog).filter(e=>e.tag==='summary');assert(summaries.some(e=>e.textContent==='概括依据 · 第 1 页 · 段号 0'));
  assert(all(dialog).some(e=>e.tag==='blockquote' && e.textContent==='Dataset A.'));
  assert(all(dialog).some(e=>e.tag==='blockquote' && e.textContent==='Method context.'));
  assert(paragraphs.some(e=>String(e.textContent).includes('尚未通过原文核对')));
  assert(!paragraphs.some(e=>String(e.textContent).includes('候选材料暂不足')));
  await go.onclick();assert.strictEqual(requests[1].refresh,true);
  const jumpsToOriginal=all(dialog).filter(e=>e.textContent==='查看原文');
  await jumpsToOriginal[jumpsToOriginal.length-1].onclick();
  assert.strictEqual(state.path,'b.pdf');assert.deepStrictEqual(jumps,[0]);assert(!dialog.open);
  console.log('PASS one-click Chinese comparison, selection validation, evidence, failed paper, retry and original-paper jump');
})().catch(error=>{console.error(error);process.exitCode=1;});
