"""
Agent Registry 検証スクリプト
直接 HTTP + SigV4 認証でRegistry APIを呼び出す
"""
import json
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import time

# --- 設定 ---
REGION = "YOUR_REGION"
BASE_URL = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
REGISTRY_NAME = "my-test-registry"

# boto3 session から認証情報取得
session = boto3.session.Session(region_name=REGION)
credentials = session.get_credentials().get_frozen_credentials()


def signed_request(method, path, body=None):
    """SigV4 署名付きリクエストを送る"""
    url = BASE_URL + path
    data = json.dumps(body) if body else ""

    request = AWSRequest(
        method=method,
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(request)

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


def wait_for_ready(registry_id, max_wait=60):
    """Registryが READY になるまで待機"""
    print(f"\n⏳ Registry が READY 状態になるのを待機中...")
    for i in range(max_wait // 5):
        resp = signed_request("GET", f"/registries/{registry_id}")
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "UNKNOWN")
            print(f"  [{i*5}s] Status: {status}")
            if status == "READY":
                return True
        time.sleep(5)
    return False


def extract_id_from_arn(arn):
    """ARN の最後のセグメントをIDとして返す"""
    if arn and "/" in arn:
        return arn.split("/")[-1]
    return None


print("\n🚀 Agent Registry 検証開始！")
print(f"  Region: {REGION}")
print(f"  Endpoint: {BASE_URL}")

# ========================================
# STEP 1: 既存のRegistryを確認
# ========================================
resp = signed_request("GET", "/registries")
result = print_result("Step 1: Registry 一覧取得", resp)

registry_id = None
if resp.status_code == 200:
    registries = resp.json().get("registries", [])
    # READY なものを優先して探す
    for r in sorted(registries, key=lambda x: x.get("status") == "READY", reverse=True):
        if r.get("name") == REGISTRY_NAME:
            registry_id = r.get("registryId") or extract_id_from_arn(r.get("registryArn"))
            print(f"\n  📌 既存Registry発見: {registry_id} (status: {r.get('status')})")
            break

# ========================================
# STEP 2: Registry 作成（なければ）
# ========================================
if not registry_id:
    registry_body = {
        "name": REGISTRY_NAME,
        "description": "Agent Registry 検証用",
        "authorizationConfig": {
            "authorizationType": "IAM"
        }
    }
    resp = signed_request("POST", "/registries", registry_body)
    result = print_result("Step 2: Registry 作成", resp)

    if resp.status_code in [200, 201, 202]:
        data = resp.json()
        registry_id = extract_id_from_arn(data.get("registryArn")) or data.get("registryId")
        print(f"\n  ✅ Registry作成成功! ID: {registry_id}")
else:
    print(f"\n  ✅ 既存Registryを使用: {registry_id}")

if not registry_id:
    print("  ❌ Registry IDが取得できませんでした。終了します。")
    exit(1)

print(f"\n📌 使用するRegistry ID: {registry_id}")

# ========================================
# READY 状態になるまで待機
# ========================================
ready = wait_for_ready(registry_id)
if not ready:
    print("  ⚠️  タイムアウト。現在の状態で続行します...")

# Registry 詳細確認
resp = signed_request("GET", f"/registries/{registry_id}")
print_result("Registry 詳細", resp)

# ========================================
# STEP 3: Registry Record 作成 (MCPサーバー)
# ========================================
print("\n\n📝 Registry Record を作成します...")

server_content = json.dumps({
    "name": "io.example/weather-server",
    "description": "天気情報を提供するMCPサーバー（テスト用）",
    "version": "1.0.0"
})

tools_content = json.dumps({
    "tools": [
        {
            "name": "get_current_weather",
            "description": "指定した都市の現在の天気を取得します",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "都市名（例: Tokyo, New York）"
                    }
                },
                "required": ["city"]
            }
        },
        {
            "name": "get_forecast",
            "description": "指定した都市の5日間天気予報を取得します",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "都市名"
                    },
                    "days": {
                        "type": "integer",
                        "description": "予報日数（1-5）"
                    }
                },
                "required": ["city"]
            }
        }
    ]
})

record_body = {
    "name": "weather-mcp-server",
    "description": "天気情報MCPサーバー - get_current_weather と get_forecast ツールを提供",
    "recordVersion": "1.0",
    "descriptorType": "MCP",
    "descriptors": {
        "mcp": {
            "server": {
                "schemaVersion": "2025-12-11",
                "inlineContent": server_content
            },
            "tools": {
                "protocolVersion": "2024-11-05",
                "inlineContent": tools_content
            }
        }
    }
}

resp = signed_request("POST", f"/registries/{registry_id}/records", record_body)
result = print_result("Step 3: Registry Record 作成 (MCPサーバー)", resp)

record_id = None
if resp.status_code in [200, 201, 202]:
    data = resp.json()
    record_id = extract_id_from_arn(data.get("recordArn")) or data.get("recordId")
    print(f"\n  ✅ Record作成成功! ID: {record_id}")
    print(f"  Status: {data.get('status')}")
else:
    # 既存のRecord一覧から探す
    list_resp = signed_request("GET", f"/registries/{registry_id}/records")
    if list_resp.status_code == 200:
        records = list_resp.json().get("records", [])
        for r in records:
            if r.get("name") == "weather-mcp-server":
                record_id = r.get("recordId") or extract_id_from_arn(r.get("recordArn"))
                print(f"  既存のRecord ID: {record_id}")
                break

# Record 一覧表示
resp = signed_request("GET", f"/registries/{registry_id}/records")
print_result("Step 3b: Record 一覧", resp)

if record_id:
    # ========================================
    # STEP 4: 承認申請
    # ========================================
    resp = signed_request(
        "POST",
        f"/registries/{registry_id}/records/{record_id}/submit-for-approval",
        {}
    )
    print_result("Step 4: 承認申請", resp)

    time.sleep(2)

    # ========================================
    # STEP 5: Record 詳細確認
    # ========================================
    resp = signed_request("GET", f"/registries/{registry_id}/records/{record_id}")
    print_result("Step 5: Record 詳細", resp)
    if resp.status_code == 200:
        status = resp.json().get("status")
        print(f"  現在のStatus: {status}")

    # ========================================
    # STEP 6: 承認 (管理者として)
    # ========================================
    approve_body = {
        "status": "APPROVED",
        "statusReason": "テスト目的で承認"
    }
    resp = signed_request(
        "PATCH",
        f"/registries/{registry_id}/records/{record_id}/status",
        approve_body
    )
    print_result("Step 6: Record 承認", resp)

    time.sleep(2)

    # 承認後の詳細確認
    resp = signed_request("GET", f"/registries/{registry_id}/records/{record_id}")
    print_result("Step 6b: 承認後のRecord 詳細", resp)

# ========================================
# STEP 7: Record 一覧検索
# ========================================
print("\n\n🔍 Registry 検索を試みます...")

resp = signed_request("GET", f"/registries/{registry_id}/records?searchQuery=weather")
print_result("Step 7: 検索 (GET + query param)", resp)

print("\n\n✨ 検証完了！")
print(f"  Registry ID: {registry_id}")
print(f"  Record ID: {record_id}")
