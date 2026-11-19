const reproResourceKeys = ['equipment','time','background','goal'];
const resourceDetails = document.createElement('details');
resourceDetails.style.cssText='margin:10px 0;font-size:12px';
const resourceSummary = document.createElement('summary');resourceSummary.textContent='我的条件与目标（可选）';resourceDetails.appendChild(resourceSummary);
const resourceHint=document.createElement('p');resourceHint.className='hint';resourceHint.textContent='留空的条件会保留为未知。点击评估时，填写内容会与论文选段一起发送给已配置的模型。';resourceDetails.appendChild(resourceHint);
for (const [index,label] of ['设备／实验条件','可投入时间','已有基础','本次目标'].entries()) {
  const row=document.createElement('label');row.style.cssText='display:block;margin:8px 0';row.textContent=label;
  const input=document.createElement('textarea');input.id='resource-'+reproResourceKeys[index];input.maxLength=1000;input.rows=2;
  input.placeholder=['例如：笔记本、可用显卡、可访问的仪器或数据','例如：每周5小时，共两周','例如：掌握Python，刚开始学习材料实验','例如：先验证一张图中的趋势'][index];
  input.style.cssText='display:block;width:100%;padding:6px 8px;background:#fffdf8;color:var(--ink);border:1px solid var(--line);border-radius:6px;font:inherit';
  input.onchange=()=>{
    if (state.path) saveStore({repro_resources:readReproResources()},state.path);
    showDisciplineRepro();
  };
  row.appendChild(input);resourceDetails.appendChild(row);
}
$('#repro-evaluate').before(resourceDetails);
function readReproResources() {
  return Object.fromEntries(reproResourceKeys.map(key=>[key,$('#resource-'+key).value.trim()]));
}
function restoreReproResources(value) {
  for (const key of reproResourceKeys) $('#resource-'+key).value=typeof value?.[key] === 'string' ? value[key] : '';
  resourceDetails.open=Object.values(readReproResources()).some(Boolean);
}
function reproResourceCacheKey(discipline,resources=readReproResources()) {
  const values=reproResourceKeys.map(key=>resources[key]);
  return values.some(Boolean) ? discipline+'|'+JSON.stringify(values) : discipline;
}
