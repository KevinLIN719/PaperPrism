/* All API requests terminate here. No model endpoint or secret is shipped. */
(() => {
  const originalFetch=window.fetch.bind(window), cache=new Map();
  const catalog=()=>originalFetch('./catalog.json').then(r=>r.json());
  const reply=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
  async function load(path){
    const entries=await catalog(),item=entries.find(x=>path==='papers/'+x.id || path===x.id);
    if(!item)throw Error('仅提供三篇示例论文');
    if(!cache.has(item.id))cache.set(item.id,await originalFetch('./'+item.id+'.json').then(r=>r.json()));
    return cache.get(item.id);
  }
  function personal(id){try{return JSON.parse(localStorage.getItem('paperprism-browser-records:'+id)||'{}')}catch{return {}}}
  function bundle(d){const b={sha:d.id,file:d.file,parse:d.parse,summary:d.summary,annots:d.annots,figures:[d.figure],asks:[d.ask.record],notes:[],ask_reviews:d.ask.review?{[d.ask.review.id]:d.ask.review}:{}};return Object.assign(b,personal(d.id))}
  window.paperPrismDemo={load};
  window.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(!url.pathname.includes('/api/'))return originalFetch(input,options);
    const route=url.pathname.split('/api/')[1];
    let body={};try{body=JSON.parse(options.body||'{}')}catch{return reply({error:'体验版不支持文件上传'},403)}
    try{
      if(route==='health')return reply({ok:true,demo:true,usd_cny:7.1,llm:{model:'预生成缓存',key_set:false},zhihu:{}});
      if(route==='papers'){const items=await catalog();return reply({papers:await Promise.all(items.map(async x=>{const d=await load(x.id);return {path:'papers/'+x.id,name:x.field+' · '+x.title,kb:x.kb,cached:{annots:Object.keys(d.annots||{}).length,asks:1}}}))})}
      if(route==='library')return reply({library:[]});
      if(route==='open'){const d=await load(body.path);return reply({cached:true,sha:d.id,path:body.path,file:d.file,bundle:bundle(d)})}
      if(route==='explain'){const d=await load(body.path);return body.idx===d.idx?reply({cached:true,explanation:d.explanation}):reply({error:'此段尚无预生成讲解；实时 AI 已锁定，请查看本篇讲解示例或使用本地完整版。'},403)}
      if(route==='store'){
        const d=await load(body.path),p=personal(d.id);
        for(const k of ['reading_bookmark','reading_goal','reading_discipline','repro_resources'])if(k in body)p[k]=body[k];
        if(body.note)p.notes=[...(p.notes||[]),body.note];
        if(body.del_note)p.notes=(p.notes||[]).filter(n=>n.id!==body.del_note);
        // Preset AI examples stay available; only visitor-authored records are mutable.
        localStorage.setItem('paperprism-browser-records:'+d.id,JSON.stringify(p));
        return reply({ok:true,sha:d.id});
      }
      if(route==='figure-catalogue')return reply({items:[]});
      return reply({error:'浏览器体验版已锁定实时 AI 与联网操作，请查看预生成示例。完整版请从 github.com/KevinLIN719/PaperPrism 克隆到本地运行。'},403);
    }catch(e){return reply({error:e.message},400)}
  };
})();
