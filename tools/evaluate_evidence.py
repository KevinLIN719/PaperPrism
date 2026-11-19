"""真实论文金标：默认验证输入，--live运行模型并报告四分类与支持判定precision/recall。"""
import argparse
import base64
import datetime
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import claim_check  # noqa: E402
import figure_check  # noqa: E402
import llm  # noqa: E402
import m1_parse  # noqa: E402
from tools.migrate_parse_version import build_parse  # noqa: E402


def metrics(rows):
    judged = [r for r in rows if 'expected' in r]
    tp = sum(r.get('actual') == '支持' and r['expected'] == '支持' for r in judged)
    fp = sum(r.get('actual') == '支持' and r['expected'] != '支持' for r in judged)
    fn = sum(r.get('actual') != '支持' and r['expected'] == '支持' for r in judged)
    return {'count':len(judged),'exact':sum(r.get('actual') == r['expected'] for r in judged),
            'supported_tp':tp,'unsupported_passed':fp,'supported_missed':fn,
            'support_precision':tp/(tp+fp) if tp+fp else None,
            'support_recall':tp/(tp+fn) if tp+fn else None,
            'confusion':{gold:{actual:sum(r['expected'] == gold and r.get('actual') == actual for r in judged)
                               for actual in (*claim_check.STATUSES,'error')}
                         for gold in claim_check.STATUSES}}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--live',action='store_true')
    cli.add_argument('--only',choices=('text','figure'))
    args = cli.parse_args()
    gold = json.loads((ROOT/'tools/evidence_gold.json').read_text(encoding='utf-8'))
    figures = {s['id']:s for s in json.loads((ROOT/'tools/figure_samples.json').read_text(encoding='utf-8'))['samples']}
    prepared = []
    parses = {}
    for case in gold['text_samples'] if args.only != 'figure' else []:
        path = ROOT/case['path']
        if str(path) not in parses:
            parses[str(path)] = build_parse(str(path))
        matches = [p for p in parses[str(path)]['paras'] if ' '.join(case['source_hint'].split()) in ' '.join(p['text'].split())]
        if not matches:
            raise ValueError('找不到金标原文：'+case['id'])
        source = matches[0]
        prepared.append({**case,'type':'text','source':source['text'],'idx':source['i'],'page':source['page'],
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    for case in gold['figure_samples'] if args.only != 'text' else []:
        sample = figures[case['sample']]
        path = ROOT/sample['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample['sha256']:
            raise ValueError('图表PDF哈希不匹配')
        if str(path) not in parses:
            parses[str(path)] = build_parse(str(path))
        caption = next(p for p in parses[str(path)]['paras'] if p['page'] == sample['page']
                       and p['kind'] == 'caption' and p['text'].startswith(sample['caption_prefix']))
        with m1_parse.pymupdf.open(path) as doc:
            pix = doc[sample['page']-1].get_pixmap(matrix=m1_parse.pymupdf.Matrix(2,2),clip=m1_parse.pymupdf.Rect(sample['bbox']),alpha=False)
            url = 'data:image/png;base64,'+base64.b64encode(pix.tobytes('png')).decode()
        prepared.append({**case,'type':'figure','image':url,'sources':[{'idx':caption['i'],'page':caption['page'],'text':caption['text']}],
                         'path':sample['path'],'page':sample['page'],'bbox':sample['bbox'],'sha256':sample['sha256']})
    out = ROOT/'.tmp/evidence-evaluation'
    out.mkdir(parents=True,exist_ok=True)
    target = out/('run-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    cfg = llm.config() if args.live else None
    vision = llm.vision_config() if args.live else None

    def run(case):
        row = {k:v for k,v in case.items() if k != 'image'}
        if not args.live:
            row['status'] = 'input_validated'
            return row
        try:
            if case['type'] == 'text':
                result = claim_check.review({'idx':case['idx'],'claim':case['claim']},case['source'],cfg)
                row['actual'] = result['status']
                row['review'] = result
            else:
                facts,ground_usage = figure_check.ground_image(case['sources'],case['image'],vision)
                items,usage = figure_check.review({case['field']:case['text']},case['sources'],case['image'],vision,visual_facts=facts)
                usage = llm.merge_usage(ground_usage,usage)
                result = items.get(case['field'],{})
                row['actual'] = result.get('status','信息不足')
                row['review'] = result
                row['usage'] = usage
        except Exception as exc:
            row.update(actual='error',error=str(exc))
        print(row['id'],row['actual'],flush=True)
        return row

    rows = []
    # 仅并发独立模型请求，不写应用书库；每完成一例保存已有结果。
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(run,prepared):
            rows.append(row)
            target.write_text(json.dumps({'gold_version':gold['version'],'live':args.live,
                'summary':metrics(rows) if args.live else {},'rows':rows,
                'review_version':figure_check.VERSION,
                'ground_prompt_sha256':hashlib.sha256(figure_check.GROUND_SYSTEM.encode()).hexdigest(),
                'review_prompt_sha256':hashlib.sha256(figure_check.REVIEW_SYSTEM.encode()).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
    if args.live:
        print(json.dumps(metrics(rows),ensure_ascii=False))
    print('Results:',target)


if __name__ == '__main__':
    main()
