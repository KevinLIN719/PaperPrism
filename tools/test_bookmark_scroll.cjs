const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('web/reading-bookmark.js','utf8');
const extract=name=>source.slice(source.indexOf(`function ${name}(`),source.indexOf('\n}',source.indexOf(`function ${name}(`))+2);
const button={setAttribute(){},image:{}};
const saved={children:[],replaceChildren(){this.children=[];},appendChild(node){this.children.push(node);}};
let queued,frameCount=0,updates=0;
const context={bookmarkPage:1,readingBookmark:{bookmarks:[{page:1},{page:2},{page:2},{page:2}]},
  bookmarkSavedIcons:saved,bookmarkRail:{hidden:false},bookmarkAddButton:button,
  addBookmarkIcon:record=>({record}),requestAnimationFrame:fn=>{queued=fn;return ++frameCount;},updateBookmarkPage:()=>updates++};
vm.createContext(context);
vm.runInContext(extract('renderBookmarkRail'),context);
const image=button.image;
context.renderBookmarkRail();assert.strictEqual(saved.children.length,1);assert.strictEqual(button.hidden,false);
context.bookmarkPage=2;context.renderBookmarkRail();assert.strictEqual(saved.children.length,3);assert.strictEqual(button.hidden,true);
context.bookmarkPage=1;context.renderBookmarkRail();assert.strictEqual(button.image,image);assert.strictEqual(button.hidden,false);
vm.runInContext('let bookmarkScrollFrame=0;'+extract('scheduleBookmarkPageUpdate'),context);
for(let i=0;i<30;i++) context.scheduleBookmarkPageUpdate();
assert.strictEqual(frameCount,1);queued();assert.strictEqual(updates,1);
context.scheduleBookmarkPageUpdate();assert.strictEqual(frameCount,2);
context.state={notes:[{id:'one',idx:0},{id:'two',idx:1},{id:'missing',idx:8}],paras:[{page:1,rects:[{page:1},{page:2}]},{page:3,rects:[{page:3}]}]};
vm.runInContext(extract('bookmarkPageNotes'),context);
assert.deepStrictEqual(Array.from(context.bookmarkPageNotes(2),note=>note.id),['one']);
assert.deepStrictEqual(Array.from(context.bookmarkPageNotes(3),note=>note.id),['two']);
assert(source.includes('bookmarkRail.append(bookmarkSavedIcons,bookmarkAddSlot)'));
console.log('PASS persistent mascot across pages, full-page hiding, and scroll events coalesced per frame');
