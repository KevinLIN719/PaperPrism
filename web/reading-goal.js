/* 首版任务导读：从已有段落与批注组织可核对的阅读入口，不新增模型调用。 */
const READING_TASKS = {
  screen: [
    {title:'先判断研究问题是否与你有关', question:'作者想解决什么问题？现有方法哪里不够？', roles:['缺口','背景'], terms:/\b(problem|challenge|limitation|however|we address)\b|问题|挑战|不足|缺口/i},
    {title:'再看作者提出了什么', question:'核心做法是什么，相比已有方法改在哪里？', roles:['方法'], terms:/\b(we propose|we present|our approach|our method|contribution)\b|提出|贡献|本文方法/i},
    {title:'最后核对适用范围与局限', question:'结论在哪些条件下成立？值得继续精读吗？', roles:['局限'], terms:/\b(limitation|future work|fails? to|restricted to|not applicable)\b|局限|尚不能|不适用|未来工作/i},
  ],
  present: [
    {title:'组织问题到方法的讲解', question:'用自己的话讲清为什么做、怎么做。', roles:['缺口','方法'], terms:/\b(we propose|we address|our approach|contribution)\b|研究问题|提出|贡献/i},
    {title:'选关键图表讲证据', question:'这张图比较了什么？如何支持作者的主张？', kind:'caption', terms:/\b(results?|comparison|accuracy|performance|error|force)\b|结果|比较|性能|误差|力/i},
    {title:'准备讨论与质疑', question:'哪些假设、局限或实验条件值得在讨论中追问？', roles:['局限'], terms:/\b(limitation|assumption|assume|future work)\b|假设|局限|未来工作/i},
  ],
  reproduce: [
    {title:'先核对数据和实现入口', question:'数据、代码在哪里？能否获得相同输入？', terms:/\b(dataset|source code|github|code is available|data availability|data are available)\b|数据集|源代码|代码公开|数据可用/i},
    {title:'再定位实验设置与评测口径', question:'超参数、预处理、训练或实验条件、评价指标交代清楚了吗？', terms:/\b(hyperparameter|learning rate|batch size|experimental setup|implementation details|evaluation metric|embedding depth|grip speed)\b|超参数|学习率|批量大小|实验设置|评测|嵌入深度|夹持速度/i},
    {title:'确定最小验证目标与风险', question:'先验证哪项结果？缺失条件会不会阻碍复现？', roles:['局限'], terms:/\b(ablation|limitation|reproduc|not available)\b|消融|局限|复现|未公开/i},
  ],
};
function buildTaskGuide(paras, annots, goal) {
  const used = new Set();
  let heading = '';
  const sections = paras.map(p => {
    if (p && p.kind === 'heading') heading = p.text || '';
    return heading;
  });
  return (READING_TASKS[goal] || READING_TASKS.screen).map(step => {
    const candidates = paras.map((p,i) => {
      if (!p || p.kind !== (step.kind || 'body') || used.has(i)) return null;
      const a = annots[i] || {};
      const role = (step.roles || []).includes(a.role);
      const term = step.terms.test(p.text || '');
      // 复现设置等具体入口必须有内容线索，不能任意拿方法段充数。
      if (!role && !term && step.kind !== 'caption') return null;
      return {idx:i, page:p.page, text:p.text, one:a.one_line || '',
        score:(role ? 20 : 0)+(term ? 10 : 0)
          +(goal === 'reproduce' && /implementation|experiment|dataset|evaluation|实验|实现|数据集|评估/i.test(sections[i]) ? 15 : 0)
          +(goal === 'reproduce' && /github\.com|code is available|data availability|源代码|代码公开/i.test(p.text) ? 15 : 0)};
    }).filter(Boolean).sort((a,b) => b.score-a.score || a.idx-b.idx).slice(0,1);
    candidates.forEach(c => used.add(c.idx));
    return {...step,candidates};
  });
}
function renderTaskGuide() {
  const root = $('#task-guide'); if (!root) return;
  root.replaceChildren();
  const goal = state.readingGoal || 'screen';
  const repro = $('#repro-workbench'); if (repro) repro.hidden = goal !== 'reproduce';
  if (!state.paras.length) {
    root.textContent = '打开论文后，这里会给出与你的阅读目的对应的优先步骤。'; return;
  }
  const intro = document.createElement('p'); intro.className = 'hint';
  intro.textContent = '建议按以下顺序阅读；点入口核对原文，完整段落顺序仍在「路线」。'; root.appendChild(intro);
  for (const [index, step] of buildTaskGuide(state.paras,state.annots || {},goal).entries()) {
    const section = document.createElement('div'); section.style.cssText = 'margin:12px 0';
    const title = document.createElement('b'); title.textContent = `${index+1}. ${step.title}`; section.appendChild(title);
    const question = document.createElement('p'); question.className = 'hint'; question.style.margin='3px 0'; question.textContent=step.question; section.appendChild(question);
    if (!step.candidates.length) {
      const empty = document.createElement('p'); empty.className='hint';
      empty.textContent = '暂未定位到明确入口，请结合原文核查。'; section.appendChild(empty);
    }
    for (const candidate of step.candidates) {
      const jump = document.createElement('button'); jump.className='claim'; jump.style.width='100%';
      const text = document.createElement('span'); text.textContent = candidate.one || candidate.text.slice(0,150)+(candidate.text.length>150 ? '…' : ''); jump.appendChild(text);
      const source = document.createElement('em'); source.textContent=`第 ${candidate.page} 页 · 阅读候选`; jump.appendChild(source);
      jump.onclick = () => revealPara(candidate.idx); section.appendChild(jump);
    }
    root.appendChild(section);
  }
}
$('#reading-goal').onchange = () => {
  state.readingGoal = $('#reading-goal').value;
  renderTaskGuide();
  if (state.path) saveStore({reading_goal:state.readingGoal},state.path);
};
