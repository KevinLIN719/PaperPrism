const fs=require('fs'),vm=require('vm'),assert=require('assert');
const escape=s=>String(s||'').replaceAll('<','&lt;').replaceAll('>','&gt;');
const ctx={state:{paras:[{page:2,text:'Error is 25.03% under condition A. <script>'}]},escapeHtml:escape,formatMathText:escape};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/claim-evidence.js','utf8'),ctx);
assert(ctx.claimSource({idx:0,quote:'Error is 25.03%'},ctx.state.paras).matched);
assert(!ctx.claimSource({idx:0,quote:'Error is 24.03%'},ctx.state.paras).matched);
assert(!ctx.claimSource({idx:99},ctx.state.paras).matched);
const old=ctx.renderClaimEvidence({idx:0,claim:'old',evidence:'note',strength:'中'});
assert(old.includes('来源段落 · 待核对'));assert(old.includes('&lt;script&gt;'));assert(!old.includes('<script>'));
assert(!old.includes('class="claim-evidence" open'));
const matched=ctx.renderClaimEvidence({idx:0,quote:'Error is 25.03%',statement_type:'作者陈述'});
assert(matched.includes('原文摘录 · 核对支持关系'));assert(matched.includes('作者陈述'));
console.log('PASS exact text match, wrong quote rejection, legacy fallback, escaping and collapsed evidence');

ctx.state.claimReviews={a:{id:'a',idx:0,claim:'claim',source_text:ctx.state.paras[0].text,status:'部分支持',reason:'limited to A',quote:'Error is 25.03%',meta:{model:'test'}}};
assert(ctx.claimReviewMarkup({idx:0,claim:'claim'}).includes('部分支持'));
assert(ctx.claimReviewMarkup({idx:0,claim:'different'}).includes('旧摘要未内置自动复核'));
ctx.state.paras[0].text='Source changed';assert(ctx.claimReviewMarkup({idx:0,claim:'claim'}).includes('旧摘要未内置自动复核'));
console.log('PASS persisted review reused only for matching claim and source');
