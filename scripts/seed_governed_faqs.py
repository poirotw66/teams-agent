#!/usr/bin/env python3
"""Seed governed FAQs into the AI Ops Backoffice Phase 2 store.

Can seed either via the live Backoffice API (port 8092) or directly via
FaqDomainService into data/ops/phase2/faqs.json.

Usage:
    python scripts/seed_governed_faqs.py
    python scripts/seed_governed_faqs.py --api http://127.0.0.1:8092
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

DEMO_FAQS = [
    {
        "faq_key": "PASSWORD_RESET",
        "question": "忘記密碼或密碼需要變更該如何處理？",
        "answer": "請至金控入口網（國泰員工入口網）點選「忘記密碼」或「密碼變更」選項進行密碼重設。若仍無法完成，請聯繫「123資訊小幫手」協助處理。",
        "category": "帳號密碼",
        "keywords": ["密碼", "忘記密碼", "重設", "金控入口網"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["email.password_reset"],
        "audience_type": "ALL",
        "positive_test": "忘記入口網密碼",
        "negative_test": "如何申請共用公槽",
        "target_status": "ACTIVE",
    },
    {
        "faq_key": "VPN_HELP",
        "question": "VPN 連線異常該如何處理？",
        "answer": "VPN 連線異常時，請先確認網路連線狀態與帳號權限，確認無誤後重新嘗試連線。若仍無法排除，請聯繫資訊小幫手協助排查。",
        "category": "VPN",
        "keywords": ["vpn", "連線", "網路"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["vpn.connection_failed"],
        "audience_type": "ALL",
        "positive_test": "VPN 無法連線",
        "negative_test": "如何請特休",
        "target_status": "ACTIVE",
    },
    {
        "faq_key": "IT_CONTACT",
        "question": "如何聯繫 123 資訊小幫手或 IT 人工協助？",
        "answer": "如自助處理無法解決問題，請透過內部管道聯繫「123資訊小幫手」尋求人工協助。",
        "category": "客服管道",
        "keywords": ["小幫手", "人工客服", "資訊小幫手", "聯絡資訊"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["network.general"],
        "audience_type": "ALL",
        "positive_test": "怎麼找資訊小幫手",
        "negative_test": "會議室借用辦法",
        "target_status": "ACTIVE",
    },
    {
        "faq_key": "TICKET_HOWTO",
        "question": "通報資訊問題時的格式與必填內容為何？",
        "answer": "通報資訊問題時，信件主旨請以「[平台名稱]+功能名稱+異常說明」格式撰寫，並於內容中提供：客戶姓名、帳號/ID、問題軟體名稱、問題說明、發生時間、載具及系統版本，若有截圖請一併附上，以利加速處理。",
        "category": "問題通報",
        "keywords": ["問題通報", "通報格式", "報修", "系統異常"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["network.general"],
        "audience_type": "ALL",
        "positive_test": "資訊問題通報格式說明",
        "negative_test": "公司外送訂餐規定",
        "target_status": "ACTIVE",
    },
    {
        "faq_key": "GITLAB_UNLOCK",
        "question": "Gitlab 帳號被鎖定或需要重置該如何處理？",
        "answer": "Gitlab 帳號解鎖或重置，請透過內部管道聯繫資訊管理處相關負責同仁協助處理。",
        "category": "研發工具",
        "keywords": ["gitlab", "帳號鎖定", "解鎖", "重置"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["vpn.account_locked"],
        "audience_type": "ALL",
        "positive_test": "Gitlab 帳號被鎖定",
        "negative_test": "座位搬遷申請流程",
        "target_status": "DRAFT",
    },
    {
        "faq_key": "IT_SERVICE_HOURS",
        "question": "IT 服務時間與服務管道為何？",
        "answer": "IT 服務時間目前尚未於知識庫中確認，本項目暫時停用，請改由「123資訊小幫手」查詢最新服務時間。",
        "category": "服務時間",
        "keywords": ["服務時間", "營業時間", "上班時間"],
        "owner_unit_id": "IT Service Desk",
        "business_contact": "IT Service Desk",
        "issue_type_ids": ["network.general"],
        "audience_type": "ALL",
        "positive_test": "資訊小幫手服務時間",
        "negative_test": "國泰志工服務報名",
        "target_status": "DISABLED",
    },
]


def seed_via_api(base_url: str) -> None:
    headers = {
        "X-Backoffice-User-Id": "ops.admin",
        "X-Backoffice-User-Name": "System Administrator",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "Content-Type": "application/json",
    }
    reviewer_headers = {
        **headers,
        "X-Backoffice-User-Id": "ops.reviewer",
        "X-Backoffice-User-Name": "Content Reviewer",
    }

    # Fetch existing
    req = urllib.request.Request(f"{base_url}/api/faqs", headers=headers)
    with urllib.request.urlopen(req) as resp:
        existing_data = json.loads(resp.read().decode("utf-8"))
    existing_keys = {item["faq"]["faq_key"]: item for item in existing_data.get("items", [])}
    print(f"現有 FAQ 數量: {len(existing_keys)}")

    for item in DEMO_FAQS:
        faq_key = item["faq_key"]
        if faq_key in existing_keys:
            print(f"[*] FAQ {faq_key} 已存在，略過建立。")
            continue

        print(f"[+] 正在建立 FAQ: {faq_key} - {item['question']}")
        create_payload = {
            "faq_key": item["faq_key"],
            "question": item["question"],
            "answer": item["answer"],
            "category": item["category"],
            "keywords": item["keywords"],
            "owner_unit_id": item["owner_unit_id"],
            "business_contact": item["business_contact"],
            "issue_type_ids": item["issue_type_ids"],
            "audience_type": item["audience_type"],
        }
        create_req = urllib.request.Request(
            f"{base_url}/api/faqs",
            data=json.dumps(create_payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(create_req) as resp:
            created = json.loads(resp.read().decode("utf-8"))

        faq_id = created["faq"]["faq_id"]
        version_id = created["version"]["version_id"]
        etag = created["faq"]["etag"]

        target_status = item["target_status"]
        if target_status == "DRAFT":
            print(f"    -> 保持為 DRAFT 狀態。")
            continue

        # Add positive test
        test_pos_req = urllib.request.Request(
            f"{base_url}/api/faqs/{faq_id}/versions/{version_id}/tests",
            data=json.dumps({
                "kind": "POSITIVE",
                "utterance": item["positive_test"],
                "expected_etag": etag,
            }).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(test_pos_req) as resp:
            pos_data = json.loads(resp.read().decode("utf-8"))
        etag = pos_data["faq"]["etag"]

        # Add negative test
        test_neg_req = urllib.request.Request(
            f"{base_url}/api/faqs/{faq_id}/versions/{version_id}/tests",
            data=json.dumps({
                "kind": "NEGATIVE",
                "utterance": item["negative_test"],
                "expected_etag": etag,
            }).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(test_neg_req) as resp:
            neg_data = json.loads(resp.read().decode("utf-8"))
        etag = neg_data["faq"]["etag"]

        # Submit
        submit_req = urllib.request.Request(
            f"{base_url}/api/faqs/{faq_id}/versions/{version_id}/submit",
            data=json.dumps({"expected_etag": etag}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(submit_req) as resp:
            sub_data = json.loads(resp.read().decode("utf-8"))
        etag = sub_data["faq"]["etag"]

        # Review & Approve
        review_req = urllib.request.Request(
            f"{base_url}/api/faqs/{faq_id}/versions/{version_id}/review",
            data=json.dumps({
                "approve": True,
                "reason": "種子資料內容審查通過",
                "expected_etag": etag,
            }).encode("utf-8"),
            headers=reviewer_headers,
            method="POST",
        )
        with urllib.request.urlopen(review_req) as resp:
            rev_data = json.loads(resp.read().decode("utf-8"))
        etag = rev_data["faq"]["etag"]

        if target_status == "ACTIVE":
            activate_req = urllib.request.Request(
                f"{base_url}/api/faqs/{faq_id}/versions/{version_id}/activate",
                data=json.dumps({
                    "reason": "種子資料正式發布",
                    "expected_etag": etag,
                }).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(activate_req) as resp:
                act_data = json.loads(resp.read().decode("utf-8"))
            print(f"    -> 成功發布為 ACTIVE 狀態。")
        elif target_status == "DISABLED":
            # Activate first then disable
            activate_req = urllib.request.Request(
                f"{base_url}/api/faqs/{faq_id}/versions/{version_id}/activate",
                data=json.dumps({
                    "reason": "暫時生效以便示範停用",
                    "expected_etag": etag,
                }).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(activate_req) as resp:
                act_data = json.loads(resp.read().decode("utf-8"))
            etag = act_data["faq"]["etag"]

            disable_req = urllib.request.Request(
                f"{base_url}/api/faqs/{faq_id}/disable",
                data=json.dumps({
                    "reason": "資訊小幫手服務時間尚未確認，先予停用",
                    "expected_etag": etag,
                }).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(disable_req) as resp:
                dis_data = json.loads(resp.read().decode("utf-8"))
            print(f"    -> 成功標記為 DISABLED 狀態。")

    print("\n[OK] 所有示範 FAQ 種子資料處理完成！")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed governed FAQs into AI Ops Backoffice")
    parser.add_argument("--api", default="http://127.0.0.1:8092", help="Base URL of Backoffice API")
    args = parser.parse_args()
    seed_via_api(args.api.rstrip("/"))


if __name__ == "__main__":
    main()
