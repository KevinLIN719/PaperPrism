const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
  constructor() { this.style={}; this.events={}; this.classList={add(){},remove(){}}; }
  append() {} appendChild() {} setAttribute() {} setPointerCapture() {} releasePointerCapture() {}
  hasPointerCapture() { return false; }
  addEventListener(name, fn) { this.events[name]=fn; }
}
const nodes = [], selections = [], drawer = {scrollIntoView(){}};
let hit = null;
const context = {
  document:{createElement(){ const node=new Element(); nodes.push(node); return node; }, head:new Element(),body:new Element(),addEventListener(){},elementsFromPoint(){return hit ? [hit] : [];}},
  pagesEl:{querySelectorAll(){return [];}},
  state:{doc:{},path:'paper',sel:0,paras:[{},{}]}, figureMode:false,
  select(idx){selections.push(idx);}, $(selector){return selector === '#panel' ? new Element() : drawer;}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/kanshan.js','utf8'),context);
const handle = nodes.find(node => node.id === 'kanshan-handle');
const event = (x,y) => ({button:0,pointerId:1,clientX:x,clientY:y});
handle.events.pointerdown(event(0,0));
hit={matches:()=>true,dataset:{i:'1'}};
handle.events.pointermove(event(50,50));
assert.strictEqual(selections.length,0);
handle.events.pointerup(event(50,50));
assert.deepStrictEqual(selections,[1]); assert.strictEqual(drawer.open,true);
handle.events.pointerdown(event(0,0)); hit=null;
handle.events.pointermove(event(40,40)); handle.events.pointerup(event(40,40));
assert.strictEqual(selections.length,1);
handle.events.pointerdown(event(0,0)); handle.events.pointercancel(); handle.events.pointerup(event(0,0));
assert.strictEqual(selections.length,1);
handle.onclick({detail:0}); assert.deepStrictEqual(selections,[1,0]);
context.figureMode=true; context.syncKanshan();
assert.strictEqual(nodes.find(node=>node.id==='kanshan').hidden,true);
console.log('PASS drag preview makes no request; drop selects once; blank/cancel ignored; keyboard entry; figure mode hides pet');
