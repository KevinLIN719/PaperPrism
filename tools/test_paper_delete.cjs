const fs=require('fs'),vm=require('vm'),assert=require('assert');
async function test(){
  const nodes={};
  const $=key=>nodes[key]||(nodes[key]={value:'',checked:false,disabled:false,textContent:'',
    addEventListener(){},showModal(){this.open=true;},close(){this.open=false;}});
  let requests=[],reloads=0,lists=0,fail=false,resolve;
  const ctx={$,state:{path:'papers/first.pdf',annoToken:4},location:{reload(){reloads++;}},
    loadList:async()=>{lists++;},fetch:async(url,options)=>{
      requests.push([url,JSON.parse(options.body)]);
      await new Promise(r=>{resolve=r;});
      return {ok:!fail,json:async()=>fail?{error:'failed'}:{ok:true}};
    }};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/paper-delete.js','utf8'),ctx);
  $('#pick').value='papers/first.pdf';$('#delete-paper').onclick();
  assert.strictEqual($('#delete-keep-records').checked,true);
  $('#pick').value='papers/other.pdf';
  const event={preventDefault(){}};
  const running=$('#delete-paper-form').onsubmit(event);
  await $('#delete-paper-form').onsubmit(event);
  assert.strictEqual(requests.length,1);
  assert.strictEqual(requests[0][1].path,'papers/first.pdf');
  assert.strictEqual(requests[0][1].keep_records,true);
  resolve();await running;assert.strictEqual(reloads,1);assert.strictEqual(ctx.state.annoToken,5);
  $('#pick').value='papers/other.pdf';$('#delete-paper').onclick();
  $('#delete-keep-records').checked=false;fail=true;
  const failure=$('#delete-paper-form').onsubmit(event);resolve();await failure;
  assert.strictEqual(requests[1][1].keep_records,false);
  assert.strictEqual($('#delete-paper-error').textContent,'failed');
  assert.strictEqual(reloads,1);assert.strictEqual(lists,0);
  assert.strictEqual($('#delete-paper-confirm').disabled,false);
  console.log('PASS default keep, fixed target, duplicate submission, erase option, failure preserves UI');
}
test().catch(e=>{console.error(e);process.exitCode=1;});
