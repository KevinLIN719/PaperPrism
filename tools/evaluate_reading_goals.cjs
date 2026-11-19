/* 同篇真实书库的三个阅读任务必须给出不同入口，且每条入口有有效页码与热区。 */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const ctx={state:{},$:()=>({}),saveStore(){}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/reading-goal.js','utf8'),ctx);
const names=['resnet_1512.03385.pdf','aay5120.pdf','science.1133687.pdf'];
const books=fs.readdirSync('store').filter(f=>f.endsWith('.json')).map(f=>JSON.parse(fs.readFileSync(path.join('store',f),'utf8')));
const output=[];
for(const name of names){
  const book=books.find(d=>d.path&&d.path.endsWith(name));
  assert(book?.parse,`missing real paper cache: ${name}`);
  const routes={};
  for(const goal of ['screen','present','reproduce']){
    routes[goal]=ctx.buildTaskGuide(book.parse.paras,book.annots||{},goal).map(step=>({
      title:step.title,question:step.question,candidates:step.candidates.map(c=>{
        const p=book.parse.paras[c.idx];
        assert(p&&p.text===c.text&&p.page===c.page);
        assert(p.rects?.length&&p.rects.every(r=>r.page>=1&&r.bbox.length===4));
        assert(book.parse.page_sizes?.[c.page-1]||book.parse.page_sizes?.[c.page]);
        return {idx:c.idx,page:c.page,kind:p.kind,text:p.text.slice(0,250)};
      })
    }));
    assert(routes[goal].some(s=>s.candidates.length),`${name}/${goal} has no anchor`);
  }
  const signature=g=>JSON.stringify(routes[g].flatMap(s=>s.candidates.map(c=>c.idx)));
  assert.notStrictEqual(signature('screen'),signature('present'));
  assert.notStrictEqual(signature('screen'),signature('reproduce'));
  assert.notStrictEqual(signature('present'),signature('reproduce'));
  assert(routes.present[1].candidates.some(c=>c.kind==='caption'));
  output.push({paper:name,routes});
}
fs.mkdirSync('.tmp',{recursive:true});
fs.writeFileSync('.tmp/reading-goals-real.json',JSON.stringify(output,null,2));
for(const item of output){
  console.log(item.paper);
  for(const [goal,steps] of Object.entries(item.routes))console.log(goal,steps.map(s=>s.candidates.map(c=>`${c.idx}@p${c.page}`).join(',')||'unknown').join(' / '));
}
console.log('PASS: three real papers, distinct task anchors, valid page geometry, optional reproduction path');
