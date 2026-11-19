const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/ask-evidence.js','utf8'),ctx);
const paras=[{page:1,text:'one'},{page:2,text:'two'},{page:3,text:'three'}];
const current=ctx.askCitationState({citation_version:1,a:'答案 [#0] [#2] [#99]',sources:[{idx:0,page:1,text:'one'},{idx:1,page:2,text:'two'}]},paras);
assert.deepStrictEqual(Array.from(current.cited),[0]);assert.deepStrictEqual(Array.from(current.invalid),[2,99]);
assert.strictEqual(current.sources.length,2);assert.strictEqual(current.legacy,false);
const legacy=ctx.askCitationState({a:'答案 [#1] [#1] #9',used:[0]},paras);
assert.strictEqual(legacy.legacy,true);assert.deepStrictEqual(Array.from(legacy.cited),[1]);assert.deepStrictEqual(Array.from(legacy.invalid),[9]);
console.log('PASS citation/input distinction, out-of-context references, duplicates and legacy fallback');

ctx.state={askReviews:{review:{ask_id:'q',answer:'answer',sources:[{idx:0,text:'source'}]}}};
const saved={id:'q',a:'answer',sources:[{idx:0,text:'source'}]};
assert(ctx.savedAskReview(saved));assert(!ctx.savedAskReview({...saved,a:'changed'}));
assert(!ctx.savedAskReview({...saved,sources:[{idx:0,text:'changed'}]}));
console.log('PASS per-answer review reuse requires same record, answer and snapshots');
