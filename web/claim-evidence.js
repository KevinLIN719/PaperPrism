/* 原文摘录匹配与来源段落回退；不把字面匹配当作语义支持验证。 */
function claimSource(claim, paras) {
  const p = paras[claim.idx];
  if (!p) return {matched:false, text:'', page:null};
  const normalize = text => String(text || '').replace(/\s+/g,' ').trim();
  const quote = normalize(claim.quote);
  const matched = !!quote && normalize(p.text).includes(quote);
  return {matched, text:matched ? quote : p.text, page:p.page};
}
function renderClaimEvidence(claim) {
  const source = claimSource(claim,state.paras);
  const type = ['作者陈述','系统解释','待确认'].includes(claim.statement_type) ? claim.statement_type : '待确认';
  const heading = `<button class="claim" data-i="${claim.idx}"><b>${escapeHtml(claim.claim)}</b><span>${escapeHtml(claim.evidence)}</span><em>${type} · 强度 ${escapeHtml(claim.strength)} · 第 ${source.page || '—'} 页</em></button>`;
  const label = claim.support_review ? '原文依据与处理说明' : source.matched ? '原文摘录 · 核对支持关系' : '来源段落 · 待核对';
  const extra = (claim.evidence_sources || []).slice(1).map(s => `<div class="source-quote">${formatMathText(s.quote)}</div><button class="cite" data-i="${s.idx}">第 ${s.page} 页 · 原文</button>`).join('');
  const note = claim.support_review ? '本条已在后台对照原文处理，以下保留依据与模型说明，供需要时追溯。' : source.matched ? '摘录已在对应段落中找到；请核对它是否支持上述主张及其适用条件。' : '这条记录没有可匹配的原文摘录，以下展示来源段落，供你核对。';
  return `<div class="claim-item">${heading}<details class="claim-evidence"><summary>${label}</summary><p class="hint">${note}</p><div class="source-quote">${source.text ? formatMathText(source.text) : '来源段落不可用，请重新生成摘要。'}</div>${extra}<div class="support-review" data-claim-idx="${claim.idx}">${claimReviewMarkup(claim)}</div></details></div>`;
}


function savedClaimReview(claim) {
  const source = state.paras[claim.idx];
  return Object.values(state.claimReviews || {}).find(r => r.idx === claim.idx && r.claim === claim.claim
    && source && r.source_text === source.text);
}
function claimReviewMarkup(claim) {
  const review = claim.support_review ? {...claim.support_review,quote:claim.quote,meta:{model:claim.support_review.model}} : savedClaimReview(claim);
  if (!review) return '<p class="hint">旧摘要未内置自动复核；重跑摘要后会自动对照原文处理。</p>';
  return `<p><b>模型复核：${escapeHtml(review.status)}</b></p><p>${escapeHtml(review.reason)}</p>
    ${review.quote ? `<div class="source-quote">${formatMathText(review.quote)}</div>` : ''}
    <p class="hint">对照以上原文辅助处理；模型复核仍可能出错，不代表主张已被事实认证。模型：${escapeHtml(review.meta.model)}</p>`;
}
