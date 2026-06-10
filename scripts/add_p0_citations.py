#!/usr/bin/env python3
"""一次性加 5 筆 P0 疾病權威引用到 citations.json"""
import json
from pathlib import Path

CITATIONS = Path(__file__).parent.parent / "content" / "references" / "citations.json"

NEW = {
    "PEDERSEN-2019-FIP-GS441524": {
        "title": "Efficacy and safety of the nucleoside analog GS-441524 for treatment of cats with naturally occurring feline infectious peritonitis",
        "title_zh": "GS-441524 治療貓自然感染 FIP 的療效與安全性研究",
        "authors": "Niels C Pedersen, Michel Perron, Michael Bannasch, Elizabeth Montgomery, Eisuke Murakami, Molly Liepnieks, Hongwei Liu",
        "source": "JFMS",
        "journal": "Journal of Feline Medicine and Surgery",
        "url": "https://pubmed.ncbi.nlm.nih.gov/30755068/",
        "doi": "10.1177/1098612X19825701",
        "pmid": "30755068",
        "pmcid": "PMC6435921",
        "year": 2019,
        "type": "research_paper",
        "language": "en",
        "open_access": True,
        "sample_size": 31,
        "study_design": "前瞻性田野試驗（field trial）+ 臨床監測，中位年齡 13.6 個月",
        "abstract_zh": "Pedersen 團隊（UC Davis）對 31 隻自然感染 FIP 的貓進行 GS-441524 治療試驗：\n\n■ 樣本：3.4–73 個月齡，26 隻濕型/混合型，5 隻乾型；嚴重神經/眼部症狀者排除\n■ 起始劑量 2.0 mg/kg SC q24h ≥ 12 週；最終確認最佳劑量為 4.0 mg/kg SC q24h ≥ 12 週\n■ 主要結果：\n  - 26/31 完成首輪療程\n  - 18/26 一輪治癒、長期健康\n  - 8/26 復發（3–84 天內），其中 2 隻為神經症狀復發\n  - 5 隻提高劑量（4.0 mg/kg）二輪治療成功；2 隻三輪治療仍存活\n  - 整體 24/31（77%）達持續健康\n■ 限制：樣本量中等、神經型/眼型未涵蓋、非隨機對照、藥物當時為非合法管道",
        "keywords": [
            "GS-441524",
            "FIP",
            "Pedersen",
            "antiviral",
            "feline infectious peritonitis"
        ],
        "disease_tags": ["fip"],
        "status": "approved",
        "url_verified": True,
        "verified_at": "2026-04-29",
        "notes": "GS-441524 治療 FIP 的 landmark 論文。Pedersen 團隊首次公開系統性療效資料，台灣 2024 後合法化引用最常用的原始來源。",
        "cited_by": []
    },
    "FOX-2018-HCM-REVEAL": {
        "title": "International collaborative study to assess cardiovascular risk and evaluate long-term health in cats with preclinical hypertrophic cardiomyopathy and apparently healthy cats: The REVEAL Study",
        "title_zh": "REVEAL 研究：貓臨床前肥厚型心肌病與健康貓的心血管長期風險國際合作研究",
        "authors": "Philip R Fox, Bruce W Keene, Kenneth Lamb, Karsten A Schober, et al. (50+ collaborators)",
        "source": "JVIM",
        "journal": "Journal of Veterinary Internal Medicine",
        "url": "https://pubmed.ncbi.nlm.nih.gov/29660848/",
        "doi": "10.1111/jvim.15122",
        "pmid": "29660848",
        "pmcid": "PMC5980443",
        "year": 2018,
        "type": "research_paper",
        "language": "en",
        "open_access": True,
        "sample_size": 1730,
        "study_design": "回顧性多中心縱向 cohort 研究，跨 21 國，醫療紀錄 + 飼主/獸醫追訪",
        "abstract_zh": "REVEAL 研究是 HCM 至今最大規模的國際 cohort：\n\n■ 樣本：1,730 隻飼主貓 — 430 隻非阻塞型 HCM、578 隻阻塞型 HOCM、722 隻健康對照\n■ 主要結果：1,008 隻 HCM/HOCM 中：\n  - 30.5% 出現 CHF（充血性心衰）/ ATE（動脈血栓栓塞）/ 兩者\n  - 27.9% 心血管死亡\n  - CHF 發生率 1/5/10 年累計：7.0% / 19.9% / 23.9%\n  - ATE 發生率 1/5/10 年累計：3.5% / 9.7% / 11.3%\n  - 出現心衰/血栓後中位存活：1.3 ± 1.7 年\n■ 阻塞型 vs 非阻塞型 HCM：morbidity / mortality 無顯著差異\n■ 僅 10% 臨床前 HCM 貓活到 9–15 歲\n■ 結論：臨床前 HCM 是全球性貓健康問題，需發展早期介入策略",
        "keywords": [
            "REVEAL",
            "HCM",
            "hypertrophic cardiomyopathy",
            "cohort",
            "Fox",
            "preclinical"
        ],
        "disease_tags": ["hcm"],
        "status": "approved",
        "url_verified": True,
        "verified_at": "2026-04-29",
        "notes": "HCM 預後最具代表性的大型 cohort 研究，常被 ACVIM 2020 共識引用。",
        "cited_by": []
    },
    "SPARKES-2016-ISFM-CKD": {
        "title": "ISFM Consensus Guidelines on the Diagnosis and Management of Feline Chronic Kidney Disease",
        "title_zh": "ISFM 貓慢性腎病診斷與管理共識指引（2016）",
        "authors": "Andrew H Sparkes, Sarah Caney, Serge Chalhoub, Jonathan Elliott, Natalie Finch, Isuru Gajanayake, Catherine Langston, Hervé P Lefebvre, Joanna White, Jessica Quimby",
        "source": "JFMS",
        "journal": "Journal of Feline Medicine and Surgery",
        "url": "https://pubmed.ncbi.nlm.nih.gov/26936494/",
        "doi": "10.1177/1098612X16631234",
        "pmid": "26936494",
        "year": 2016,
        "volume": "18(3):219-239",
        "type": "consensus_guideline",
        "language": "en",
        "open_access": True,
        "study_design": "ISFM 專家共識（10 位作者跨 UK / US / 加拿大 / 法國），整合 IRIS 分期框架",
        "abstract_zh": "ISFM 2016 CKD 共識指引（核心臨床參考之一）：\n\n■ CKD 是老年貓最常見診斷之一，個體間差異極大、需個人化處置\n■ 強調定期重新評估療效，平衡生活品質與證據導向介入\n■ 涵蓋：\n  - 早期偵測（SDMA、UPC、血壓）\n  - IRIS 分期應用於治療選擇\n  - 飲食磷限制（核心介入）\n  - 水分補充策略（鼓勵飲水 > 強制皮下輸液）\n  - 高血壓與蛋白尿的併發症處置\n  - 終末期生活品質決策\n■ 結論：CKD 病程多變，需依個體情況持續調整，而非套用固定方案",
        "keywords": [
            "ISFM",
            "CKD",
            "chronic kidney disease",
            "consensus",
            "Sparkes",
            "IRIS"
        ],
        "disease_tags": ["ckd"],
        "status": "approved",
        "url_verified": True,
        "verified_at": "2026-04-29",
        "notes": "ISFM 官方共識，與 IRIS 分期互為核心臨床指引。",
        "cited_by": []
    },
    "BUFFINGTON-2014-PANDORA-FLUTD": {
        "title": "From FUS to Pandora syndrome: where are we, how did we get here, and where to now?",
        "title_zh": "從 FUS 到 Pandora 症候群：FLUTD 概念演進與系統性壓力觀點",
        "authors": "C A Tony Buffington, Jodi L Westropp, Dennis J Chew",
        "source": "JFMS",
        "journal": "Journal of Feline Medicine and Surgery",
        "url": "https://pubmed.ncbi.nlm.nih.gov/24794035/",
        "doi": "10.1177/1098612X14530212",
        "pmid": "24794035",
        "pmcid": "PMC11104043",
        "year": 2014,
        "volume": "16(5):385-394",
        "type": "review_article",
        "language": "en",
        "open_access": True,
        "study_design": "回顧性綜述（40 年文獻整合）",
        "abstract_zh": "Buffington 團隊（Ohio State）提出 Pandora 症候群框架，重新定位 FLUTD：\n\n■ 過去 40 年觀念變遷：FUS（feline urologic syndrome）→ FLUTD → FIC（feline idiopathic cystitis）→ Pandora\n■ 核心論點：膀胱不一定是「病因」，而是「全身性壓力反應系統敏感化」的受害者之一\n■ Pandora 症候群特徵：\n  - 中樞壓力反應系統長期失調\n  - 對環境變化的耐受範圍變窄\n  - 同一隻貓可能同時有膀胱、腸胃、皮膚、行為等多系統症狀\n■ 對臨床啟示：環境豐富化、降低壓力源、多重感官介入（MEMO）優先於單純膀胱用藥\n■ 影響：成為 ISFM/AAFP 後續 FLUTD 指引的觀念基礎",
        "keywords": [
            "Pandora",
            "FLUTD",
            "FIC",
            "Buffington",
            "stress",
            "feline idiopathic cystitis",
            "lower urinary tract"
        ],
        "disease_tags": ["flutd", "behavior"],
        "status": "approved",
        "url_verified": True,
        "verified_at": "2026-04-29",
        "notes": "FLUTD 病因學的觀念基石，從「膀胱病」轉向「系統性壓力症候群」。",
        "cited_by": []
    },
    "BEHREND-2018-AAHA-DIABETES": {
        "title": "2018 AAHA Diabetes Management Guidelines for Dogs and Cats",
        "title_zh": "2018 AAHA 犬貓糖尿病管理指引",
        "authors": "Ellen Behrend, Amy Holford, Patty Lathan, Renee Rucinsky, Rhonda Schulman",
        "source": "JAAHA",
        "journal": "Journal of the American Animal Hospital Association",
        "url": "https://pubmed.ncbi.nlm.nih.gov/29314873/",
        "doi": "10.5326/JAAHA-MS-6822",
        "pmid": "29314873",
        "year": 2018,
        "volume": "54(1):1-21",
        "type": "consensus_guideline",
        "language": "en",
        "open_access": True,
        "study_design": "AAHA 專家工作小組共識指引（更新 2010 版本）",
        "abstract_zh": "AAHA 2018 糖尿病指引（更新 2010 版）：\n\n■ 胰島素治療為臨床糖尿病核心\n■ 胰島素種類選擇、非胰島素藥物（口服降糖）、飲食策略討論\n■ 飼主教育重點：注射技巧、低血糖辨識、居家血糖監測\n■ 「控制良好」定義：臨床症狀減少 + 避免低血糖（不必強求血糖數值正常）\n■ 強調區分：真正糖尿病 vs 暫時性高血糖（壓力性 / 類固醇誘發），避免不必要治療\n■ 與 ISFM-DIABETES-2015 互補：ISFM 偏貓專科觀點，AAHA 為犬貓綜合臨床指引",
        "keywords": [
            "AAHA",
            "diabetes",
            "Behrend",
            "insulin",
            "remission",
            "glucose monitoring"
        ],
        "disease_tags": ["diabetes"],
        "status": "approved",
        "url_verified": True,
        "verified_at": "2026-04-29",
        "notes": "美國動物醫院協會官方指引，與 ISFM 2015 共識互補使用。",
        "cited_by": []
    },
}


def main():
    raw = json.loads(CITATIONS.read_text(encoding="utf-8"))
    meta = raw.pop("_meta", None)

    added, skipped = [], []
    for cid, entry in NEW.items():
        if cid in raw:
            skipped.append(cid)
        else:
            raw[cid] = entry
            added.append(cid)

    # restore _meta first
    out = {}
    if meta is not None:
        out["_meta"] = meta
    out.update(raw)

    # update meta totals
    if meta is not None:
        out["_meta"]["total"] = len(raw)
        out["_meta"]["approved"] = sum(1 for v in raw.values() if v.get("status") == "approved")

    CITATIONS.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Add] {len(added)} 新加: {added}")
    if skipped:
        print(f"[Skip] {len(skipped)} 已存在: {skipped}")
    print(f"[Total] citations: {len(raw)}")


if __name__ == "__main__":
    main()
