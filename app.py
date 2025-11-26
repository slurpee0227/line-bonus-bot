from flask import Flask, request, jsonify
import requests
import os
import threading

app = Flask(__name__)

LINE_TOKEN = os.getenv("LINE_TOKEN")

# 使用記憶體儲存每個使用者資料
users = {}
lock = threading.Lock()

def get_user(uid):
    with lock:
        if uid not in users:
            users[uid] = {
                "step": "name",
                "name": None,
                "numbers": [],
                "editMode": None,
                "editIndex": None,
                "confirmMode": False
            }
        return users[uid]


# ===============================
# LINE 回覆
# ===============================
def reply(token, msgs):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + LINE_TOKEN,
    }

    if isinstance(msgs, dict):
        msgs = [msgs]

    body = {"replyToken": token, "messages": msgs}

    requests.post(url, headers=headers, json=body)


# ===============================
# Flex UI － 主選單
# ===============================
def main_menu():
    return {
        "type": "flex",
        "altText": "選單",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "操作選單", "weight": "bold", "size": "lg"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    btn("🔢 輸入支數", "輸入支數"),
                    btn("📋 列表", "列表"),
                    btn("✏ 編輯", "編輯"),
                    btn("🔚 結束", "結束"),
                    btn("ℹ️ 說明", "說明"),
                ]
            }
        }
    }


def btn(label, data):
    return {
        "type": "button",
        "style": "primary",
        "action": {
            "type": "message",
            "label": label,
            "text": data
        }
    }


# ===============================
# Flex UI － 計算結果
# ===============================
def result_card(name, total, bonus):
    return {
        "type": "flex",
        "altText": "計算結果",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "✨ 計算完成", "size": "xl", "weight": "bold"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    line("姓名", name),
                    line("總支數", f"{total:.1f}"),
                    line("獎金 (×76)", f"{bonus:.1f} 元")
                ]
            }
        }
    }


def line(label, value):
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "weight": "bold", "size": "sm", "flex": 2},
            {"type": "text", "text": value, "size": "sm", "flex": 3}
        ]
    }


# ===============================
# Utility
# ===============================
def fix1(x):
    return float(f"{x:.1f}")


# ===============================
# Webhook
# ===============================
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json

    # 空事件防呆
    if not body or "events" not in body or not body["events"]:
        return "OK"

    event = body["events"][0]

    if event.get("type") != "message":
        return "OK"

    message = event.get("message", {})
    if message.get("type") != "text":
        return "OK"

    text = message["text"].strip()
    token = event["replyToken"]
    uid = event["source"]["userId"]

    user = get_user(uid)

    # ==========================================
    # 說明
    # ==========================================
    if text == "說明":
        reply(token, {
            "type": "text",
            "text": (
                "【獎金計算小幫手】\n\n"
                "流程：\n"
                "1️⃣ 輸入姓名\n"
                "2️⃣ 輸入支數\n"
                "3️⃣ 列表 / 編輯\n"
                "4️⃣ 結束 → 計算獎金\n"
            )
        })
        return "OK"

    # ==========================================
    # 開始
    # ==========================================
    if text == "開始":
        users[uid] = {
            "step": "name",
            "name": None,
            "numbers": [],
            "editMode": None,
            "editIndex": None,
            "confirmMode": False
        }

        reply(token, [
            {"type": "text", "text": "🟦 步驟 1：請輸入姓名"},
            main_menu()
        ])
        return "OK"

    # ==========================================
    # 如果在編輯模式 → 最高優先
    # ==========================================
    if user["editMode"]:
        return handle_edit(uid, user, text, token)

    # ==========================================
    # 確認模式
    # ==========================================
    if user["confirmMode"]:
        return handle_confirm(uid, user, text, token)

    # ==========================================
    # Step 1：輸入姓名（v3 修正版）
    # ==========================================
    if user["step"] == "name":
        forbidden = ["列表", "編輯", "結束", "返回", "說明", "輸入支數"]

        if text in forbidden:
            reply(token, {
                "type": "text",
                "text": "現在是【輸入姓名】階段，請輸入姓名（不能輸入指令）。"
            })
            return "OK"

        if not text:
            reply(token, {"type": "text", "text": "姓名不可為空白，請重新輸入。"})
            return "OK"

        user["name"] = text
        user["step"] = "input"

        reply(token, [
            {"type": "text", "text": f"👤 姓名：{text}\n\n請開始輸入支數。"},
            main_menu()
        ])
        return "OK"

    # ==========================================
    # 列表
    # ==========================================
    if text == "列表":
        nums = user["numbers"]
        if not nums:
            reply(token, {"type": "text", "text": "📋 尚未輸入任何支數。"})
            return "OK"

        s = "📋【目前支數】\n\n"
        for i, n in enumerate(nums):
            s += f"{i+1}) {n:.1f}\n"

        s += f"\n合計：{sum(nums):.1f}\n共 {len(nums)} 筆"

        reply(token, [
            {"type": "text", "text": s},
            main_menu()
        ])
        return "OK"

    # ==========================================
    # 進入編輯
    # ==========================================
    if text == "編輯":
        if not user["numbers"]:
            reply(token, {"type": "text", "text": "目前沒有資料可編輯。"})
            return "OK"

        user["editMode"] = "selectIndex"
        reply(token, {"type": "text", "text": "請輸入要編輯的筆數（例：1）"})
        return "OK"

    # ==========================================
    # 結束
    # ==========================================
    if text == "結束":
        if not user["numbers"]:
            reply(token, {"type": "text", "text": "目前沒有資料可結束。"})
            return "OK"

        # 預覽
        nums = user["numbers"]
        s = "📋【結束前預覽】\n\n"
        for i, n in enumerate(nums):
            s += f"{i+1}) {n:.1f}\n"

        s += f"\n合計：{sum(nums):.1f}\n\n請回覆：確認 / 取消"

        user["confirmMode"] = True
        reply(token, {"type": "text", "text": s})
        return "OK"

    # ==========================================
    # Step 2：輸入支數
    # ==========================================
    return handle_number(uid, user, text, token)
# ===============================
# 支數輸入
# ===============================
def handle_number(uid, user, text, token):
    # 禁止文字指令誤觸
    forbidden = ["編輯", "列表", "結束", "返回", "說明"]
    if text in forbidden:
        reply(token, {
            "type": "text",
            "text": "輸入支數時不可使用指令喔。"
        })
        return "OK"

    try:
        v = fix1(float(text))
    except:
        reply(token, {"type": "text", "text": "請輸入有效的數字（可含小數）。"})
        return "OK"

    user["numbers"].append(v)

    reply(token, [
        {"type": "text", "text": f"✔ 已加入：{v:.1f}\n目前共有 {len(user['numbers'])} 筆。"},
        main_menu()
    ])
    return "OK"


# ===============================
# 編輯模式
# ===============================
def handle_edit(uid, user, text, token):
    mode = user["editMode"]
    nums = user["numbers"]

    # 返回
    if text == "返回":
        user["editMode"] = None
        user["editIndex"] = None
        reply(token, {"type": "text", "text": "已退出編輯模式。"})
        return "OK"

    # 選擇哪一筆
    if mode == "selectIndex":
        try:
            i = int(text) - 1
            if i < 0 or i >= len(nums):
                raise Exception()
        except:
            reply(token, {"type": "text", "text": f"請輸入 1 ~ {len(nums)} 的編號"})
            return "OK"

        user["editIndex"] = i
        user["editMode"] = "chooseAction"

        reply(token, {
            "type": "text",
            "text": f"你選擇第 {i+1} 筆：{nums[i]:.1f}\n請輸入：修改 或 刪除"
        })
        return "OK"

    # 修改 or 刪除
    if mode == "chooseAction":
        if text == "刪除":
            removed = nums.pop(user["editIndex"])
            user["editMode"] = None
            user["editIndex"] = None
            reply(token, {"type": "text", "text": f"✔ 已刪除：{removed:.1f}"})
            return "OK"

        if text == "修改":
            user["editMode"] = "inputValue"
            reply(token, {"type": "text", "text": "請輸入新值："})
            return "OK"

        reply(token, {"type": "text", "text": "請輸入：修改 或 刪除"})
        return "OK"

    # 新值輸入
    if mode == "inputValue":
        try:
            v = fix1(float(text))
        except:
            reply(token, {"type": "text", "text": "請輸入有效數字。"})
            return "OK"

        nums[user["editIndex"]] = v
        user["editMode"] = None
        user["editIndex"] = None

        reply(token, {"type": "text", "text": f"✔ 已修改為：{v:.1f}"})
        return "OK"


# ===============================
# 確認模式
# ===============================
def handle_confirm(uid, user, text, token):
    if text == "取消":
        user["confirmMode"] = False
        reply(token, {"type": "text", "text": "已取消結束，可繼續輸入資料。"})
        return "OK"

    if text == "確認":
        total = sum(user["numbers"])
        bonus = total * 76

        card = result_card(user["name"], total, bonus)

        reply(token, [
            card,
            {"type": "text", "text": "如要再算一次請輸入：開始"}
        ])

        # 重置
        users[uid] = {
            "step": "name",
            "name": None,
            "numbers": [],
            "editMode": None,
            "editIndex": None,
            "confirmMode": False
        }
        return "OK"

    reply(token, {"type": "text", "text": "請輸入：確認 或 取消"})
    return "OK"



# ===============================
# 主程式（本地測試）
# ===============================
if __name__ == "__main__":
    app.run(debug=True, port=5000)
