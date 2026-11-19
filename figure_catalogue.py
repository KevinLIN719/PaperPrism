"""基于图注及已有几何信息生成候选目录，子图仅定位可识别标签。"""
import re
import m1_parse


def catalogue(path, parsed):
    items=[]
    with m1_parse.pymupdf.open(path) as doc:
        for idx, para in enumerate(parsed['paras']):
            match=re.match(r'^\s*(Fig(?:ure)?\.?|Table|图|表)\s*(S?\d+)\b',para.get('text',''),re.I)
            if para.get('kind')!='caption' or not match:
                continue
            kind='table' if match[1].lower().startswith('table') or match[1]=='表' else 'figure'
            regions=para.get('figure_rects') or para.get('rects') or []
            pages=sorted({int(r['page']) for r in regions})
            item={'idx':idx,'kind':kind,'number':match[2].upper(),'label':('Table ' if kind=='table' else 'Fig ')+match[2].upper(),
                  'page':para['page'],'caption':para['text'],'regions':[],'panels':[],
                  'continued':bool(re.search(r'continu(?:ed|ation)|续表|接上页',para['text'][:140],re.I))}
            for region in regions:
                page_no=int(region['page'])
                if not 1<=page_no<=len(doc):continue
                page=doc[page_no-1];box=region['bbox'];width,height=page.rect.width,page.rect.height
                if len(box)!=4 or box[0]>=box[2] or box[1]>=box[3]:continue
                normalized=[max(0,min(1,v/(width if n%2==0 else height))) for n,v in enumerate(box)]
                item['regions'].append({'page':page_no,'bounds':normalized})
                for block in page.get_text('dict',clip=m1_parse.pymupdf.Rect(box)).get('blocks',[]):
                    block_text=' '.join(span['text'] for line in block.get('lines',[]) for span in line.get('spans',[])).strip()
                    if re.match(r'^(?:Fig(?:ure)?\.?|Table|图|表)\s*S?\d+\b',block_text,re.I):
                        continue
                    for line in block.get('lines',[]):
                        line_text=''.join(span['text'] for span in line.get('spans',[])).strip('(). ')
                        for span in line.get('spans',[]):
                            label=span['text'].strip('(). ')
                            if line_text==label and re.fullmatch('[A-Z]',label) and span.get('flags',0)&16:
                                candidate={'label':label,'page':page_no,'bbox':span['bbox']}
                                if not any(p['label']==label and p['page']==page_no for p in item['panels']):item['panels'].append(candidate)
            item['panels']=sorted(item['panels'],key=lambda p:(p['page'],p['label'])) if len(item['panels'])>=2 else []
            item['pages']=pages
            items.append(item)
    # 同号续表只在相邻页且明确标有continued/续表时关联。
    for item in items:
        item['continuations']=[other['idx'] for other in items if other is not item and item['kind']=='table' and other['kind']=='table'
            and item['number']==other['number'] and abs(item['page']-other['page'])==1 and (item['continued'] or other['continued'])]
    return items
