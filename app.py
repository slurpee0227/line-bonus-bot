from flask import Flask, request
import requests
import os
import threading

app = Flask(__name__)

# 從環境變數讀取 LINE TOKEN
LINE_TOKEN = os.getenv("LINE_TOKEN")

# 使用記憶體儲存每個使用者資料（依 userId 區分）
users = {}
lock = threading.Lock()


def get_user(uid):
    """取得或初始化使用者狀態"""
    with lock:
        if uid not in users:
            users[uid] = {
                "step": "name",        # name / input
                "name": None,
                "numbers": [],
                "editMode": None,      # None / selectIndex / chooseAction / inputValue
                "editIndex": None,
                "confirmMode": False
            }
        return users[uid]


# ===============================
# LINE 回覆工具
# ===============================
def line_post(path, body):
    url = f"https://api.line.me/v2/bot{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + LINE_TOKEN,
    }
    requests.post(url, headers=headers, json=body)


def reply(reply_token, messages):
    """回覆訊息（messages 可以是 dict 或 list）"""
    if isinstance(messages, dict):
        messages = [messages]
    body = {
        "replyToken": reply_token,
        "messages": messages
    }
    line_post("/message/reply", body)


# ===============================
# QuickReply 建構
# ===============================
def qr_item(label, text):
    return {
        "type": "action",
        "action": {
            "type": "message",
            "label": label,
            "text": text
        }
    }


def quick_reply_main():
    """主選單 QuickReply：輸入支數 / 列表 / 編輯 / 結束 / 說明"""
    return {
        "items": [
            qr_item("🔢 輸入支數", "輸入支數"),
            qr_item("📋 列表", "列表"),
            qr_item("✏ 編輯", "編輯"),
            qr_item("🔚 結束", "結束"),
            qr_item("ℹ️ 說明", "說明"),
        ]
    }


def quick_reply_numbers():
    """支數輸入常用數值 + 返回"""
    common_values = ["0.5", "1.0", "1.5", "2.0", "3.0", "5.0"]
    items = [qr_item(v, v) for v in common_values]
    items.append(qr_item("⬅ 返回", "返回"))
    return {"items": items}


def quick_reply_confirm():
    """確認 / 取消"""
    return {
        "items": [
            qr_item("✅ 確認", "確認"),
            qr_item("❌ 取消", "取消")
        ]
    }


def quick_reply_edit_choose_index(numbers):
    """選擇要編輯的筆數（用按鈕顯示 1~N，最多 13 個）"""
    n = len(numbers)
    limit = min(n, 13)  # QuickReply 最多 13 個 item
    items = [qr_item(f"第{i+1}筆", str(i+1)) for i in range(limit)]
    items.append(qr_item("⬅ 返回", "返回"))
    return {"items": items}


def quick_reply_edit_action():
    """在選定筆數後，提供 修改 / 刪除 / 返回"""
    return {
        "items": [
            qr_item("✏ 修改", "修改"),
            qr_item("🗑 刪除", "刪除"),
            qr_item("⬅ 返回", "返回")
        ]
    }


# ===============================
# Flex UI（計算結果卡片）
# ===============================
def line_box(label, value):
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "text",
                "text": label,
                "weight": "bold",
                "size": "sm",
                "flex": 2
            },
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "flex": 3
            }
        ]
    }


def result_card(name, total, bonus):
    """計算結果 Flex 卡片"""
    return {
        "type": "flex",
        "altText": "計算結果",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "獎金計算機",
                        "weight": "bold",
                        "size": "sm",
                        "color": "#555555"
                    },
                    {
                        "type": "text",
                        "text": "✨ 計算完成",
                        "weight": "bold",
                        "size": "xl",
                        "margin": "md"
                    }
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    line_box("姓名", name),
                    line_box("總支數", f"{total:.1f}"),
                    line_box("獎金（×76）", f"{bonus:.1f} 元"),
                ]
            }
        }
    }


# ===============================
# 小工具
# ===============================
def fix1(x):
    return float(f"{x:.1f}")


def build_text(text, with_main_qr=False, extra_qr=None):
    """建一個帶 QuickReply 的文字訊息"""
    msg = {
        "type": "text",
        "text": text
    }
    # main_qr: 主選單
    if with_main_qr:
        msg["quickReply"] = quick_reply_main()
    # extra_qr: 特定情境（例如支數輸入、編輯選擇等）
    if extra_qr is not None:
        msg["quickReply"] = extra_qr
    return msg


# ===============================
# Webhook 入口
# ===============================
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json

    # LINE 驗證或 Health check 時可能沒有 events
    if not body or "events" not in body or not body["events"]:
        return "OK"

    event = body["events"][0]

    if event.get("type") != "message":
        return "OK"

    message = event.get("message", {})
    if message.get("type") != "text":
        return "OK"

    text = message["text"].strip()
    reply_token = event["replyToken"]
    uid = event["source"]["userId"]

    user = get_user(uid)

    # ==========================================
    # 說明
    # ==========================================
    if text == "說明":
        msg = build_text(
            "【獎金計算機 - 使用說明】\n\n"
            "1️⃣ 先輸入姓名\n"
            "2️⃣ 使用「輸入支數」輸入每一筆支數\n"
            "3️⃣ 可使用「列表 / 編輯」檢視與調整\n"
            "4️⃣ 使用「結束」進行預覽與計算獎金\n\n"
            "獎金公式：總支數 × 76",
            with_main_qr=True
        )
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 開始 / 首頁：重置流程
    # ==========================================
    if text in ["開始", "首頁"]:
        users[uid] = {
            "step": "name",
            "name": None,
            "numbers": [],
            "editMode": None,
            "editIndex": None,
            "confirmMode": False
        }
        msg = build_text("🟦 步驟 1：請輸入姓名", with_main_qr=False)
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 編輯模式：最高優先
    # ==========================================
    if user["editMode"]:
        return handle_edit(uid, user, text, reply_token)

    # ==========================================
    # 結束確認模式
    # ==========================================
    if user["confirmMode"]:
        return handle_confirm(uid, user, text, reply_token)

    # ==========================================
    # Step 1：輸入姓名（只在 step == "name" 時觸發）
    # ==========================================
    if user["step"] == "name":
        forbidden = ["列表", "編輯", "結束", "返回", "說明", "輸入支數"]

        if text in forbidden:
            msg = build_text(
                "現在是【輸入姓名】階段，請輸入姓名（不能使用指令）。",
                with_main_qr=False
            )
            reply(reply_token, msg)
            return "OK"

        if not text:
            msg = build_text("姓名不可為空白，請重新輸入。", with_main_qr=False)
            reply(reply_token, msg)
            return "OK"

        user["name"] = text
        user["step"] = "input"

        msg = build_text(
            f"👤 姓名：{text}\n\n請使用下方按鈕開始輸入支數。",
            with_main_qr=True
        )
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 從任何狀態按「返回」：回主畫面（僅 step == input）
    # ==========================================
    if text == "返回":
        if user["step"] == "input":
            summary = build_status_text(user)
            msg = build_text(summary, with_main_qr=True)
            reply(reply_token, msg)
            return "OK"
        # 若 step 不是 input，就當作無效
        msg = build_text("目前無法返回，請依照畫面指示操作。", with_main_qr=True)
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 輸入支數（顯示說明 + 常用數值 QuickReply）
    # ==========================================
    if text == "輸入支數":
        if user["step"] != "input":
            msg = build_text("請先輸入姓名，再輸入支數。", with_main_qr=False)
            reply(reply_token, msg)
            return "OK"

        msg = build_text(
            "請輸入支數（可含小數），\n"
            "也可以直接點下方常用數值按鈕。",
            extra_qr=quick_reply_numbers()
        )
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 列表
    # ==========================================
    if text == "列表":
        nums = user["numbers"]
        if not nums:
            msg = build_text("📋 尚未輸入任何支數。", with_main_qr=True)
            reply(reply_token, msg)
            return "OK"

        s = build_list_text(nums)
        msg = build_text(s, with_main_qr=True)
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 進入編輯
    # ==========================================
    if text == "編輯":
        nums = user["numbers"]
        if not nums:
            msg = build_text("目前沒有資料可編輯。", with_main_qr=True)
            reply(reply_token, msg)
            return "OK"

        user["editMode"] = "selectIndex"
        s = "請選擇要編輯的筆數："
        msg = build_text(s, extra_qr=quick_reply_edit_choose_index(nums))
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 結束：進入預覽 & 確認模式
    # ==========================================
    if text == "結束":
        nums = user["numbers"]
        if not nums:
            msg = build_text("目前沒有資料可結束。", with_main_qr=True)
            reply(reply_token, msg)
            return "OK"

        s = "📋【結束前預覽】\n\n" + build_list_text(nums) + "\n\n請確認是否要結束並計算獎金？"
        user["confirmMode"] = True
        msg = build_text(s, extra_qr=quick_reply_confirm())
        reply(reply_token, msg)
        return "OK"

    # ==========================================
    # 其他情況 → 視為支數輸入
    # ==========================================
    return handle_number(uid, user, text, reply_token)


# ===============================
# 狀態顯示用文字
# ===============================
def build_status_text(user):
    name = user["name"] or "(尚未輸入)"
    nums = user["numbers"]
    count = len(nums)
    total = sum(nums) if nums else 0.0
    text = f"👤 姓名：{name}\n目前筆數：{count} 筆，合計 {total:.1f}\n\n請使用下方按鈕繼續操作。"
    return text


def build_list_text(nums):
    s = ""
    for i, n in enumerate(nums):
        s += f"{i+1}) {n:.1f}\n"
    s += f"\n合計：{sum(nums):.1f}\n共 {len(nums)} 筆"
    return s


# ===============================
# 支數輸入
# ===============================
def handle_number(uid, user, text, reply_token):
    # 在支數輸入階段，不再接受指令（那些應該已在上層被處理）
    try:
        v = fix1(float(text))
    except:
        msg = build_text(
            "請輸入有效的數字（可含小數）。\n"
            "如需使用功能請按下方按鈕。",
            with_main_qr=True
        )
        reply(reply_token, msg)
        return "OK"

    user["numbers"].append(v)

    msg = build_text(
        f"✔ 已加入：{v:.1f}\n目前共有 {len(user['numbers'])} 筆。",
        with_main_qr=True
    )
    reply(reply_token, msg)
    return "OK"


# ===============================
# 編輯模式
# ===============================
def handle_edit(uid, user, text, reply_token):
    mode = user["editMode"]
    nums = user["numbers"]

    # 「返回」：離開編輯模式，回主畫面
    if text == "返回":
        user["editMode"] = None
        user["editIndex"] = None
        msg = build_text("已退出編輯模式。", with_main_qr=True)
        reply(reply_token, msg)
        return "OK"

    # 選擇哪一筆（由 QuickReply 傳入數字）
    if mode == "selectIndex":
        try:
            i = int(text) - 1
            if i < 0 or i >= len(nums):
                raise Exception()
        except:
            msg = build_text(
                f"請使用下方按鈕選擇 1 ~ {len(nums)} 的編號。",
                extra_qr=quick_reply_edit_choose_index(nums)
            )
            reply(reply_token, msg)
            return "OK"

        user["editIndex"] = i
        user["editMode"] = "chooseAction"

        msg = build_text(
            f"你選擇第 {i+1} 筆：{nums[i]:.1f}\n請選擇要「修改」或「刪除」。",
            extra_qr=quick_reply_edit_action()
        )
        reply(reply_token, msg)
        return "OK"

    # 修改 or 刪除
    if mode == "chooseAction":
        if text == "刪除":
            removed = nums.pop(user["editIndex"])
            user["editMode"] = None
            user["editIndex"] = None
            msg = build_text(f"✔ 已刪除：{removed:.1f}", with_main_qr=True)
            reply(reply_token, msg)
            return "OK"

        if text == "修改":
            user["editMode"] = "inputValue"
            msg = build_text("請輸入新的數值（可含小數）：", with_main_qr=False)
            reply(reply_token, msg)
            return "OK"

        # 其他輸入 → 再提示一次
        msg = build_text(
            "請使用下方按鈕選擇「修改」或「刪除」。",
            extra_qr=quick_reply_edit_action()
        )
        reply(reply_token, msg)
        return "OK"

    # 新值輸入
    if mode == "inputValue":
        try:
            v = fix1(float(text))
        except:
            msg = build_text("請輸入有效數字。", with_main_qr=False)
            reply(reply_token, msg)
            return "OK"

        nums[user["editIndex"]] = v
        user["editMode"] = None
        user["editIndex"] = None

        msg = build_text(f"✔ 已修改為：{v:.1f}", with_main_qr=True)
        reply(reply_token, msg)
        return "OK"

    # 理論上不會跑到這裡
    msg = build_text("編輯模式狀態異常，請輸入「開始」重新啟動流程。", with_main_qr=True)
    reply(reply_token, msg)
    return "OK"


# ===============================
# 確認模式（結束後計算獎金）
# ===============================
def handle_confirm(uid, user, text, reply_token):
    if text == "取消":
        user["confirmMode"] = False
        msg = build_text("已取消結束，可繼續輸入或編輯資料。", with_main_qr=True)
        reply(reply_token, msg)
        return "OK"

    if text == "確認":
        total = sum(user["numbers"])
        bonus = total * 76

        card = result_card(user["name"], total, bonus)

        reply(reply_token, [
            card,
            build_text("如要再算一次請輸入：開始", with_main_qr=True)
        ])

        # 重置使用者狀態
        users[uid] = {
            "step": "name",
            "name": None,
            "numbers": [],
            "editMode": None,
            "editIndex": None,
            "confirmMode": False
        }
        return "OK"

    # 其他輸入 → 再提示一次
    msg = build_text(
        "請使用下方按鈕選擇「確認」或「取消」。",
        extra_qr=quick_reply_confirm()
    )
    reply(reply_token, msg)
    return "OK"


# ===============================
# 本地測試用
# ===============================
if __name__ == "__main__":
    # 本地測試時可用 ngrok / cloudflared 暴露 5000 port
    app.run(host="0.0.0.0", port=5000, debug=True)
