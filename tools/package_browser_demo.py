"""Package the original reader unchanged in style, with a browser-local API adapter."""
from pathlib import Path
import shutil
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'browser-demo' / 'dist'


def package():
    catalog = json.loads((OUT / 'catalog.json').read_text(encoding='utf-8'))
    for item in catalog:
        data = json.loads((OUT / (item['id']+'.json')).read_text(encoding='utf-8'))
        item['kb'] = round((OUT / data['file']).stat().st_size / 1024)
    (OUT / 'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
    for source in (ROOT / 'web').iterdir():
        if source.is_dir():
            shutil.copytree(source, OUT / source.name, dirs_exist_ok=True)
        elif source.suffix in ('.css', '.js'):
            text = source.read_text(encoding='utf-8').replace("'/assets/", "'./assets/").replace('"/assets/', '"./assets/')
            (OUT / source.name).write_text(text, encoding='utf-8')
    html = (ROOT / 'web/reader.html').read_text(encoding='utf-8')
    html = html.replace('src="/', 'src="./').replace('href="/', 'href="./')
    html = html.replace('"/vendor/', '"./vendor/').replace('"/pdf/" + pdfRel', '"./" + encodeURIComponent(window.demoCurrent.file)')
    html = html.replace('<title>', '<title>浏览器体验版 · ')
    html = html.replace('</head>', '<script src="./demo-adapter.js"></script></head>')
    html = html.replace('if (annoLeft) pending.set', 'if (false && annoLeft) pending.set')
    html = html.replace('  maybeZhihu();   //', '  // 静态体验版不触发联网搜索。\n  // maybeZhihu();   //')
    html = html.replace('  loadList();\n  bindDrop();\n  initDemo();', '  loadList().then(run);\n  initDemo();')
    html = html.replace('</body>', '<script src="./demo-controls.js"></script></body>')
    html = html.replace('点击解读后，选区截图与相关正文会发送给配置的视觉模型。解读记录保存到本地书库，仅保留选区坐标与文字，不保存截图。', '浏览器体验版已锁定实时图表解读。下方预生成记录可展开查看，并回到原文选区核对；不会发送截图或调用模型。')
    (OUT / 'index.html').write_text(html, encoding='utf-8')
    print('Packaged original reader with static adapter')


if __name__ == '__main__':
    package()
