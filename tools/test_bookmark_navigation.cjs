const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('web/reading-bookmark.js','utf8');
const start=code.indexOf('async function revealReadingBookmark('),end=code.indexOf('\nfunction openBookmarkEditor',start);
const calls=[];
const scroll={scrollTop:0,getBoundingClientRect:()=>({top:10})};
const context={figureRecords:[{id:'figure'}],state:{paras:[{text:'same',page:2},{text:'same',page:4}]},
  locateFigureRecord:r=>calls.push(r.id),revealPara:async idx=>calls.push(idx),$:()=>scroll,
  pagesEl:{querySelector:()=>({clientHeight:1000,getBoundingClientRect:()=>({top:110})})}};
vm.createContext(context);vm.runInContext(code.slice(start,end),context);
(async()=>{
  const mark={page:4,text:'same',figureId:'figure',offset:.4};
  await context.revealReadingBookmark(mark);assert.deepStrictEqual(calls,['figure']);
  context.figureRecords=[];await context.revealReadingBookmark(mark);assert.deepStrictEqual(calls,['figure',1]);
  context.state.paras=[];await context.revealReadingBookmark(mark);assert.strictEqual(scroll.scrollTop,500);
  console.log('PASS existing figure, deleted figure to same-page paragraph, changed paragraph to saved page offset');
})().catch(error=>{console.error(error);process.exitCode=1;});
