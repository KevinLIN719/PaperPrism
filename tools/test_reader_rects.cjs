const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('web/reader.html','utf8');
const code=html.slice(html.indexOf('function removeContainedRects('),html.indexOf('/* S3 版式诚实',html.indexOf('function removeContainedRects(')));
const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);
const r=(page,bbox)=>({page,bbox});
const outer=r(4,[36,145.7,293.2,566.5]);
const fragment=r(4,[258.4,288.7,293.2,302.5]);
for(const boxes of [[outer,fragment],[fragment,outer],[outer,outer]]) {
 const output=ctx.normalizeRects([{rects:boxes}])[0].rects;
 assert.strictEqual(output.length,1);assert.deepStrictEqual(Array.from(output[0].bbox),outer.bbox);
}
for(const extra of [r(5,fragment.bbox),r(4,[300,288,550,303]),r(4,[280,560,310,580])]) {
 assert.strictEqual(ctx.normalizeRects([{rects:[outer,extra]}])[0].rects.length,2);
}
const separate=ctx.normalizeRects([{rects:[outer]},{rects:[fragment]}]);
assert.strictEqual(separate[1].rects.length,1);
const actual=ctx.normalizeRects([{rects:[outer,fragment]}]);
assert.strictEqual(ctx.normalizeRects(actual)[0].rects.length,1);
console.log('PASS: real radical fragment removed; order-independent; duplicate cleanup; cross-page, column, partial overlap and distinct paragraphs preserved; idempotent');
