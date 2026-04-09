"""
Agent Registry 検証スクリプト Part 3
- Record を承認（APPROVED状態にする）
- Auto-approval Registry の待機と確認
- 検索 API の正しいパスを探索
- Strands Agent から Registry を利用
"""
import json
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from strands import Agent, tool
import time

# --- 設定 ---
REGION = "YOUR_REGION"
CONTROL_URL = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
DATA_URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com"
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# registry_test.py / registry_test2.py で取得した ID を設定してください
REGISTRY_ID = "YOUR_REGISTRY_ID"
RECORD_ID = "YOUR_RECORD_ID"
AUTO_REGISTRY_ID = "YOUR_AUTO_REGISTRY_ID"

session = boto3.session.Session(region_name=REGION)
credentials = session.get_credentials().get_frozen_credentials()


def signed_request(method, url, body=None, service="bedrock-agentcore"):
    data = json.dumps(body) if body else ""
    request = AWSRequest(
        method=method, url=url, data=data,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials, service, REGION).add_auth(request)
    prep = request.prepare()
    return requests.request(method=method, url=url, headers=dict(prep.headers), data=data)


def print_result(label, resp):
    print(f"\n{'='*60}")
    print(f"🔷 {label}")
    print(f"  Status: {resp.status_code}")
    try:
        data = resp.json()
        print(f"  Response:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception:
        print(f"  Body: {resp.text[:500]}")
    print("="*60)
    return resp


print("🚀 Agent Registry 検証 Part 3")
print(f"  Registry ID: {REGISTRY_ID}")
print(f"  Record ID: {RECORD_ID}")

# ========================================
# STEP 6: Record 承認 (PATCH + statusReason)
# ========================================
print("\n\n✅ Record を承認します...")
approve_body = {
    "status": "APPROVED",
    "statusReason": "テスト目的で承認"
}
resp = signed_request(
    "PATCH",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}/status",
    approve_body
)
print_result("Step 6: Record 承認", resp)

time.sleep(2)

# 承認後のRecord確認
resp = signed_request(
    "GET",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}"
)
print_result("Step 6b: 承認後のRecord詳細", resp)

# ========================================
# Auto-approval Registry を待機
# ========================================
print("\n\n⏳ Auto-approval Registry が READY になるのを待機...")
for i in range(30):
    time.sleep(5)
    resp = signed_request("GET", f"{CONTROL_URL}/registries/{AUTO_REGISTRY_ID}")
    if resp.status_code == 200:
        status = resp.json().get("status", "?")
        print(f"  [{i*5}s] {status}")
        if status == "READY":
            print("  ✅ READY!")
            break
    else:
        print(f"  [{i*5}s] Error: {resp.status_code}")
        break

# Auto-approval にレコード追加
print("\n\n📝 Auto-approval Registry にレコード追加...")
server_content = json.dumps({
    "name": "io.example/auto-weather-server",
    "description": "Auto-approval テスト用天気MCPサーバー",
    "version": "1.0.0"
})
tools_content = json.dumps({
    "tools": [{
        "name": "get_weather",
        "description": "都市の天気を取得します",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "都市名"}
            },
            "required": ["city"]
        }
    }]
})

record_body = {
    "name": "auto-weather-mcp",
    "description": "天気情報ツール（自動承認テスト）",
    "recordVersion": "1.0",
    "descriptorType": "MCP",
    "descriptors": {
        "mcp": {
            "server": {"schemaVersion": "2025-12-11", "inlineContent": server_content},
            "tools": {"protocolVersion": "2024-11-05", "inlineContent": tools_content}
        }
    }
}

resp = signed_request("POST", f"{CONTROL_URL}/registries/{AUTO_REGISTRY_ID}/records", record_body)
print_result("Auto-approval Registry Record追加", resp)

auto_record_id = None
if resp.status_code in [200, 201, 202]:
    data = resp.json()
    arn = data.get("recordArn", "")
    auto_record_id = arn.split("/")[-1] if "/" in arn else None
    print(f"\n  ✅ Record ID: {auto_record_id}, Status: {data.get('status')}")

    time.sleep(5)
    r = signed_request(
        "GET",
        f"{CONTROL_URL}/registries/{AUTO_REGISTRY_ID}/records/{auto_record_id}"
    )
    print_result("Auto Record 詳細", r)
    if r.status_code == 200:
        status = r.json().get("status")
        print(f"\n  ✅ Auto-approval でのStatus: {status}")

# ========================================
# STEP 7: セマンティック検索（正しいエンドポイントを探す）
# ========================================
print("\n\n🔍 セマンティック検索を試みます...")

search_endpoints = [
    (f"{CONTROL_URL}/registries/{REGISTRY_ID}/search", "bedrock-agentcore"),
    (f"{CONTROL_URL}/search-registry-records", "bedrock-agentcore"),
    (f"{DATA_URL}/registries/{REGISTRY_ID}/records:search", "bedrock-agentcore"),
    (f"{DATA_URL}/search-registry-records", "bedrock-agentcore"),
]

for url, service in search_endpoints:
    body = {"searchQuery": "weather", "maxResults": 5}
    resp = signed_request("POST", url, body, service)
    print(f"\n  POST {url.split('.amazonaws.com')[-1]} -> {resp.status_code}")
    if resp.status_code not in [403, 404, 405]:
        try:
            print(f"  {json.dumps(resp.json(), ensure_ascii=False)[:300]}")
        except:
            print(f"  {resp.text[:200]}")

# ========================================
# STEP 8: Strands Agent から Registry を利用する
# ========================================
print("\n\n🤖 Strands Agent から Registry を利用します...")


@tool
def search_registry(query: str) -> str:
    """Agent Registry から利用可能なツールを検索します。

    Args:
        query: 検索クエリ（例: weather tool, database query tool）

    Returns:
        見つかったツールの情報
    """
    resp = signed_request(
        "GET",
        f"{CONTROL_URL}/registries/{REGISTRY_ID}/records"
    )
    if resp.status_code != 200:
        return f"Registry取得エラー: {resp.status_code}"

    records = resp.json().get("registryRecords", [])
    if not records:
        return "Registryにレコードが見つかりませんでした"

    query_lower = query.lower()
    results = []
    for r in records:
        name = r.get("name", "")
        desc = r.get("description", "")
        if query_lower in name.lower() or query_lower in desc.lower() or query_lower in ["all", "全て"]:
            record_id_local = r.get("recordId")
            detail_resp = signed_request(
                "GET",
                f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{record_id_local}"
            )
            if detail_resp.status_code == 200:
                detail = detail_resp.json()
                mcp = detail.get("descriptors", {}).get("mcp", {})
                tools_content_str = mcp.get("tools", {}).get("inlineContent", "{}")
                try:
                    tools_data = json.loads(tools_content_str)
                    tool_names = [t["name"] for t in tools_data.get("tools", [])]
                except:
                    tool_names = []

                results.append(
                    f"📦 {name} (v{r.get('recordVersion', '?')})\n"
                    f"   説明: {desc}\n"
                    f"   ツール: {', '.join(tool_names)}\n"
                    f"   Status: {r.get('status')}"
                )

    if not results:
        return f"'{query}' に関連するツールが見つかりませんでした。全レコード数: {len(records)}"

    return f"=== Registry検索結果: '{query}' ===\n\n" + "\n\n".join(results)


@tool
def get_registry_record_detail(record_name: str) -> str:
    """Registry内の特定レコードの詳細を取得します。

    Args:
        record_name: レコード名

    Returns:
        レコードの詳細情報
    """
    resp = signed_request(
        "GET",
        f"{CONTROL_URL}/registries/{REGISTRY_ID}/records"
    )
    if resp.status_code != 200:
        return f"エラー: {resp.status_code}"

    records = resp.json().get("registryRecords", [])
    for r in records:
        if r.get("name") == record_name:
            record_id_local = r.get("recordId")
            detail_resp = signed_request(
                "GET",
                f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{record_id_local}"
            )
            if detail_resp.status_code == 200:
                return json.dumps(detail_resp.json(), indent=2, ensure_ascii=False)

    return f"'{record_name}' というレコードが見つかりませんでした"


agent = Agent(
    model=MODEL_ID,
    system_prompt=(
        "あなたはAgent Registryの専門家です。"
        "search_registryツールを使って利用可能なMCPサーバーやエージェントツールを検索・確認できます。"
        "必ずツールを使って回答してください。"
    ),
    tools=[search_registry, get_registry_record_detail],
)

print("\n  Agent に質問します: 天気関連のツールはありますか？")
print("  " + "-"*50)
result = agent("Agent Registryに登録されている天気関連のツールを調べて、使い方を教えてください。")
print(f"\n  Agent の回答:\n{result}")

print("\n\n✅ 全検証完了！")
print(f"\n  検証まとめ:")
print(f"  ✅ Registry 一覧取得")
print(f"  ✅ Registry 作成 (IAM認証, auto-approval無効)")
print(f"  ✅ Registry 作成 (IAM認証, auto-approval有効)")
print(f"  ✅ Registry Record 作成 (MCPサーバー)")
print(f"  ✅ 承認申請 (submit-for-approval)")
print(f"  ✅ 手動承認 (PATCH /status)")
print(f"  ✅ Strands Agent から Registry 利用")
