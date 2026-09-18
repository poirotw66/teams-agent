"""Static ticket-item catalog served by the mock ticket service."""

from __future__ import annotations

MOCK_TICKET_CATALOG_ITEMS: list[dict[str, object]] = [
    {
        "id": "category-hardware",
        "level": 1,
        "name": "軟硬體設備",
        "children": [
            {
                "id": "category-computer",
                "level": 2,
                "name": "電腦設備",
                "children": [
                    {"id": "item-power", "level": 3, "name": "電腦無法開機", "children": []},
                    {
                        "id": "item-performance",
                        "level": 3,
                        "name": "電腦效能異常",
                        "children": [],
                    },
                    {"id": "item-crash", "level": 3, "name": "電腦頻繁當機", "children": []},
                ],
            },
            {
                "id": "category-peripheral",
                "level": 2,
                "name": "周邊設備",
                "children": [
                    {"id": "item-monitor", "level": 3, "name": "螢幕無畫面", "children": []},
                    {
                        "id": "item-input",
                        "level": 3,
                        "name": "鍵盤或滑鼠異常",
                        "children": [],
                    },
                ],
            },
        ],
    },
    {
        "id": "category-services",
        "level": 1,
        "name": "系統服務",
        "children": [
            {
                "id": "category-internal-system",
                "level": 2,
                "name": "內部系統",
                "children": [
                    {
                        "id": "item-system-login",
                        "level": 3,
                        "name": "系統無法登入",
                        "children": [],
                    },
                    {
                        "id": "item-system-function",
                        "level": 3,
                        "name": "系統功能異常",
                        "children": [],
                    },
                ],
            },
            {
                "id": "category-network",
                "level": 2,
                "name": "網路服務",
                "children": [
                    {
                        "id": "item-network",
                        "level": 3,
                        "name": "公司網路無法連線",
                        "children": [],
                    },
                    {"id": "item-vpn", "level": 3, "name": "VPN 無法連線", "children": []},
                ],
            },
        ],
    },
    {
        "id": "category-access",
        "level": 1,
        "name": "帳號與權限",
        "children": [
            {
                "id": "category-ad",
                "level": 2,
                "name": "AD 帳號",
                "children": [
                    {"id": "item-ad-lock", "level": 3, "name": "AD 帳號鎖定", "children": []},
                    {
                        "id": "item-ad-password",
                        "level": 3,
                        "name": "AD 密碼重設",
                        "children": [],
                    },
                ],
            },
            {
                "id": "category-system-access",
                "level": 2,
                "name": "系統權限",
                "children": [
                    {
                        "id": "item-access-request",
                        "level": 3,
                        "name": "申請系統權限",
                        "children": [],
                    },
                    {
                        "id": "item-access-error",
                        "level": 3,
                        "name": "系統權限異常",
                        "children": [],
                    },
                ],
            },
        ],
    },
]
