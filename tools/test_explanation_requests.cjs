const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('web/paragraph-explain.js','utf8');
let calls=0,usage=0,resolve;
const context={state:{path:'paper',annoToken:1},fetch:()=>{calls++;return new Promise(r=>resolve=r);},usageAdd:()=>usage++,saveStore:()=>{}};
vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('function renderLayeredExplanation')),context);
(async()=>{
  const first=context.requestParagraphExplanation('paper',2,1);
  const second=context.requestParagraphExplanation('paper',2,1);
  assert.strictEqual(first,second);assert.strictEqual(calls,1);
  resolve({ok:true,json:async()=>({explanation:{meta:{}},cached:false})});
  await Promise.all([first,second]);assert.strictEqual(usage,1);
  const failed=context.requestParagraphExplanation('paper',2,1);
  resolve({ok:false,json:async()=>({error:'failed'})});await assert.rejects(failed,/failed/);
  const retried=context.requestParagraphExplanation('paper',2,1);
  context.state.path='another';
  resolve({ok:true,json:async()=>({explanation:{meta:{}},cached:false})});await retried;
  assert.strictEqual(usage,1);assert.strictEqual(calls,3);
  console.log('PASS concurrent request deduplication, single usage count, retry and stale document guard');
})().catch(error=>{console.error(error);process.exitCode=1;});
