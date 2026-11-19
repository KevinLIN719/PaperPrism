const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const code = fs.readFileSync('web/figure-readalong.js', 'utf8');
const context = {};
vm.createContext(context);
vm.runInContext(code.slice(0, code.indexOf('const readAlongStyle')), context);
const refs = context.readingFigureRefs('See Fig. 3D and Table 1, then Figure 2A.');
assert.strictEqual(refs.length, 3);
assert.strictEqual(refs[1].type, 'table');
const records = ['第4页 图3A（一部分）', '第4页 图3C、D（一部分）', '第4页 图3', '第4页 表3'].map(title => ({title}));
assert.deepStrictEqual(Array.from(context.readingFigureCandidates(refs[0], records), r => r.title), [records[1].title, records[2].title]);
assert.strictEqual(context.readingFigureCandidates(context.readingFigureRefs('Fig. 30D')[0], records).length, 0);
assert.strictEqual(context.readingFigureCandidates(context.readingFigureRefs('Fig. 3C/D')[0], [records[0]]).length, 0);
const exact = {title:'第4页 图3D（一部分）',partial:true};
assert.deepStrictEqual(Array.from(context.readingFigureCandidates(refs[0], [...records,exact]),r=>r.title),[exact.title]);
assert.strictEqual(context.readingFigureCandidates(refs[0],[{title:'第4页 图3（一部分）',partial:true}]).length,0);
console.log('PASS figure references, tables, merged panels, wrong panel exclusion and number boundaries');

const grouped=context.readingFigureTree([
  {id:'a1',title:'Fig. 3A'}, {id:'a2',title:'Fig. 3A'},
  {id:'b',title:'Fig. 3B'}, {id:'one',title:'Fig. 1'},
  {id:'table',title:'Table 3'}, {id:'merged',title:'Fig. 3C/D'}
]);
assert.deepStrictEqual(Array.from(grouped,g=>g.label),['Fig 1','Fig 3','Table 3']);
const figure=grouped[1];
assert.deepStrictEqual(Array.from(figure.branches.keys()),['A','B','C/D']);
assert.deepStrictEqual(Array.from(figure.branches.get('A'),r=>r.id),['a1','a2']);
assert.strictEqual(grouped[2].branches.size,1);
console.log('PASS column tree grouping, numeric ordering, repeated subfigure records and combined region labels');
class Node {
  constructor(){this.children=[];this.attributes={};this.hidden=false;}
  appendChild(node){this.children.push(node);return node;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
}
const nodes=[],jumps=[];
const ui={document:{createElement(){const node=new Node();nodes.push(node);return node;},head:new Node(),body:new Node(),addEventListener(){}},
  figureRecords:[{id:'a1',title:'Fig. 3A'},{id:'a2',title:'Fig. 3A'}],
  state:{paras:[]},locateFigureRecord:record=>jumps.push(record.id)};
vm.createContext(ui);vm.runInContext(code,ui);
ui.openReadAlong(ui.readingFigureRefs('Fig. 3A')[0],0,new Node());
assert.strictEqual(jumps.length,0);
const branch=nodes.find(node=>node.textContent==='A');branch.onclick();
assert.deepStrictEqual(jumps,['a1']);
const second=nodes.filter(node=>node.textContent==='2').at(-1);second.onclick();
assert.deepStrictEqual(jumps,['a1','a2']);
console.log('PASS opening index preserves position, subfigure click jumps, numbered leaf selects exact record');
const pageWrap=new Node();
ui.state={sel:0,paras:[{text:'Fig. 3A. Fig. 3A. Fig. 3B.',rects:[{page:1,bbox:[10,20,40,60]}]}],sizes:{'1':[100,100]}};
ui.figureMode=false;
ui.pagesEl={querySelectorAll:()=>[],querySelector:()=>pageWrap};
const create=ui.document.createElement;
ui.document.createElement=()=>{const node=create();node.style={};return node;};
ui.paintReadAlongLinks();
assert.strictEqual(pageWrap.children.length,0);
const supplementary=context.readingFigureRefs('fig. S3A and Fig. 3D and Fig. 3D');
assert.strictEqual(supplementary[0].number,'S3');
const targets=context.paragraphFigureTargets(supplementary,[],[
  {kind:'caption',text:'Fig. 3. Grip force for objects.'},
  {kind:'caption',text:'Fig. S3. Supplementary setup.'}
]);
assert.strictEqual(targets.length,2);
assert.strictEqual(targets[0].captionIdx,1);
assert.strictEqual(targets[1].captionIdx,0);
assert.strictEqual(targets[1].indexRef.parts[0],'D');
assert.strictEqual(context.paragraphFigureTargets(supplementary,[],[])[0].unavailable,true);
const original=context.paragraphFigureTargets(supplementary,[{id:'exact',title:'Fig. 3D'}],[]);
assert.strictEqual(original[1].id,'exact');
console.log('PASS no extra page-edge entry, supplementary references, deduplication, parent caption fallback and exact selection priority');
assert.deepStrictEqual(Array.from(context.readingFigureRefs('(Fig. 3A, I)')[0].parts),['A']);
const auto=[];
ui.document.querySelector=()=>new Node();ui.formatMathText=value=>value;
ui.openReadAlong=(ref,idx)=>auto.push([ref.text,idx]);
ui.state.paras[0].kind='body';
ui.renderReadAlongLinks(0);
assert.strictEqual(auto.length,1);assert.strictEqual(auto[0][1],0);
console.log('PASS paragraph selection opens tree directly and roman step labels remain within subfigure A');
assert.strictEqual(context.hasMovieReference('see also movie S2'),true);
assert.strictEqual(context.hasMovieReference('normal paragraph'),false);
assert.strictEqual(context.supplementaryMaterialLocation([{text:'SUPPLEMENTARY MATERIALS'},{text:'Available at https://example.org/supplement'}]),1);
assert.strictEqual(context.supplementaryMaterialLocation([{text:'No linked materials'}]),-1);
const externalNodes=[];
ui.document.createElement=()=>{const node=new Node();node.style={};externalNodes.push(node);return node;};
ui.pagesEl.querySelector=()=>null;
ui.state.paras=[{kind:'body',text:'Fig. 3A and Fig. S3A, see movie S2.'},{kind:'caption',text:'Fig. 3. Main figure.'},{kind:'body',text:'Supplementary materials at https://example.org/supplement'}];
ui.figureRecords=[];
const destinations=[];ui.revealPara=idx=>destinations.push(idx);
vm.runInContext(code.slice(code.indexOf('function openReadAlong(')),ui);
ui.openReadAlong(ui.readingFigureRefs('Fig. 3A')[0],0,null);
assert(!externalNodes.some(node=>node.textContent==='Fig S3'));
const extension=externalNodes.filter(node=>node.textContent==='补充材料 · 图表／视频 ↗');
assert.strictEqual(extension.length,1);extension[0].onclick();assert.deepStrictEqual(destinations,[2]);
console.log('PASS missing figures and movies share one row linked to the document extension location');
for (const [text,step] of [['(Fig. 3A, I)','I'],['Fig. 12B, III)','III'],['Fig. 2a (iv)','iv'],['Fig. 8C, 2)','2'],['Fig. 5D (Ⅳ)','Ⅳ']]) {
  assert.strictEqual(context.readingFigureRefs(text)[0].step,step);
}
const steps=context.paragraphFigureTargets(context.readingFigureRefs('Fig. 3A, I). Fig. 3A, II). Fig. 3A, I).'),[],[{kind:'caption',text:'Fig. 3. Whole figure.'}]);
assert.deepStrictEqual(Array.from(steps,target=>target.indexRef.step),['I','II']);
const stepTree=context.readingFigureTree([
  {title:'Fig. 3A',indexRef:{type:'figure',number:'3',parts:['A'],step:''}},
  ...steps
]);
assert.deepStrictEqual(Array.from(stepTree[0].branches.get('A'),record=>record.indexRef.step),['I','II']);
vm.runInContext('readAlongCard.style={};',ui);
ui.state.paras=[{rects:[{page:4,bbox:[30,100,280,400]}]}];
ui.state.zoom=1;
const anchoredPage=new Node();ui.pagesEl.querySelector=()=>anchoredPage;
ui.positionReadAlong(0);
const floating=anchoredPage.children.at(-1);
assert.strictEqual(floating.style.left,'288px');assert.strictEqual(floating.style.top,'100px');
ui.state.zoom=2;ui.positionReadAlong(0);
assert.strictEqual(floating.style.left,'576px');assert.strictEqual(floating.style.top,'200px');
assert.strictEqual(floating.style.transform,'none');
assert.strictEqual(floating.style.width,'240px');
console.log('PASS source numeral styles, step deduplication, proportional anchor movement and fixed popup size');
