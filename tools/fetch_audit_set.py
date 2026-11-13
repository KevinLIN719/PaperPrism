# -*- coding: utf-8 -*-
"""A 部分测试集：按 9 类版式抓 30-50 篇开放获取 PDF 到 papers_audit/。

只抓开放获取来源（arXiv / ACL Anthology / NeurIPS / PMLR / CVF / PLOS /
Nature Communications / APS / NBER / Archive.org 扫描件 / 中文开放期刊）。
不回传 PDF 本身，只回传解析指标——见任务书 3.1「不要提交受版权限制的 PDF」。

用法：
    python tools/fetch_audit_set.py              # 抓全部缺失的
    python tools/fetch_audit_set.py --list       # 只列清单不下载
"""

import argparse
import concurrent.futures as cf
import io
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "papers_audit")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

# (类别, 文件名, URL, 一句话说明)
# 类别编号对应任务书 3.1 的 9 类
CANDIDATES = [
    # --- 1 单栏/双栏常见会议论文 ---
    (1, "c1_acl_bart.pdf", "https://aclanthology.org/2020.acl-main.703.pdf", "ACL 双栏"),
    (1, "c1_acl_p19.pdf", "https://aclanthology.org/P19-1285.pdf", "ACL 2019 双栏"),
    (1, "c1_emnlp22.pdf", "https://aclanthology.org/2022.emnlp-main.759.pdf", "EMNLP 双栏"),
    (1, "c1_naacl21.pdf", "https://aclanthology.org/2021.naacl-main.41.pdf", "NAACL 双栏"),
    (1, "c1_cvpr_mae.pdf", "https://openaccess.thecvf.com/content/CVPR2022/papers/He_Masked_Autoencoders_Are_Scalable_Vision_Learners_CVPR_2022_paper.pdf", "CVPR 双栏图多"),
    (1, "c1_cvpr_fpn.pdf", "https://openaccess.thecvf.com/content_cvpr_2017/papers/Lin_Feature_Pyramid_Networks_CVPR_2017_paper.pdf", "CVPR 双栏"),
    (1, "c1_iccv_maskrcnn.pdf", "https://openaccess.thecvf.com/content_ICCV_2017/papers/He_Mask_R-CNN_ICCV_2017_paper.pdf", "ICCV 双栏"),
    (1, "c1_neurips_alexnet.pdf", "https://proceedings.neurips.cc/paper_files/paper/2012/file/c399862d3b9d6b76c8436e924a68c45b-Paper.pdf", "NeurIPS 单栏老模板"),
    (1, "c1_pmlr_clip.pdf", "https://proceedings.mlr.press/v139/radford21a/radford21a.pdf", "PMLR 单栏长文"),
    (1, "c1_jmlr.pdf", "https://www.jmlr.org/papers/volume23/21-0998/21-0998.pdf", "JMLR 单栏"),

    # --- 2 三栏 / 期刊紧凑版式 ---
    (2, "c2_nature_alphafold.pdf", "https://www.nature.com/articles/s41586-021-03819-2.pdf", "Nature 多栏"),
    (2, "c2_nature_2019.pdf", "https://www.nature.com/articles/s41586-019-1666-5.pdf", "Nature 多栏"),
    (2, "c2_natcomm.pdf", "https://www.nature.com/articles/s41467-021-21210-7.pdf", "Nature Comm 双栏"),
    (2, "c2_natsr.pdf", "https://www.nature.com/articles/s41598-021-99269-x.pdf", "Sci Rep 单栏"),
    (2, "c2_aps_ligo.pdf", "https://link.aps.org/pdf/10.1103/PhysRevLett.116.061102", "PRL 双栏物理"),
    (2, "c2_aps_prx.pdf", "https://link.aps.org/pdf/10.1103/PhysRevX.8.031084", "PRX 双栏"),

    # --- 3 首字下沉 / 期刊首页特殊排版 ---
    (3, "c3_plos_one.pdf", "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0270275&type=printable", "PLOS ONE 双栏"),
    (3, "c3_plos_cb.pdf", "https://journals.plos.org/ploscompbiol/article/file?id=10.1371/journal.pcbi.1008865&type=printable", "PLOS CB 双栏"),

    # --- 4 脚注多 ---
    (4, "c4_nber_w31161.pdf", "https://www.nber.org/system/files/working_papers/w31161/w31161.pdf", "NBER 脚注密集"),
    (4, "c4_nber_w30957.pdf", "https://www.nber.org/system/files/working_papers/w30957/w30957.pdf", "NBER 脚注密集"),
    (4, "c4_nber_w29649.pdf", "https://www.nber.org/system/files/working_papers/w29649/w29649.pdf", "NBER 脚注密集"),
    (4, "c4_nber_w28393.pdf", "https://www.nber.org/system/files/working_papers/w28393/w28393.pdf", "NBER 脚注密集"),

    # --- 5 参考文献 + 附录都很长（30 页以上） ---
    (5, "c5_llm_survey.pdf", "https://arxiv.org/pdf/2303.18223", "LLM 综述 100+ 页"),
    (5, "c5_gpt4.pdf", "https://arxiv.org/pdf/2303.08774", "GPT-4 报告 附录长"),
    (5, "c5_llama2.pdf", "https://arxiv.org/pdf/2307.09288", "Llama2 77 页"),
    (5, "c5_palm.pdf", "https://arxiv.org/pdf/2204.02311", "PaLM 83 页"),
    (5, "c5_opt.pdf", "https://arxiv.org/pdf/2205.01068", "OPT 附录多"),

    # --- 6 一个 PDF 里排了两篇（期刊合订/带 SI 的预印本包） ---
    (6, "c6_bstj_shannon1.pdf", "https://archive.org/download/bstj27-3-379/bstj27-3-379.pdf", "BSTJ 期刊抽印"),
    (6, "c6_bstj_shannon2.pdf", "https://archive.org/download/bstj27-4-623/bstj27-4-623.pdf", "BSTJ 期刊抽印"),

    # --- 7 扫描件 / 图片型 PDF（无文本层） ---
    (7, "c7_scan_bstj.pdf", "https://archive.org/download/bstj37-1-1/bstj37-1-1.pdf", "老期刊扫描"),
    (7, "c7_scan_ia2.pdf", "https://archive.org/download/bstj28-4-656/bstj28-4-656.pdf", "老期刊扫描"),

    # --- 8 中英混排 / 中文期刊 ---
    (8, "c8_aas_c210555.pdf", "http://www.aas.net.cn/cn/article/pdf/preview/10.16383/j.aas.c210555.pdf", "自动化学报"),
    (8, "c8_aas_c200739.pdf", "http://www.aas.net.cn/cn/article/pdf/preview/10.16383/j.aas.c200739.pdf", "自动化学报"),
    (8, "c8_aas_c190495.pdf", "http://www.aas.net.cn/cn/article/pdf/preview/10.16383/j.aas.c190495.pdf", "自动化学报"),
    (8, "c8_aas_c200954.pdf", "http://www.aas.net.cn/cn/article/pdf/preview/10.16383/j.aas.c200954.pdf", "自动化学报"),
    (8, "c8_crad_202330746.pdf", "https://crad.ict.ac.cn/cn/article/pdf/preview/10.7544/issn1000-1239.202330746.pdf", "计算机研究与发展"),
    (8, "c8_crad_202440123.pdf", "https://crad.ict.ac.cn/cn/article/pdf/preview/10.7544/issn1000-1239.202440123.pdf", "计算机研究与发展"),
    (8, "c8_arxiv_cjk.pdf", "https://arxiv.org/pdf/2402.14973", "中英混排 arXiv"),

    # --- 9 跨栏 / 跨页续段密集 ---
    (9, "c9_neurips_transformer.pdf", "https://proceedings.neurips.cc/paper_files/paper/2017/file/3f5ee243547dee91fbd053c1c4a845aa-Paper.pdf", "NeurIPS 单栏"),
    (9, "c9_arxiv_swin.pdf", "https://arxiv.org/pdf/2103.14030", "Swin 双栏图多"),
    (9, "c9_arxiv_detr.pdf", "https://arxiv.org/pdf/2005.12872", "DETR"),
    (9, "c9_arxiv_vit.pdf", "https://arxiv.org/pdf/2010.11929", "ViT"),
    (9, "c9_arxiv_bahdanau.pdf", "https://arxiv.org/pdf/1409.0473", "2014 老模板"),
    (9, "c9_arxiv_clip_rn.pdf", "https://arxiv.org/pdf/1409.1556", "VGG 双栏"),
    (9, "c9_arxiv_gan.pdf", "https://arxiv.org/pdf/1406.2661", "GAN 单栏"),
    (9, "c9_arxiv_dropout.pdf", "https://arxiv.org/pdf/1207.0580", "Dropout 短文"),
]


def fetch(item):
    cat, name, url, note = item
    path = os.path.join(OUT, name)
    if os.path.isfile(path) and os.path.getsize(path) > 20000:
        return (cat, name, note, "cached", os.path.getsize(path))
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as f:
            data = f.read()
    except Exception as exc:
        return (cat, name, note, "FAIL %s %s" % (type(exc).__name__, str(exc)[:50]), 0)
    if data[:5] != b"%PDF-":
        return (cat, name, note, "not-pdf", len(data))
    io.open(path, "wb").write(data)
    return (cat, name, note, "downloaded", len(data))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    if args.list:
        for cat, name, url, note in CANDIDATES:
            print("%d  %-32s %s" % (cat, name, note))
        print("共 %d 个候选" % len(CANDIDATES))
        return
    results = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(fetch, CANDIDATES):
            results.append(r)
            print("类%d %-32s %-10s %7d  %s" % (r[0], r[1], r[3][:10], r[4], r[2]))
    ok = [r for r in results if r[3] in ("cached", "downloaded")]
    print("\n成功 %d / %d" % (len(ok), len(results)))
    io.open(os.path.join(OUT, "_fetch_log.json"), "w", encoding="utf-8").write(
        json.dumps([{"cat": r[0], "file": r[1], "note": r[2], "status": r[3], "bytes": r[4]}
                    for r in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
