"""Generate a sanitized static showcase; never export personal reading history or settings."""
import concurrent.futures
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import llm
import m1_parse
import paragraph_explain
import ask_pipeline
import figure

OUT = ROOT / 'browser-demo' / 'dist'
SPECS = [
    ('bdfaa68d8984', '计算机 · 深度学习', 'Attention Is All You Need', 7, '为什么这个架构可以比循环神经网络更容易并行训练？', 3),
    ('9af82b90f2a9', '经济学 · 劳动生产率', 'Generative AI at Work', 5, '这篇研究中，AI 对不同经验水平员工的影响是否一样？研究结果有哪些适用边界？', 37),
    ('f73d1ffb2a15', '机器人 · 自适应系统', 'Resilient Machines Through Continuous Self-Modeling', 5, '机器人如何在身体受损后恢复运动？这是否意味着它具有人的自我意识？', 4),
]


def build(spec):
    sha, field, title, idx, question, page = spec
    source = json.loads((ROOT / 'store' / (sha + '.json')).read_text(encoding='utf-8'))
    parsed = source['parse']
    cache = OUT / (sha + '.json')
    data = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    data.update(id=sha, field=field, title=title, file=source['file'], parse=parsed, summary=source.get('summary'), annots=source.get('annots', {}), idx=idx, question=question)
    def save():
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    save()
    pdf = ROOT / 'demo_papers' / source['file']
    shutil.copy2(pdf, OUT / source['file'])
    if page == 37 and not any(p['page'] == page for p in parsed['paras']):
        with m1_parse.pymupdf.open(str(pdf)) as doc:
            text = doc[page-1].get_text()
        parsed['paras'].append({'i':max(p['i'] for p in parsed['paras'])+1,'page':page,'kind':'caption','text':text,'rects':[]})
        data['parse'] = parsed
        save()
    if not data.get('explanation'):
        data['explanation'] = paragraph_explain.complete(paragraph_explain.sources_for(parsed, idx), llm.config())
        save()
        print(title, 'explanation ready', flush=True)
    if not data.get('ask'):
        data['ask'] = ask_pipeline.complete(parsed, question, idx=idx, summary=source.get('summary'))
        save()
        print(title, 'ask ready', flush=True)
    if not data.get('figure'):
        existing = source.get('figures') or []
        if existing:
            record = existing[0]
        else:
            bounds = [0.10, 0.08, 0.90, 0.58] if page == 3 else [0.04, 0.03, 0.96, 0.94]
            caption = next((p for p in parsed['paras'] if p['page'] == page and p['kind'] == 'caption'), None)
            related = [p for p in parsed['paras'] if 'figure 2' in p['text'].lower()][:4] if page == 37 else []
            payload = {'page':page, 'bounds':bounds, 'context':{'caption':{'idx':caption['i']} if caption else {},'paragraphs':[{'idx':p['i']} for p in related]}}
            record = figure.explain(str(pdf), parsed, payload)['record']
        data['figure'] = record
        save()
        print(title, 'figure ready', flush=True)
    with m1_parse.pymupdf.open(str(pdf)) as doc:
        record = data['figure']
        p = doc[record['page']-1]
        b = record['bounds']
        clip = m1_parse.pymupdf.Rect(b[0]*p.rect.width,b[1]*p.rect.height,b[2]*p.rect.width,b[3]*p.rect.height)
        p.get_pixmap(matrix=m1_parse.pymupdf.Matrix(1.7,1.7), clip=clip).save(str(OUT / (sha+'.png')))
    return {'id':sha,'field':field,'title':title}


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'web' / 'vendor', OUT / 'vendor', dirs_exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(build, SPECS))
    (OUT / 'catalog.json').write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
    from package_browser_demo import package
    package()
    print('Static demo cache complete', flush=True)
