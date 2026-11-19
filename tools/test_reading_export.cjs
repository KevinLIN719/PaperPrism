const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('web/reading-export.js','utf8');
const context={};vm.createContext(context);vm.runInContext(code.slice(0,code.indexOf('const exportButton')),context);
const document=context.buildReadingExport({title:'论文 <script>alert(1)</script>',date:'2026-11-19',
  paras:[{page:2,text:'Current source changed.'}],summary:{tl_dr:['概括'],claims:[{claim:'作者假设',idx:0,strength:'中'}]},
  notes:[{text:'我的批注',idx:0}],bookmarks:[{page:4,question:'一个未解问题',color:'#ffffff',text:'Original bookmark text.'}],
  asks:[{q:'问题',a:'回答 #8',evidence:{legacy:false,invalid:[8],cited:[3],sources:[{idx:3,page:5,text:'Original answer input.'}]}},{pending:true,q:'进行中'}],
  figures:[{title:'图3D（一部分）',bounds:[.1,.2,.3,.4],result:{reading:'轴的含义',limits:'样本量未知'},sources:[{page:5,text:'Original caption.'}]}]});
const markdown=context.readingExportMarkdown(document),html=context.readingExportHTML(document);
for(const text of ['我的批注','一个未解问题','样本量未知','来源未核实','Original answer input.','Original bookmark text.','Original caption.','第 5 页']) {
  assert(markdown.includes(text));assert(html.includes(text));
}
assert(!markdown.includes('进行中'));
assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));
assert.strictEqual(document.sources.filter(s=>s.text==='Current source changed.').length,1);
for(const source of document.sources) assert(html.includes(`id="${source.id}"`));
assert(markdown.includes('旧记录待核对'));
const empty=context.buildReadingExport({title:'Empty',date:'today',paras:[]});assert.strictEqual(empty.sections.length,0);
console.log('PASS exports keep source snapshots, page references and uncertainty, deduplicate sources, omit pending answers and escape HTML');
