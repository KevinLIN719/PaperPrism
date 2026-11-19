"""固定图表样本：默认只验证PDF和选区；--live 才调用视觉模型。"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import figure  # noqa: E402
import figure_check  # noqa: E402
from tools.migrate_parse_version import build_parse  # noqa: E402


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--live', action='store_true', help='每个样本调用视觉模型（收费）')
    cli.add_argument('--render', action='store_true', help='输出选区PNG供人工复查')
    cli.add_argument('--only', nargs='+', help='只验证指定样本ID')
    args = cli.parse_args()
    samples = json.loads((ROOT/'tools/figure_samples.json').read_text(encoding='utf-8'))['samples']
    if args.only:
        unknown = set(args.only)-{s['id'] for s in samples}
        if unknown:
            cli.error('未知样本ID：'+','.join(sorted(unknown)))
        samples = [s for s in samples if s['id'] in args.only]
    out = ROOT/'.tmp/figure-evaluation'
    out.mkdir(parents=True, exist_ok=True)
    target = out/("run-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json" if args.live else "input-validation.json")
    results = []
    parses = {}
    for sample in samples:
        path = ROOT/sample['path']
        if not path.is_file():
            raise ValueError('缺少样本PDF：%s' % sample['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample['sha256']:
            raise ValueError('样本PDF内容已改变：%s' % sample['path'])
        with figure.m1_parse.pymupdf.open(path) as doc:
            page = doc[sample['page']-1]
            w, h = page.rect.width, page.rect.height
            bounds = [v/(w if i%2 == 0 else h) for i,v in enumerate(sample['bbox'])]
            figure.validate_region({'page':sample['page'],'bounds':bounds},len(doc))
            if args.render:
                page.get_pixmap(matrix=figure.m1_parse.pymupdf.Matrix(2,2),clip=figure.m1_parse.pymupdf.Rect(sample['bbox'])).save(str(out/(sample['id']+'.png')))
        row = {'id':sample['id'],'checks':sample['checks'],'status':'input_validated',
               'review_version':figure_check.VERSION,
               'review_prompt_sha256':hashlib.sha256(figure_check.REVIEW_SYSTEM.encode()).hexdigest(),
               'ground_prompt_sha256':hashlib.sha256(figure_check.GROUND_SYSTEM.encode()).hexdigest(),
               'prompt_sha256':hashlib.sha256(figure.SYSTEM.encode('utf-8')).hexdigest()}
        if args.live:
            if str(path) not in parses:
                parses[str(path)] = build_parse(str(path))
            parsed = parses[str(path)]
            caption = next(p for p in parsed['paras'] if p['kind']=='caption' and p['page']==sample['page'] and p['text'].startswith(sample['caption_prefix']))
            context = {'caption':{'idx':caption['i']}, 'paragraphs':[]}
            response = figure.explain(str(path),parsed,{'page':sample['page'],'bounds':bounds,'context':context})
            row.update(status='model_returned',response=response)
        results.append(row)
        # 每个样本完成即保存，后续失败时仍可查到前面的结果；不写应用书库。
        target.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(sample['id'],row['status'],flush=True)
    print('Results:',target)


if __name__ == '__main__':
    main()
