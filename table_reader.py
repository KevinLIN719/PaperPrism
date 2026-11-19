"""原生文字表格阅读；明确续表且列标题一致时合并，不推断缺失单元格。"""
import re

import figure_catalogue
import m1_parse


def normalized(box, page):
    return [max(0, min(1, value / (page.rect.width if n % 2 == 0 else page.rect.height)))
            for n, value in enumerate(box)]


def clean(value):
    return str(value or '').strip()


def header_key(cells):
    # 保留大小写与单位，仅消除排版空白。
    return [re.sub(r'\s+', '', cell) for cell in cells]


def extract_segment(page, item, tables):
    segment = {'idx':item['idx'], 'page':item['page'], 'caption':item['caption'],
               'header':[], 'rows':[], 'bounds':None, 'warning':''}
    regions = [m1_parse.pymupdf.Rect([
        value * (page.rect.width if n % 2 == 0 else page.rect.height)
        for n, value in enumerate(region['bounds'])])
        for region in item['regions'] if region['page'] == item['page']]
    candidates = []
    for table in tables:
        box = m1_parse.pymupdf.Rect(table.bbox)
        coverage = max(((box & region).get_area() / max(1, box.get_area()) for region in regions), default=0)
        if coverage >= .9:
            candidates.append(table)
    if not candidates:
        # 有些解析只保留表注框；只接受同栏紧邻且唯一的原生表格。
        nearby = []
        for table in tables:
            box = m1_parse.pymupdf.Rect(table.bbox)
            for region in regions:
                gap = min(abs(box.y0-region.y1), abs(region.y0-box.y1))
                if (region.height < 80 and gap <= 60 and abs(box.x0-region.x0) <= 12
                        and min(box.x1,region.x1)-max(box.x0,region.x0) >= .8*region.width):
                    nearby.append(table)
                    break
        if len(nearby) == 1:
            candidates = nearby
    if len(candidates) != 1:
        segment['warning'] = '当前范围未定位到唯一的原生文字表格，请查看原页。'
        return segment
    table = candidates[0]
    segment['bounds'] = normalized(table.bbox, page)
    cells = [[clean(cell) for cell in row] for row in table.extract()]
    if not cells or sum(len(row) for row in cells) > 5000:
        segment['warning'] = '表格为空或结构过大，请查看原页。'
        return segment
    names = [clean(name) for name in table.header.names]
    # 数值首行可能被提取器误当作列名，不能据此移除数据或合并续页。
    reliable = (len(names) >= 2 and all(name and re.search(r'[^\W\d_]', name, re.UNICODE) for name in names)
                and len(set(header_key(names))) == len(names))
    offset = 0
    if reliable:
        segment['header'] = names
        if not table.header.external and header_key(cells[0]) == header_key(names):
            offset = 1
    for position, row in enumerate(cells[offset:], offset):
        boxes = [box for box in table.rows[position].cells if box]
        box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else table.bbox
        segment['rows'].append({'cells':row, 'page':item['page'], 'bounds':normalized(box, page)})
    # 合并单元格保留空位、按页显示，不猜测跨行／跨列的继承关系。
    merged_cells = any(cell is None for row in table.extract() for cell in row)
    if not reliable:
        segment['warning'] = '未确认完整列标题，保留本页原始行。'
    elif merged_cells or any(len(row) != len(names) for row in cells):
        segment['warning'] = '存在合并单元格或不规则列，保留分页面貌。'
    elif any(sum('\n' in cell for cell in row) >= 2 for row in cells[offset:]):
        segment['warning'] = '多个单元格包含多行内容，可能挤入多条数据；保留分页面貌，请对照原页。'
    return segment


def assemble(segments):
    if not segments:
        raise ValueError('未找到表格页面')
    header = segments[0]['header']
    compatible = bool(header) and all(
        not segment['warning'] and header_key(segment['header']) == header_key(header)
        for segment in segments)
    result = {'segments':segments, 'mode':'merged' if compatible else 'separate',
              'header':header if compatible else [],
              'rows':[row for segment in segments for row in segment['rows']] if compatible else []}
    result['message'] = ('已按原文列标题整理，重复表头仅显示一次；数据行均保留。' if compatible else
                         '各页列标题、单位或提取结构未能确认一致，已分开显示。')
    return result


def read_table(path, parsed, idx):
    items = figure_catalogue.catalogue(path, parsed)
    by_idx = {item['idx']:item for item in items}
    target = by_idx.get(idx)
    if target is None or target['kind'] != 'table':
        raise ValueError('请选择自动目录中的表格')
    group = {idx}
    pending = [idx]
    while pending:
        current = by_idx[pending.pop()]
        for other in current['continuations']:
            if other not in group:
                group.add(other)
                pending.append(other)
    selected = sorted((by_idx[i] for i in group), key=lambda item:(item['page'], item['idx']))
    if len(selected) > 12:
        raise ValueError('续表超过12页，请分段查看原页')
    # 同一页同号表注有歧义时，不选择其中一张冒充完整续表。
    if len({item['page'] for item in selected}) != len(selected):
        raise ValueError('同页存在多处同号表注，请分别查看原页确认')
    segments = []
    with m1_parse.pymupdf.open(path) as doc:
        for item in selected:
            page = doc[item['page'] - 1]
            try:
                found = page.find_tables()
                segment = extract_segment(page, item, found.tables)
            except (ValueError, RuntimeError, AttributeError, IndexError, TypeError):
                segment = {'idx':item['idx'], 'page':item['page'], 'caption':item['caption'],
                           'header':[], 'rows':[], 'bounds':None,
                           'warning':'本页原生表格提取未完成，请查看原页。'}
            segments.append(segment)
    return {'label':target['label'], **assemble(segments),
            'note':'仅提取PDF原生文字，不调用模型或OCR。空单元格按原样保留，表下注释及复杂结构请查看原页。'}
