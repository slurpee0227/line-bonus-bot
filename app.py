from flask import Flask, request, jsonify
import requests
import os
import threading

app = Flask(__name__)

# ===============================
# 配置
# ===============================
LINE_TOKEN = os.getenv("LINE_TOKEN")

# 全域使用者資料（Render 免費版可用）
users = {}
lock = threading.Lock()

def get_user(uid):
    with lock:
        if uid not in users:
            users[uid] = {
                "step": "name",
                "name": None,
                "numbers": [],
                "editMode": None,       # None / selectIndex / chooseAction / inputValue
                "editIndex": None,
                "confirmMode": False
            }
        return users[uid]

# ===============================
# 工具函數
# ===============================
def reply(token, msgs):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + LINE_TOKEN,
    }

    if isinstance(msgs, dict):
        msgs = [msgs]

    data = {
        "replyToken": token,
        "messages": msgs
    }

    requests.post(url, headers=headers, json=data)


def fix1(num):
    return float(f"{num:.1f}")

# ===============================
# 主 Webhook
# ===============================
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json

    event = body["events"][0]
    if event["type"] != "message" or event["message"]["type"] != "text":
        return "OK"

    text = event["message"]["text"].strip()
    token = event["replyToken"]
    uid = event["source"]["userId"]

    user = get_user(uid)

    # ===============================
    # 說明
    # ===============================
    if text == "說明":
        reply(token, {
            "type": "text",
            "text": "【獎金計算小幫手】\n\n指令：\n• 開始\n• 列表\n• 編輯\n• 結束\n• 說明"
        })
        return "OK"

    # ===============================
    # 開始 / 首頁 → 重置流程
    # ===============================
    if text in ["開始", "首頁"]:
        users[uid] = {
            "step": "name",
            "name": None,
            "numbers": [],
            "editMode": None,
            "editIndex": None,
            "confirmMode": False
        }

        reply(token, {"type": "text", "text": "🟦 步驟 1：請輸入姓名"})
        return "OK"

    # ===============================
    # 如果正在編輯模式 → 最優先
    # ===============================
    if user["editMode"]:
        return handle_edit_mode(uid, user, text, token)

    # ===============================
    # 結束確認模式
    # ===============================
    if user["confirmMode"]:
        return handle_confirm_mode(uid, user, text, token)

    # ===============================
    # Step 1：輸入姓名
    # ===============================
    if user["step"] == "name":
        user["name"] = text
        user["step"] = "input"

        reply(token, {
            "type": "text",
            "text": f"👤 姓名：{text}\n\n🟩 步驟 2：請開始輸入支數（可含小數）\n可用指令：列表 / 編輯 / 結束"
        })
        return "OK"

    # ===============================
    # 列表
    # ===============================
    if text == "列表":
        return handle_list(user, token)

    # ===============================
    # 進入編輯模式
    # ===============================
    if text == "編輯":
        if not user["numbers"]:
            reply(token, {"type": "text", "text": "尚無資料可編輯。"})
            return "OK"

        user["editMode"] = "selectIndex"
        reply(token, {"type": "text", "text": "🔧 請輸入要編輯的筆數（例如：1）\n或輸入「返回」離開編輯模式。"})
        return "OK"

    # ===============================
    # 結束 → 預覽
    # ===============================
    if text == "結束":
        return enter_preview(uid, user, token)

    # ===============================
    # Step 2：輸入支數
    # ===============================
    return handle_number_input(uid, user, text, token)


# ===============================
# 支數輸入
# ===============================
def handle_number_input(uid, user, text, token):
    try:
        v = fix1(float(text))
    except:
        reply(token, {"type": "text", "text": "請輸入數字（可含小數）。"})
        return "OK"

    user["numbers"].append(v)

    reply(token, {"type": "text",
                  "text": f"✔ 已加入：{v:.1f}\n目前共有 {len(user['numbers'])} 筆。"})
    return "OK"


# ===============================
# 列表
# ===============================
def handle_list(user, token):
    nums = user["numbers"]

    if not nums:
        reply(token, {"type": "text", "text": "📋 尚未輸入任何支數。"})
        return "OK"

    text = "📋【目前支數】\n\n"
    for i, n in enumerate(nums):
        text += f"{i+1}) {n:.1f}\n"

    total = sum(nums)
    text += f"\n合計：{total:.1f}\n共 {len(nums)} 筆"

    reply(token, {"type": "text", "text": text})
    return "OK"


# ===============================
# 編輯模式
# ===============================
def handle_edit_mode(uid, user, text, token):
    mode = user["editMode"]
    nums = user["numbers"]

    # 返回
    if text == "返回":
        user["editMode"] = None
        user["editIndex"] = None
        reply(token, {"type": "text", "text": "已退出編輯模式。"})
        return "OK"

    # 選筆數
    if mode == "selectIndex":
        try:
            i = int(text) - 1
            if i < 0 or i >= len(nums):
                raise Exception()
        except:
            reply(token, {"type": "text", "text": f"請輸入 1 ~ {len(nums)} 的數字。"})
            return "OK"

        user["editIndex"] = i
        user["editMode"] = "chooseAction"

        reply(token, {
            "type": "text",
            "text": f"你選擇第 {i+1} 筆：{nums[i]:.1f}\n請輸入：「修改」或「刪除」"
        })
        return "OK"

    # 選擇修改/刪除
    if mode == "chooseAction":
        if text == "刪除":
            removed = nums.pop(user["editIndex"])
            user["editMode"] = None
            user["editIndex"] = None

            reply(token, {"type": "text", "text": f"✔ 已刪除：{removed:.1f}"})
            return "OK"

        if text == "修改":
            user["editMode"] = "inputValue"
            reply(token, {"type": "text", "text": "請輸入新的數值："})
            return "OK"

        reply(token, {"type": "text", "text": "請輸入：修改 / 刪除"})
        return "OK"

    # 修改新值
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
# 結束 → 預覽
# ===============================
def enter_preview(uid, user, token):
    nums = user["numbers"]
    if not nums:
        reply(token, {"type": "text", "text": "目前沒有資料可結束。"})
        return "OK"

    text = "📋【結束前預覽】\n\n"
    for i, n in enumerate(nums):
        text += f"{i+1}) {n:.1f}\n"

    total = sum(nums)
    text += f"\n合計：{total:.1f}\n\n回覆：確認 / 取消"

    user["confirmMode"] = True

    reply(token, {"type": "text", "text": text})
    return "OK"


# ===============================
# 確認模式
# ===============================
def handle_confirm_mode(uid, user, text, token):
    if text == "取消":
        user["confirmMode"] = False
        reply(token, {"type": "text", "text": "已取消結束，可繼續輸入。"})
        return "OK"

    if text == "確認":
        total = sum(user["numbers"])
        bonus = total * 76

        reply(token, {
            "type": "text",
            "text": f"✨【計算完成】\n\n姓名：{user['name']}\n總支數：{total:.1f}\n獎金：{bonus:.1f} 元\n\n如要再算一次請輸入：開始"
        })

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

    reply(token, {"type": "text", "text": "請輸入：確認 / 取消"})
    return "OK"


# ===============================
# 本地端啟動（Render 不會用到）
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
