const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('web/reader.html','utf8');
const extract=name=>html.slice(html.indexOf('function '+name+'('),html.indexOf('\n}',html.indexOf('function '+name+'('))+2);
class Node {
 constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.style={};this.className='';this.open=false;this.listeners={};this.textContent='';}
 appendChild(n){this.children.push(n);return n;}
 replaceChildren(){this.children=[];this.textContent='';}
 setAttribute(k,v){this[k]=v;}
 addEventListener(name,fn){this.listeners[name]=fn;}
 querySelectorAll(selector){const nodes=this.children.flatMap(n=>[n,...n.querySelectorAll('*')]);if(selector==='*')return nodes;
  return nodes.filter(n=>selector.startsWith('.qhis') ? n.className==='qhis' && (!selector.includes('[open]') || n.open) : false);}
}
(async()=>{
 const nodes={'#askhist':new Node(),'#askq':{value:'new question'},'#askgo':new Node()};
 let resolveFetch;const ctx={$:s=>nodes[s],document:{createElement:t=>new Node(t)},state:{path:'paper',annoToken:1,sel:-1,summary:null,asks:[{id:'old',q:'old',a:'old answer',ts:1}]},
  renderAskAnswer:(root,record)=>root.textContent=record.a,usageAdd(){},saveStore:async()=>({ok:true}),fetch:()=>new Promise(resolve=>resolveFetch=resolve)};
 vm.createContext(ctx);
 for(const name of ['createRecordDeleteButton','renderAsks','askQuestion'])vm.runInContext((name==='askQuestion'?'async ':'')+extract(name),ctx);
 ctx.renderAsks('old');
 const request=ctx.askQuestion();
 let drawers=nodes['#askhist'].querySelectorAll('.qhis');
 assert.strictEqual(drawers.length,2);assert(drawers[0].open);assert(drawers[1].open);
 let body=drawers[0].children[1];assert(body.children[0].textContent.includes('正在阅读'));
 resolveFetch({ok:true,json:async()=>({record:{id:'new',q:'new question',a:'final answer',ts:2},answer:'final answer',meta:{}})});
 await request;
 drawers=nodes['#askhist'].querySelectorAll('.qhis');
 assert.strictEqual(drawers.length,2);assert(drawers[0].open);assert(drawers[1].open);
 assert.strictEqual(drawers[0].children[1].textContent,'final answer');
 assert.strictEqual(ctx.state.asks.length,2);assert.strictEqual(ctx.state.asks[0].id,'new');
 assert(!html.includes('id="askans"'));
 console.log('PASS pending drawer visible immediately; final answer rendered without toggle event; no duplicate bottom area; other open records preserved');
})().catch(error=>{console.error(error);process.exitCode=1});
