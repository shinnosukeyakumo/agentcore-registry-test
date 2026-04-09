"""
Registry から email-sender を発見して使う Strands Agent
実行: uv run python email_agent.py
"""
import json
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from strands import Agent, tool
from strands.models.bedrock import BedrockModel

# --- 設定 ---
REGION = "YOUR_REGION"
SES_REGION = "YOUR_SES_REGION"
BASE_URL = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
REGISTRY_ID = "YOUR_REGISTRY_ID"  # registry_test.py で作成した Registry ID
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
FROM_EMAIL = "your-verified@example.com"  # SES で検証済みのメールアドレス

session = boto3.session.Session(region_name=REGION)
credentials = session.get_credentials().get_frozen_credentials()

# Strands に明示的にリージョンを指定
bedrock_model = BedrockModel(model_id=MODEL_ID, region_name=REGION)


def signed_request(method, path, body=None):
    url = BASE_URL + path
    data = json.dumps(body) if body else ""
    req = AWSRequest(method=method, url=url, data=data,
                     headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(req)
    prep = req.prepare()
    return requests.request(method=method, url=url, headers=dict(prep.headers), data=data)


# ========================================
# STEP 1: Registry から email-sender を発見
# ========================================
def discover_email_tool_from_registry() -> dict | None:
    """Registryを検索してemail-senderのメタデータを取得する"""
    resp = signed_request("GET", f"/registries/{REGISTRY_ID}/records")
    if resp.status_code != 200:
        return None

    records = resp.json().get("registryRecords", [])
    target = next((r for r in records if r.get("name") == "email-sender"), None)
    if not target:
        return None

    # 詳細を取得
    record_id = target.get("recordId")
    detail = signed_request("GET", f"/registries/{REGISTRY_ID}/records/{record_id}").json()

    mcp = detail.get("descriptors", {}).get("mcp", {})
    tools_raw = mcp.get("tools", {}).get("inlineContent", "{}")
    tools_data = json.loads(tools_raw)

    return {
        "name": detail.get("name"),
        "status": detail.get("status"),
        "tools": tools_data.get("tools", []),
    }


print("🔍 Registry から email-sender を探しています...")
email_tool_info = discover_email_tool_from_registry()

if not email_tool_info:
    print("❌ email-sender が Registry に見つかりません")
    exit(1)

print(f"✅ 発見！ [{email_tool_info['status']}] {email_tool_info['name']}")
print(f"   利用可能なツール: {[t['name'] for t in email_tool_info['tools']]}")


# ========================================
# STEP 2: Strands Agent のツールを定義
# ========================================
@tool
def send_email(to: str, subject: str, body: str) -> str:
    """メールを送信します。

    Args:
        to: 送信先メールアドレス
        subject: メールの件名
        body: メールの本文

    Returns:
        送信結果メッセージ
    """
    print(f"\n  📧 [email-sender] メール送信")
    print(f"     To: {to}")
    print(f"     Subject: {subject}")
    print(f"     Body: {body[:50]}...")

    ses = boto3.client("sesv2", region_name=SES_REGION)
    ses.send_email(
        FromEmailAddress=FROM_EMAIL,
        Destination={"ToAddresses": [to]},
        Content={
            "Simple": {
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            }
        },
    )
    return f"✅ メール送信完了\n  宛先: {to}\n  件名: {subject}"


# ========================================
# STEP 3: Strands Agent を作成
# ========================================
agent = Agent(
    model=bedrock_model,
    system_prompt=(
        "あなたはメール送信アシスタントです。\n"
        "ユーザーの指示に従い send_email ツールを使ってメールを送ってください。\n"
        "必要な情報（宛先・件名・本文）が不足している場合は確認してください。"
    ),
    tools=[send_email],
)

# ========================================
# STEP 4: 実行
# ========================================
print("\n" + "="*50)
print("🤖 email-sender Agent 起動")
print("="*50)
print("'quit' で終了\n")

while True:
    try:
        user_input = input("あなた > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n終了します")
        break

    if not user_input or user_input.lower() in ["quit", "exit", "q"]:
        print("終了します")
        break

    print("\nAgent > ", end="", flush=True)
    response = agent(user_input)
    print(f"{response}\n")
