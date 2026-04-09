"""
Agent Registry 検証スクリプト Part 2
- 承認ワークフロー（auto-approval有効版）
- 正しいAPIパスを探索
- セマンティック検索
- Strands Agent から Registry を使う
"""
import json
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import time

# --- 設定 ---
REGION = "YOUR_REGION"
CONTROL_URL = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
DATA_URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com"

# registry_test.py で作成した ID を設定してください
REGISTRY_ID = "YOUR_REGISTRY_ID"
RECORD_ID = "YOUR_RECORD_ID"

session = boto3.session.Session(region_name=REGION)
credentials = session.get_credentials().get_frozen_credentials()


def signed_request(method, url, body=None, service="bedrock-agentcore"):
    """SigV4 署名付きリクエストを送る"""
    data = json.dumps(body) if body else ""
    request = AWSRequest(
        method=method,
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials, service, REGION).add_auth(request)
    prep = request.prepare()
    resp = requests.request(
        method=method,
        url=url,
        headers=dict(prep.headers),
        data=data,
    )
    return resp


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


def try_paths(label, method, paths, body=None, service="bedrock-agentcore"):
    """複数パスを試して動くものを探す"""
    for url in paths:
        resp = signed_request(method, url, body, service)
        print(f"\n  試行: {method} {url} -> {resp.status_code}")
        if resp.status_code not in [403, 404, 405]:
            print_result(f"{label} (成功: {url})", resp)
            return resp, url
        elif resp.status_code == 404:
            try:
                print(f"  404: {resp.json()}")
            except:
                pass
    print(f"\n  ❌ {label}: 全パスで失敗")
    return None, None


print("🚀 Agent Registry 検証 Part 2")
print(f"  Registry ID: {REGISTRY_ID}")
print(f"  Record ID: {RECORD_ID}")

# ========================================
# Registry 詳細確認
# ========================================
resp = signed_request(
    "GET",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}",
    service="bedrock-agentcore"
)
print_result("Registry 詳細", resp)

# ========================================
# 新しいRegistry（auto-approval有効）を作成
# ========================================
print("\n\n📋 Auto-approval有効のRegistry を作成...")
auto_reg_body = {
    "name": "my-autoapproval-registry",
    "description": "Auto-approval有効のテスト用Registry",
    "authorizationConfig": {"authorizationType": "IAM"},
    "approvalConfiguration": {"autoApproval": True}
}

resp = signed_request(
    "POST", f"{CONTROL_URL}/registries", auto_reg_body,
    service="bedrock-agentcore"
)
print_result("Auto-approval Registry 作成", resp)

auto_registry_id = None
if resp.status_code in [200, 201, 202]:
    data = resp.json()
    arn = data.get("registryArn", "")
    auto_registry_id = arn.split("/")[-1] if "/" in arn else None
    print(f"\n  ✅ Auto-approval Registry ID: {auto_registry_id}")

    # READY になるまで待機
    print("\n⏳ READY を待機中...")
    for i in range(12):
        time.sleep(5)
        r = signed_request("GET", f"{CONTROL_URL}/registries/{auto_registry_id}", service="bedrock-agentcore")
        status = r.json().get("status", "?")
        print(f"  [{i*5}s] {status}")
        if status == "READY":
            break

if auto_registry_id:
    # Auto-approval Registry に MCPレコードを追加
    server_content = json.dumps({
        "name": "io.example/auto-weather-server",
        "description": "Auto-approval テスト用天気MCPサーバー",
        "version": "1.0.0"
    })
    tools_content = json.dumps({
        "tools": [{
            "name": "get_weather",
            "description": "都市の天気を取得",
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
    resp = signed_request(
        "POST", f"{CONTROL_URL}/registries/{auto_registry_id}/records",
        record_body, service="bedrock-agentcore"
    )
    print_result("Auto-approval Registry にRecord追加", resp)

    if resp.status_code in [200, 201, 202]:
        data = resp.json()
        arn = data.get("recordArn", "")
        auto_record_id = arn.split("/")[-1] if "/" in arn else None
        print(f"\n  Record ID: {auto_record_id}, Status: {data.get('status')}")

        # 少し待ってRecord確認
        time.sleep(3)
        r = signed_request(
            "GET", f"{CONTROL_URL}/registries/{auto_registry_id}/records/{auto_record_id}",
            service="bedrock-agentcore"
        )
        print_result("Auto Record 詳細", r)
        print(f"\n  ✅ Auto-approval Status: {r.json().get('status')}")

# ========================================
# 手動承認ワークフロー（元のRegistry）
# 正しいAPIパスを探索
# ========================================
print("\n\n🔍 承認APIのパスを探索中...")

submit_paths = [
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}/submit-for-approval",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}:submitForApproval",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}/approval",
]
try_paths("Submit for approval", "POST", submit_paths, {}, service="bedrock-agentcore")

status_paths = [
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}/status",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{RECORD_ID}",
]
try_paths("Record status 更新", "PATCH", status_paths, {"status": "APPROVED"}, service="bedrock-agentcore")

# ========================================
# セマンティック検索 - データプレーンを試す
# ========================================
print("\n\n🔍 セマンティック検索を試みます...")

search_urls = [
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/search",
    f"{DATA_URL}/registries/{REGISTRY_ID}/records/search",
    f"{DATA_URL}/search",
    f"{DATA_URL}/registries/search",
]

for url in search_urls:
    body = {"searchQuery": "weather forecast", "maxResults": 5}
    resp = signed_request("POST", url, body, service="bedrock-agentcore")
    print(f"\n  POST {url} -> {resp.status_code}")
    if resp.status_code not in [403, 404, 405]:
        try:
            print(f"  Response: {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
        except:
            print(f"  Body: {resp.text[:300]}")

# ========================================
# Record 一覧（フィルター検索として）
# ========================================
print("\n\n📋 Record 一覧（フィルタリング）")
resp = signed_request(
    "GET",
    f"{CONTROL_URL}/registries/{REGISTRY_ID}/records",
    service="bedrock-agentcore"
)
print_result("Record 一覧", resp)

print("\n\n✅ 検証サマリー")
print(f"  Manual Registry: {REGISTRY_ID}")
print(f"    Record: {RECORD_ID} (status: DRAFT)")
if auto_registry_id:
    print(f"  Auto-approval Registry: {auto_registry_id}")
