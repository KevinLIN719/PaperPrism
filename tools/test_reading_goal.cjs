const fs = require('fs'),vm=require('vm'),assert=require('assert');
const context={state:{},$:()=>({}),saveStore(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/reading-goal.js','utf8'),context);
const paras=[
 {kind:'body',page:1,text:'The problem is expensive classification.'},
 {kind:'body',page:2,text:'We propose a residual method.'},
 {kind:'body',page:6,text:'A limitation is the small sample size.'},
 {kind:'caption',page:4,text:'Figure 1. Comparison of error rates.'},
 {kind:'body',page:3,text:'The dataset and source code are available on github.'},
 {kind:'body',page:3,text:'Experimental setup: learning rate 0.1, batch size 32.'}
];
const annots={0:{role:'缺口'},1:{role:'方法'},2:{role:'局限'}};
const screen=context.buildTaskGuide(paras,annots,'screen');
const present=context.buildTaskGuide(paras,annots,'present');
const reproduce=context.buildTaskGuide(paras,annots,'reproduce');
assert(screen[0].candidates.some(c=>c.idx===0));
assert(present[1].candidates.some(c=>c.idx===3));
assert(reproduce[0].candidates.some(c=>c.idx===4));
assert(reproduce[1].candidates.some(c=>c.idx===5));
for(const route of [screen,present,reproduce]) {
 const ids=route.flatMap(s=>s.candidates.map(c=>c.idx));
 assert.strictEqual(new Set(ids).size,ids.length);
 ids.forEach(id=>assert(paras[id]));
}
const missing=context.buildTaskGuide([{kind:'body',page:1,text:'Ordinary unrelated prose.'}],{},'reproduce');
assert(missing.every(s=>s.candidates.length===0));
const invalid=context.buildTaskGuide(paras,annots,'invalid');
assert.deepStrictEqual(Array.from(invalid,s=>s.title),Array.from(screen,s=>s.title));
console.log('PASS: task-specific anchors, valid indices, no duplicate steps, no invented missing entry, default goal');

const nodes = {'#task-guide':{replaceChildren(){},textContent:''}, '#repro-workbench':{hidden:false}};
context.$=key=>nodes[key];context.state={paras:[],readingGoal:'screen'};
context.renderTaskGuide();assert.strictEqual(nodes['#repro-workbench'].hidden,true);
context.state.readingGoal='present';context.renderTaskGuide();assert.strictEqual(nodes['#repro-workbench'].hidden,true);
context.state.readingGoal='reproduce';context.renderTaskGuide();assert.strictEqual(nodes['#repro-workbench'].hidden,false);
console.log('PASS: reproduction module visible only for reproduce purpose');
