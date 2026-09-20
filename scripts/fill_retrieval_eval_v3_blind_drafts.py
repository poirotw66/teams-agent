"""Fill retrieval_eval_v3_blind draft slots from corpus (no model output)."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BLIND_PATH = REPO / "data" / "eval" / "retrieval_eval_v3_blind.json"
V2_PATH = REPO / "data" / "eval" / "retrieval_eval_v2.json"


def _case(
    case_id: str,
    *,
    categories: list[str],
    query: str,
    expected_found: bool,
    expected_documents: list[str] | None = None,
    expected_evidence: list[dict] | None = None,
    hard_negatives: list[str] | None = None,
    notes: str = "",
    groups: list[str] | None = None,
    prior_turn: str | None = None,
) -> dict:
    docs = list(expected_documents or [])
    payload: dict = {
        "id": case_id,
        "categories": categories,
        "query": query,
        "expectedFound": expected_found,
        "expectedDocuments": docs,
        "expectedSourceTitles": list(docs),
        "expectedEvidence": list(expected_evidence or []),
        "hardNegatives": list(hard_negatives or []),
        "forbiddenSourceTitles": [],
        "relevanceGrades": {},
        "groups": list(groups or []),
        "notes": notes,
        "split": "blind",
        "labelStatus": "draft_pending_review",
    }
    if prior_turn:
        payload["priorTurn"] = prior_turn
        payload["notes"] = f"{notes}; priorTurn={prior_turn}".strip("; ")
    return payload


def build_drafts() -> list[dict]:
    drafts: list[dict] = []

    # --- Answerable (corpus-grounded) ---
    answerable = [
        ("v3-blind-ans-09", "外網要用 CRM 該怎麼設定連線？", "外網 CRM 登入連線設定方式", ["外網", "CRM", "連線"]),
        ("v3-blind-ans-10", "國金 CRM 的 OTP 要怎麼綁定？", "國金 CRM OTP 綁訂操作", ["OTP", "綁"]),
        ("v3-blind-ans-11", "登入 FortiClient 出現錯訊要看哪份說明？", "登入 FortiClient 出現錯訊", ["FortiClient", "錯訊"]),
        ("v3-blind-ans-12", "VPN 跳板機連線異常怎麼排查？", "VPN 跳板機連線異常", ["跳板", "異常"]),
        ("v3-blind-ans-13", "內網筆電連 VPN 有問題怎麼辦？", "內網筆電 VPN 連線問題", ["內網", "VPN"]),
        ("v3-blind-ans-14", "要申請 VPN 國外短暫連線怎麼做？", "VPN國外連線短暫申請", ["國外", "申請"]),
        ("v3-blind-ans-15", "分公司 CS 團隊 VPN 權限列表在哪？", "分公司CS團隊VPN連線可使用權限列表", ["CS", "權限"]),
        ("v3-blind-ans-16", "同仁要申請共用公槽資料夾流程？", "同仁申請共用公槽資料夾", ["公槽", "申請"]),
        ("v3-blind-ans-17", "座位搬遷需求要怎麼提出？", "座位搬遷需求", ["座位", "搬遷"]),
        ("v3-blind-ans-18", "總公司 IP 話機怎麼操作？", "總公司IP話機操作", ["IP話機", "操作"]),
        ("v3-blind-ans-19", "Webex 會議要借用可錄影帳號怎麼辦？", "Webex會議借用-可錄影", ["Webex", "錄影"]),
        ("v3-blind-ans-20", "郵件變成亂碼怎麼處理？", "郵件為亂碼", ["亂碼", "郵件"]),
        ("v3-blind-ans-21", "資訊問題通報要用什麼格式？", "資訊問題的通報格式", ["通報", "格式"]),
        ("v3-blind-ans-22", "PowerPivot 相關問題文件在哪？", "PowerPivot", ["PowerPivot"]),
        ("v3-blind-ans-23", "樹精靈 AP 無法登入怎麼辦？", "樹精靈AP無法登入", ["樹精靈", "登入"]),
        ("v3-blind-ans-24", "超音樹程式閃退怎麼處理？", "超音樹-程式閃退問題", ["超音樹", "閃退"]),
        ("v3-blind-ans-25", "大州系統功能無法點選要看哪份？", "大州系統_功能無法點選", ["大州", "無法點選"]),
        ("v3-blind-ans-26", "大州首次使用要做哪些設定？", "大州首次使用設定", ["大州", "首次"]),
        ("v3-blind-ans-27", "XQ 系統常見問題有哪些文件？", "XQ問題", ["XQ"]),
        ("v3-blind-ans-28", "外部客戶線上問題怎麼處理？", "外部客戶線上問題", ["外部客戶", "線上"]),
        ("v3-blind-ans-29", "國泰期貨艾揚登入出現 -200 怎麼辦？", "國泰期貨艾揚登入出現-200", ["-200", "艾揚"]),
        ("v3-blind-ans-30", "金控入口網密碼變更方式是什麼？", "金控入口網密碼變更方式", ["入口網", "密碼"]),
        ("v3-blind-ans-31", "Android 行動裝置怎麼安裝 Outlook？", "行動裝置 Outlook 安裝手冊（Android）", ["Android", "Outlook"]),
        ("v3-blind-ans-32", "iOS 行動裝置怎麼安裝 Outlook？", "行動裝置 Outlook 安裝手冊（iOS）", ["iOS", "Outlook"]),
        ("v3-blind-ans-33", "CTeam 密碼跟員工入口網有關嗎？", "國泰員工入口網、CTeam密碼、國泰e點名", ["CTeam", "密碼"]),
        ("v3-blind-ans-34", "國泰 e 點名密碼連動哪邊？", "國泰員工入口網、CTeam密碼、國泰e點名", ["e點名", "密碼"]),
        ("v3-blind-ans-35", "AD 密碼打錯太多次被鎖怎麼解？", "AD 帳號與系統解鎖 FAQ", ["AD 自助解鎖專區", "鎖定"]),
        ("v3-blind-ans-36", "CRM 登入被鎖能不能走 AD 自助解鎖？", "AD 帳號與系統解鎖 FAQ", ["CRM", "AD 自助解鎖"]),
        ("v3-blind-ans-37", "M365 相關帳號鎖定可以自助解鎖嗎？", "AD 帳號與系統解鎖 FAQ", ["M365", "自助解鎖"]),
        ("v3-blind-ans-38", "VPN 密碼不對且不要保存密碼是什麼意思？", "VPN常見Q&A問答", ["密碼不對", "不要保存密碼"]),
        ("v3-blind-ans-39", "VPN 密碼怎麼輸入都不行要聯絡誰？", "VPN常見Q&A問答", ["123", "帳號解鎖"]),
        ("v3-blind-ans-40", "Gitlab 帳號重置相關說明在哪？", "Gitlab帳號解鎖跟重置", ["Gitlab", "重置"]),
        ("v3-blind-ans-41", "外網 CRM 與內網設定差在哪裡？", "外網 CRM 登入連線設定方式", ["外網", "CRM"]),
        ("v3-blind-ans-42", "OTP 綁定失敗要重看哪份操作？", "國金 CRM OTP 綁訂操作", ["OTP", "綁"]),
        ("v3-blind-ans-43", "跳板機連不上時優先檢查什麼？", "VPN 跳板機連線異常", ["跳板"]),
        ("v3-blind-ans-44", "筆電在內網但 VPN 仍異常怎麼查？", "內網筆電 VPN 連線問題", ["筆電", "VPN"]),
        ("v3-blind-ans-45", "國外短期出差要申請哪種 VPN？", "VPN國外連線短暫申請", ["國外", "短暫"]),
        ("v3-blind-ans-46", "公槽權限申請要找哪個流程文件？", "同仁申請共用公槽資料夾", ["公槽"]),
        ("v3-blind-ans-47", "IP 話機轉接怎麼操作？", "總公司IP話機操作", ["話機"]),
        ("v3-blind-ans-48", "通報資訊問題要填哪些欄位？", "資訊問題的通報格式", ["通報"]),
        ("v3-blind-ans-49", "大州第一次登入要完成什麼？", "大州首次使用設定", ["首次使用"]),
        ("v3-blind-ans-50", "功能灰掉無法點選是大州哪份文件？", "大州系統_功能無法點選", ["無法點選"]),
    ]
    for case_id, query, title, must in answerable:
        drafts.append(
            _case(
                case_id,
                categories=["answerable"],
                query=query,
                expected_found=True,
                expected_documents=[title],
                expected_evidence=[{"mustContain": list(must)}],
                notes=f"Corpus-grounded answerable for {title}",
            )
        )

    # --- No-answer / hard-negative ---
    no_answers = [
        ("v3-blind-na-06", "公司有沒有提供 ChatGPT Team 付費帳號？"),
        ("v3-blind-na-07", "如何申請個人 AWS root 帳號？"),
        ("v3-blind-na-08", "辦公大樓無人機停機坪使用規範？"),
        ("v3-blind-na-09", "錯誤碼 FOO-424242 官方修補步驟？"),
        ("v3-blind-na-10", "請給我董事長私人 Line ID"),
        ("v3-blind-na-11", "內部有沒有 Minecraft 伺服器帳號申請？"),
        ("v3-blind-na-12", "如何把公司筆電刷成 Ubuntu 桌面版？"),
        ("v3-blind-na-13", "申請加密貨幣冷錢包保管流程？"),
        ("v3-blind-na-14", "衛星電話費用報銷標準是什麼？"),
        ("v3-blind-na-15", "公司提供免費 Spotify 家庭方案嗎？"),
        ("v3-blind-na-16", "如何取得未公開的薪資等級表？"),
        ("v3-blind-na-17", "請提供資安弱點掃描原始報告下載連結"),
        ("v3-blind-na-18", "內部 NFT 發幣申請窗口？"),
        ("v3-blind-na-19", "量子電腦租用申請表在哪？"),
        ("v3-blind-na-20", "如何關閉全部大樓門禁系統？"),
        ("v3-blind-na-21", "申請個人域名綁到公司 DNS？"),
        ("v3-blind-na-22", "公司有沒有提供 Tesla 充電樁預約？"),
        ("v3-blind-na-23", "錯誤碼 ZZZ-000 的中文說明？"),
        ("v3-blind-na-24", "請寄送完整員工個資匯出檔"),
        ("v3-blind-na-25", "如何安裝破解版 Office？"),
        ("v3-blind-na-26", "內部有沒有提供 Steam 遊戲庫？"),
        ("v3-blind-na-27", "申請私人 VPN 繞過公司防火牆？"),
        ("v3-blind-na-28", "如何取得尚未發布的財報草稿？"),
        ("v3-blind-na-29", "公司寵物上班日規範？"),
        ("v3-blind-na-30", "請提供測試環境的正式客戶交易資料"),
        ("v3-blind-na-31", "如何申請個人 GitHub Copilot Business？"),
        ("v3-blind-na-32", "大樓頂樓觀景台開放時間？"),
        ("v3-blind-na-33", "錯誤碼 HELLO-WORLD 修復手冊？"),
        ("v3-blind-na-34", "申請公司信用卡給外包商？"),
        ("v3-blind-na-35", "如何關閉所有同事的 Teams 通知？"),
        ("v3-blind-na-36", "內部有沒有提供 Netflix 共用帳號？"),
        ("v3-blind-na-37", "申請把筆電改成雙開 Android？"),
        ("v3-blind-na-38", "請提供防火牆 bypass 白名單申請給個人網站"),
        ("v3-blind-na-39", "公司無人機空拍宣傳預約？"),
        ("v3-blind-na-40", "如何取得已刪除郵件伺服器的根密碼？"),
    ]
    for case_id, query in no_answers:
        drafts.append(
            _case(
                case_id,
                categories=["no_answer"],
                query=query,
                expected_found=False,
                notes="Absent / unsafe / out-of-corpus topic",
            )
        )

    hard_negatives = [
        (
            "v3-blind-hn-02",
            "員工入口網密碼要去哪改？不要給我 AD 解鎖流程",
            "國泰員工入口網、CTeam密碼、國泰e點名",
            ["入口網", "密碼"],
            ["AD 帳號與系統解鎖 FAQ"],
        ),
        (
            "v3-blind-hn-03",
            "金控入口網密碼變更，不是 AD 自助解鎖",
            "金控入口網密碼變更方式",
            ["入口網", "密碼"],
            ["AD 帳號與系統解鎖 FAQ"],
        ),
        (
            "v3-blind-hn-04",
            "FortiClient 錯訊說明，不要只給一般 VPN Q&A",
            "登入 FortiClient 出現錯訊",
            ["FortiClient"],
            ["VPN常見Q&A問答"],
        ),
        (
            "v3-blind-hn-05",
            "大州首次設定，不是功能無法點選那篇",
            "大州首次使用設定",
            ["首次"],
            ["大州系統_功能無法點選"],
        ),
        (
            "v3-blind-hn-06",
            "Android Outlook 安裝，不要給 iOS 手冊",
            "行動裝置 Outlook 安裝手冊（Android）",
            ["Android", "Outlook"],
            ["行動裝置 Outlook 安裝手冊（iOS）"],
        ),
        (
            "v3-blind-hn-07",
            "iOS Outlook 安裝，不要給 Android 手冊",
            "行動裝置 Outlook 安裝手冊（iOS）",
            ["iOS", "Outlook"],
            ["行動裝置 Outlook 安裝手冊（Android）"],
        ),
        (
            "v3-blind-hn-08",
            "外網 CRM 連線設定，不是 OTP 綁定",
            "外網 CRM 登入連線設定方式",
            ["外網", "連線"],
            ["國金 CRM OTP 綁訂操作"],
        ),
        (
            "v3-blind-hn-09",
            "OTP 綁定操作，不是外網連線設定",
            "國金 CRM OTP 綁訂操作",
            ["OTP"],
            ["外網 CRM 登入連線設定方式"],
        ),
        (
            "v3-blind-hn-10",
            "超音樹閃退，不要答成樹精靈無法登入",
            "超音樹-程式閃退問題",
            ["超音樹", "閃退"],
            ["樹精靈AP無法登入"],
        ),
    ]
    for case_id, query, title, must, hn in hard_negatives:
        drafts.append(
            _case(
                case_id,
                categories=["hard_negative", "answerable"],
                query=query,
                expected_found=True,
                expected_documents=[title],
                expected_evidence=[{"mustContain": list(must)}],
                hard_negatives=hn,
                notes="Hard-negative: prefer target doc over adjacent doc",
            )
        )

    # Extra no-answer slots filled via na-06..40 above (scaffold max na-40).

    # --- Multi-turn follow-ups ---
    multi = [
        ("v3-blind-conv-01", "那自助解鎖網址是什麼？", "AD 帳號被鎖定了", "AD 帳號與系統解鎖 FAQ", ["AD 自助解鎖專區"]),
        ("v3-blind-conv-02", "那 OTP 要綁在哪個 App？", "國金 CRM 登入要驗證", "國金 CRM OTP 綁訂操作", ["OTP"]),
        ("v3-blind-conv-03", "那 Android 要下載哪個商店的 Outlook？", "手機收公司信", "行動裝置 Outlook 安裝手冊（Android）", ["Android", "Outlook"]),
        ("v3-blind-conv-04", "那 iPhone 步驟呢？", "手機收公司信", "行動裝置 Outlook 安裝手冊（iOS）", ["iOS", "Outlook"]),
        ("v3-blind-conv-05", "那密碼不是 AD 的話要去哪改？", "員工入口網登不進去", "國泰員工入口網、CTeam密碼、國泰e點名", ["並非AD"]),
        ("v3-blind-conv-06", "那錯訊文件還有其他代碼嗎？", "FortiClient 登入失敗", "登入 FortiClient 出現錯訊", ["FortiClient"]),
        ("v3-blind-conv-07", "那首次設定第一步是什麼？", "大州系統不會用", "大州首次使用設定", ["首次"]),
        ("v3-blind-conv-08", "那功能點不了是另一篇嗎？", "大州系統不會用", "大州系統_功能無法點選", ["無法點選"]),
        ("v3-blind-conv-09", "那通報要寫系統名稱嗎？", "要開資訊單", "資訊問題的通報格式", ["通報"]),
        ("v3-blind-conv-10", "那亂碼信怎麼轉回正常？", "收到一封看不懂的信", "郵件為亂碼", ["亂碼"]),
        ("v3-blind-conv-11", "那跳板機異常還要查 VPN 嗎？", "連不到某台主機", "VPN 跳板機連線異常", ["跳板"]),
        ("v3-blind-conv-12", "那國外短期怎麼申請？", "下週要出國仍要用 VPN", "VPN國外連線短暫申請", ["國外"]),
        ("v3-blind-conv-13", "那公槽申請要誰核准？", "需要共用資料夾", "同仁申請共用公槽資料夾", ["公槽"]),
        ("v3-blind-conv-14", "那 IP 話機怎麼轉接分機？", "總公司電話不會轉", "總公司IP話機操作", ["話機"]),
        ("v3-blind-conv-15", "那 Webex 錄影帳號怎麼借？", "明天開會要錄影", "Webex會議借用-可錄影", ["Webex", "錄影"]),
        ("v3-blind-conv-16", "那 -200 是什麼意思？", "期貨艾揚登入失敗", "國泰期貨艾揚登入出現-200", ["-200"]),
        ("v3-blind-conv-17", "那閃退要重裝嗎？", "超音樹一直關掉", "超音樹-程式閃退問題", ["閃退"]),
        ("v3-blind-conv-18", "那 AP 登不進去找誰？", "樹精靈打不開", "樹精靈AP無法登入", ["樹精靈"]),
        ("v3-blind-conv-19", "那外網 CRM 要改什麼設定？", "在家連 CRM 失敗", "外網 CRM 登入連線設定方式", ["外網", "CRM"]),
        ("v3-blind-conv-20", "那金控入口網密碼怎麼改？", "入口網密碼忘了", "金控入口網密碼變更方式", ["密碼"]),
    ]
    for case_id, query, prior, title, must in multi:
        drafts.append(
            _case(
                case_id,
                categories=["conversational", "multi_turn", "answerable"],
                query=query,
                expected_found=True,
                expected_documents=[title],
                expected_evidence=[{"mustContain": list(must)}],
                notes="Multi-turn follow-up",
                prior_turn=prior,
            )
        )

    # --- Typo / alias / short ---
    noise = [
        ("v3-blind-noise-02", "VP N 密嗎到期怎麼辦", "VPN常見Q&A問答", ["密碼到期"], ["typo", "answerable"]),
        ("v3-blind-noise-03", "FotiiClient 錯訊", "登入 FortiClient 出現錯訊", ["FortiClient"], ["typo", "answerable"]),
        ("v3-blind-noise-04", "大洲系統無法點選", "大州系統_功能無法點選", ["無法點選"], ["typo", "answerable"]),
        ("v3-blind-noise-05", "超音数閃退", "超音樹-程式閃退問題", ["閃退"], ["typo", "answerable"]),
        ("v3-blind-noise-06", "Gitlab帳號被所", "Gitlab帳號解鎖跟重置", ["Gitlab", "解鎖"], ["typo", "answerable"]),
        ("v3-blind-noise-07", "Webex可錄影帳號借用不了", "Webex會議借用-可錄影", ["Webex"], ["typo", "answerable"]),
        ("v3-blind-alias-02", "國泰員工入口密碼是不是 AD？", "國泰員工入口網、CTeam密碼、國泰e點名", ["並非AD"], ["alias", "answerable"]),
        ("v3-blind-alias-03", "跳板機 VPN 掛掉", "VPN 跳板機連線異常", ["跳板"], ["alias", "answerable"]),
        ("v3-blind-alias-04", "手機 Outlook 安卓版安裝", "行動裝置 Outlook 安裝手冊（Android）", ["Android", "Outlook"], ["alias", "answerable"]),
        ("v3-blind-alias-05", "蘋果手機公司信設定", "行動裝置 Outlook 安裝手冊（iOS）", ["iOS", "Outlook"], ["alias", "answerable"]),
        ("v3-blind-alias-06", "期貨艾揚 -200", "國泰期貨艾揚登入出現-200", ["-200"], ["alias", "answerable"]),
        ("v3-blind-alias-07", "金控入口忘記密碼", "金控入口網密碼變更方式", ["密碼"], ["alias", "answerable"]),
        ("v3-blind-short-02", "OTP綁定", "國金 CRM OTP 綁訂操作", ["OTP"], ["short_query", "answerable"]),
        ("v3-blind-short-03", "公槽申請", "同仁申請共用公槽資料夾", ["公槽"], ["short_query", "answerable"]),
        ("v3-blind-short-04", "郵件亂碼", "郵件為亂碼", ["亂碼"], ["short_query", "answerable"]),
        ("v3-blind-short-05", "座位搬遷", "座位搬遷需求", ["搬遷"], ["short_query", "answerable"]),
        ("v3-blind-short-06", "VPN國外", "VPN國外連線短暫申請", ["國外"], ["short_query", "answerable"]),
    ]
    for case_id, query, title, must, cats in noise:
        drafts.append(
            _case(
                case_id,
                categories=list(cats),
                query=query,
                expected_found=True,
                expected_documents=[title],
                expected_evidence=[{"mustContain": list(must)}],
                notes="Typo/alias/short query variant",
            )
        )

    # --- ACL / version / scope / negative extras ---
    drafts.append(
        _case(
            "v3-blind-acl-01",
            categories=["acl_allow", "answerable"],
            query="IT 群組可見的 AD 自助解鎖說明？",
            expected_found=True,
            expected_documents=["AD 帳號與系統解鎖 FAQ"],
            expected_evidence=[{"mustContain": ["AD 自助解鎖專區"]}],
            groups=["IT"],
            notes="ACL allow smoke: labeled for IT group visibility",
        )
    )
    drafts.append(
        _case(
            "v3-blind-acl-02",
            categories=["acl_allow", "answerable"],
            query="有權限時 VPN 常見錯誤碼 -455 怎麼處理？",
            expected_found=True,
            expected_documents=["VPN常見Q&A問答"],
            expected_evidence=[{"mustContain": ["(-455)"]}],
            groups=["IT"],
            notes="ACL allow smoke",
        )
    )
    drafts.append(
        _case(
            "v3-blind-acl-03",
            categories=["acl_allow", "answerable"],
            query="授權使用者如何查看外網 CRM 設定？",
            expected_found=True,
            expected_documents=["外網 CRM 登入連線設定方式"],
            expected_evidence=[{"mustContain": ["外網", "CRM"]}],
            groups=["IT"],
            notes="ACL allow smoke",
        )
    )
    drafts.append(
        _case(
            "v3-blind-acl-04",
            categories=["acl_allow", "answerable"],
            query="有權限時 Gitlab 解鎖說明？",
            expected_found=True,
            expected_documents=["Gitlab帳號解鎖跟重置"],
            expected_evidence=[{"mustContain": ["Gitlab"]}],
            groups=["IT"],
            notes="ACL allow smoke",
        )
    )
    drafts.append(
        _case(
            "v3-blind-ver-01",
            categories=["version_conflict", "answerable"],
            query="大州首次使用設定與功能無法點選是不是同一版文件？",
            expected_found=True,
            expected_documents=["大州首次使用設定", "大州系統_功能無法點選"],
            expected_evidence=[{"mustContain": ["大州"]}],
            notes="Version/document discrimination between related titles",
        )
    )
    drafts.append(
        _case(
            "v3-blind-ver-02",
            categories=["version_conflict", "answerable"],
            query="Android 與 iOS Outlook 手冊是否為不同文件？",
            expected_found=True,
            expected_documents=[
                "行動裝置 Outlook 安裝手冊（Android）",
                "行動裝置 Outlook 安裝手冊（iOS）",
            ],
            expected_evidence=[{"mustContain": ["Outlook"]}],
            notes="Platform-specific document discrimination",
        )
    )
    drafts.append(
        _case(
            "v3-blind-ver-03",
            categories=["version_conflict", "answerable"],
            query="VPN 常見 Q&A 與 FortiClient 錯訊文件差別？",
            expected_found=True,
            expected_documents=["VPN常見Q&A問答", "登入 FortiClient 出現錯訊"],
            expected_evidence=[{"mustContain": ["VPN"]}],
            notes="Related VPN docs discrimination",
        )
    )
    drafts.append(
        _case(
            "v3-blind-ver-04",
            categories=["version_conflict", "answerable"],
            query="樹精靈無法登入跟超音樹閃退是不是同一份？",
            expected_found=True,
            expected_documents=["樹精靈AP無法登入", "超音樹-程式閃退問題"],
            expected_evidence=[{"mustContain": ["登入"]}],
            notes="Adjacent product docs discrimination",
        )
    )
    drafts.append(
        _case(
            "v3-blind-scope-02",
            categories=["source_scope", "answerable"],
            query="「VPN常見Q&A問答」這份文件主要涵蓋什麼？",
            expected_found=True,
            expected_documents=["VPN常見Q&A問答"],
            expected_evidence=[{"mustContain": ["VPN"]}],
            notes="Named-source scope question",
        )
    )
    drafts.append(
        _case(
            "v3-blind-scope-03",
            categories=["source_scope", "answerable"],
            query="「資訊問題的通報格式」文件是在規範什麼？",
            expected_found=True,
            expected_documents=["資訊問題的通報格式"],
            expected_evidence=[{"mustContain": ["通報"]}],
            notes="Named-source scope question",
        )
    )
    drafts.append(
        _case(
            "v3-blind-scope-04",
            categories=["source_scope", "answerable"],
            query="「金控入口網密碼變更方式」講的是哪個入口？",
            expected_found=True,
            expected_documents=["金控入口網密碼變更方式"],
            expected_evidence=[{"mustContain": ["入口網", "密碼"]}],
            notes="Named-source scope question",
        )
    )
    drafts.append(
        _case(
            "v3-blind-neg-02",
            categories=["negative_constraint", "answerable"],
            query="為何不能把 AD 解鎖當成員工入口網改密碼？",
            expected_found=True,
            expected_documents=["國泰員工入口網、CTeam密碼、國泰e點名"],
            expected_evidence=[{"mustContain": ["並非AD"]}],
            notes="Negative constraint",
        )
    )
    drafts.append(
        _case(
            "v3-blind-neg-03",
            categories=["negative_constraint", "answerable"],
            query="為何 Android Outlook 手冊不能套用到 iPhone？",
            expected_found=True,
            expected_documents=["行動裝置 Outlook 安裝手冊（iOS）"],
            expected_evidence=[{"mustContain": ["iOS"]}],
            notes="Negative constraint across platforms",
        )
    )
    drafts.append(
        _case(
            "v3-blind-neg-04",
            categories=["negative_constraint", "answerable"],
            query="為何大州功能無法點選不該用首次設定全文回答？",
            expected_found=True,
            expected_documents=["大州系統_功能無法點選"],
            expected_evidence=[{"mustContain": ["無法點選"]}],
            notes="Negative constraint scenario separation",
        )
    )

    return drafts


def main() -> None:
    v2 = json.loads(V2_PATH.read_text(encoding="utf-8"))
    v2_queries = {c["query"] for c in v2["cases"]}
    blind = json.loads(BLIND_PATH.read_text(encoding="utf-8"))
    by_id = {c["id"]: i for i, c in enumerate(blind["cases"])}
    preserve_ids = {
        c["id"]
        for c in blind["cases"]
        if str(c.get("query") or "").strip() and c.get("labelStatus") == "draft_pending_review"
    }
    drafts = build_drafts()
    overlap = [d["query"] for d in drafts if d["query"] in v2_queries]
    missing: list[str] = []
    updated = 0
    skipped_preserve = 0
    for draft in drafts:
        idx = by_id.get(draft["id"])
        if idx is None:
            missing.append(draft["id"])
            continue
        if draft["id"] in preserve_ids:
            skipped_preserve += 1
            continue
        blind["cases"][idx].update(draft)
        updated += 1

    filled = sum(1 for c in blind["cases"] if str(c.get("query") or "").strip())
    by_cat: dict[str, int] = {}
    for case in blind["cases"]:
        if not str(case.get("query") or "").strip():
            continue
        for category in case.get("categories") or []:
            by_cat[category] = by_cat.get(category, 0) + 1

    blind["fillProgress"] = {
        "totalSlots": len(blind["cases"]),
        "filled": filled,
        "reviewed": 0,
        "categoryCounts": by_cat,
        "note": (
            "Corpus-grounded drafts pending non-implementer review. "
            "Do not freeze until coverage targets and reviewerSignoff are met."
        ),
    }
    blind["frozen"] = False
    BLIND_PATH.write_text(json.dumps(blind, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "updated": updated,
                "skippedPreserve": skipped_preserve,
                "filled": filled,
                "missing": missing,
                "v2OverlapCount": len(overlap),
                "categoryCounts": by_cat,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
