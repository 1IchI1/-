"""
Slack → Claude Code 半自動化ボット
Slackの指定チャンネルにメッセージを送ると Claude が自動実行し、結果をSlackに返す
"""

import os
import time
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# .env から設定を読み込む（ハードコード厳禁）
load_dotenv(Path(__file__).parent / ".env")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
CHANNEL_ID      = os.environ.get("CHANNEL_ID", "")
WORK_DIR        = r"C:\Users\a3225\Desktop\出力"
CHECK_INTERVAL  = 20  # 何秒ごとにSlackを確認するか

# 許可ユーザーIDリスト（空の場合は全員拒否して安全側に倒す）
_raw = os.environ.get("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = {uid.strip() for uid in _raw.split(",") if uid.strip()}

if not SLACK_BOT_TOKEN:
    print("[ERROR] SLACK_BOT_TOKEN が設定されていません。.env を確認してください。")
    sys.exit(1)

if not CHANNEL_ID:
    print("[ERROR] CHANNEL_ID が設定されていません。.env を確認してください。")
    sys.exit(1)

if not ALLOWED_USER_IDS:
    print("[ERROR] ALLOWED_USER_IDS が設定されていません。.env に許可ユーザーIDを設定してください。")
    sys.exit(1)

client = WebClient(token=SLACK_BOT_TOKEN)
last_ts = None


def get_bot_user_id():
    res = client.auth_test()
    return res["user_id"]


def post_message(text):
    client.chat_postMessage(channel=CHANNEL_ID, text=text)


def is_authorized(user_id: str) -> bool:
    return user_id in ALLOWED_USER_IDS


def run_claude(instruction: str) -> str:
    """Claude Code を非対話モードで実行して結果を返す"""
    result = subprocess.run(
        ["claude", "-p", instruction],
        capture_output=True,
        text=True,
        cwd=WORK_DIR,
        encoding="utf-8",
        timeout=300,  # 5分でタイムアウト
    )
    output = result.stdout.strip()
    if result.returncode != 0 and result.stderr:
        output += f"\n⚠️ エラー：{result.stderr.strip()}"
    return output if output else "（出力なし）"


def main():
    global last_ts
    bot_user_id = get_bot_user_id()
    print(f"[OK] 起動完了。チャンネル {CHANNEL_ID} を監視中...")
    print(f"[OK] 許可ユーザー数: {len(ALLOWED_USER_IDS)}")
    post_message("🤖 Claude Bot 起動しました。許可されたユーザーのみ指示できます。")

    # 起動時点の最新メッセージを記録（起動前のメッセージを処理しない）
    try:
        res = client.conversations_history(channel=CHANNEL_ID, limit=1)
        if res["messages"]:
            last_ts = res["messages"][0]["ts"]
    except Exception:
        pass

    while True:
        try:
            res = client.conversations_history(channel=CHANNEL_ID, limit=5)
            messages = res.get("messages", [])

            for msg in reversed(messages):
                ts   = msg.get("ts")
                user = msg.get("user", "")
                text = msg.get("text", "").strip()

                if last_ts and float(ts) <= float(last_ts):
                    continue
                if user == bot_user_id:
                    continue
                if not text:
                    continue

                last_ts = ts

                # 認証チェック
                if not is_authorized(user):
                    print(f"[WARN] 未許可ユーザー {user} からの指示を拒否しました。")
                    post_message(f"⛔ <@{user}> このボットを使用する権限がありません。")
                    continue

                print(f"[MSG] 指示受信 ({user})：{text}")
                post_message(f"⏳ 実行中：`{text}`")

                try:
                    output = run_claude(text)
                except subprocess.TimeoutExpired:
                    output = "⚠️ タイムアウト：処理が5分を超えたため中断しました。"

                if len(output) > 2800:
                    output = output[:2800] + "\n…（省略）"

                post_message(f"✅ 完了：\n```{output}```")

        except SlackApiError as e:
            print(f"[ERR] Slack API エラー：{e}")
        except KeyboardInterrupt:
            print("\n[STOP] 停止しました。")
            post_message("🛑 Claude Bot を停止しました。")
            sys.exit(0)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
