"""
Agent Registry × Strands Agent 対話デモ
ターミナルで実行: uv run python demo.py
"""
import json
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from strands import Agent, tool

# --- 設定 ---
REGION = "YOUR_REGION"
CONTROL_URL = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
REGISTRY_ID = "YOUR_REGISTRY_ID"  # registry_test.py で作成した Registry ID
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

session = boto3.session.Session(region_name=REGION)
credentials = session.get_credentials().get_frozen_credentials()


def signed_request(method, url, body=None):
    data = json.dumps(body) if body else ""
    req = AWSRequest(method=method, url=url, data=data,
                     headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(req)
    prep = req.prepare()
    return requests.request(method=method, url=url, headers=dict(prep.headers), data=data)


# ========================================
# Registry を操作するツール群
# ========================================

@tool
def list_registry_tools() -> str:
    """Agent Registry に登録されている全ツールを一覧表示します。

    Returns:
        登録済みツールの一覧
    """
    resp = signed_request("GET", f"{CONTROL_URL}/registries/{REGISTRY_ID}/records")
    if resp.status_code != 200:
        return f"エラー: {resp.status_code} - {resp.text}"

    records = resp.json().get("registryRecords", [])
    if not records:
        return "Registryにツールが登録されていません。"

    lines = [f"📦 Registry に {len(records)} 件のツールが登録されています:\n"]
    for r in records:
        status_icon = "✅" if r.get("status") == "APPROVED" else "⏳"
        lines.append(
            f"{status_icon} [{r.get('status')}] {r.get('name')} (v{r.get('recordVersion', '?')})\n"
            f"   {r.get('description', '説明なし')}"
        )
    return "\n".join(lines)


@tool
def search_registry(query: str) -> str:
    """Agent Registry からキーワードでツールを検索します。

    Args:
        query: 検索キーワード（例: 天気, database, email）

    Returns:
        検索結果
    """
    resp = signed_request("GET", f"{CONTROL_URL}/registries/{REGISTRY_ID}/records")
    if resp.status_code != 200:
        return f"エラー: {resp.status_code}"

    records = resp.json().get("registryRecords", [])
    query_lower = query.lower()

    matched = [
        r for r in records
        if query_lower in r.get("name", "").lower()
        or query_lower in r.get("description", "").lower()
    ]

    if not matched:
        all_names = [r.get("name") for r in records]
        return f"'{query}' に一致するツールが見つかりませんでした。\n登録済み: {all_names}"

    lines = [f"🔍 '{query}' の検索結果: {len(matched)} 件\n"]
    for r in matched:
        lines.append(f"✅ {r.get('name')} - {r.get('description')}")
    return "\n".join(lines)


@tool
def get_tool_detail(tool_name: str) -> str:
    """Registry に登録されたツールの詳細（使い方・パラメータ）を取得します。

    Args:
        tool_name: ツール名（例: weather-mcp-server）

    Returns:
        ツールの詳細情報
    """
    resp = signed_request("GET", f"{CONTROL_URL}/registries/{REGISTRY_ID}/records")
    if resp.status_code != 200:
        return f"エラー: {resp.status_code}"

    records = resp.json().get("registryRecords", [])
    target = next((r for r in records if r.get("name") == tool_name), None)

    if not target:
        names = [r.get("name") for r in records]
        return f"'{tool_name}' が見つかりません。\n利用可能: {names}"

    record_id = target.get("recordId")
    detail = signed_request(
        "GET", f"{CONTROL_URL}/registries/{REGISTRY_ID}/records/{record_id}"
    ).json()

    mcp = detail.get("descriptors", {}).get("mcp", {})
    tools_raw = mcp.get("tools", {}).get("inlineContent", "{}")
    server_raw = mcp.get("server", {}).get("inlineContent", "{}")

    try:
        tools_data = json.loads(tools_raw)
        server_data = json.loads(server_raw)
    except Exception:
        return "ツール情報のパースに失敗しました"

    lines = [
        f"📦 {detail.get('name')} v{detail.get('recordVersion')}",
        f"   ステータス: {detail.get('status')}",
        f"   サーバー: {server_data.get('name')} - {server_data.get('description')}",
        "",
        "🔧 利用可能なツール:",
    ]
    for t in tools_data.get("tools", []):
        props = t.get("inputSchema", {}).get("properties", {})
        required = t.get("inputSchema", {}).get("required", [])
        lines.append(f"\n  • {t['name']}: {t.get('description', '')}")
        for param, info in props.items():
            req_mark = "（必須）" if param in required else "（任意）"
            lines.append(f"    - {param}{req_mark}: {info.get('description', '')}")

    return "\n".join(lines)


@tool
def register_new_tool(name: str, description: str, tool_description: str) -> str:
    """新しいツール（MCPサーバー）を Registry に登録します。

    Args:
        name: ツール名（英数字とハイフンのみ、例: my-tool）
        description: ツールの説明
        tool_description: 提供する機能の説明

    Returns:
        登録結果
    """
    server_content = json.dumps({
        "name": f"io.demo/{name}",
        "description": description,
        "version": "1.0.0"
    })
    tools_content = json.dumps({
        "tools": [{
            "name": name.replace("-", "_"),
            "description": tool_description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "入力データ"}
                },
                "required": ["input"]
            }
        }]
    })

    body = {
        "name": name,
        "description": description,
        "recordVersion": "1.0",
        "descriptorType": "MCP",
        "descriptors": {
            "mcp": {
                "server": {"schemaVersion": "2025-12-11", "inlineContent": server_content},
                "tools": {"protocolVersion": "2024-11-05", "inlineContent": tools_content}
            }
        }
    }

    resp = signed_request("POST", f"{CONTROL_URL}/registries/{REGISTRY_ID}/records", body)
    if resp.status_code in [200, 201, 202]:
        data = resp.json()
        arn = data.get("recordArn", "")
        record_id = arn.split("/")[-1] if "/" in arn else "unknown"
        return f"✅ 登録完了！\n  Record ID: {record_id}\n  Status: {data.get('status')} → 承認が必要です"
    else:
        return f"❌ 登録失敗: {resp.status_code} - {resp.text[:200]}"


# ========================================
# Strands Agent 作成
# ========================================
agent = Agent(
    model=MODEL_ID,
    system_prompt=(
        "あなたは Agent Registry のアシスタントです。\n"
        "ユーザーの質問に答えるために、以下のツールを使ってください:\n"
        "- list_registry_tools: 全ツール一覧を表示\n"
        "- search_registry: キーワードで検索\n"
        "- get_tool_detail: ツールの詳細・使い方を表示\n"
        "- register_new_tool: 新しいツールを登録\n\n"
        "常に日本語で回答してください。"
    ),
    tools=[list_registry_tools, search_registry, get_tool_detail, register_new_tool],
)

# ========================================
# 対話ループ
# ========================================
print("=" * 60)
print("🚀 Agent Registry × Strands Agent デモ")
print("=" * 60)
print("質問例:")
print("  - 登録されているツールを見せて")
print("  - 天気ツールの使い方を教えて")
print("  - メール送信ツールを新しく登録して")
print("  - weather で検索して")
print("\n'quit' または 'exit' で終了\n")

while True:
    try:
        user_input = input("あなた > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n終了します。")
        break

    if not user_input:
        continue
    if user_input.lower() in ["quit", "exit", "終了", "q"]:
        print("終了します。")
        break

    print("\nAgent > ", end="", flush=True)
    response = agent(user_input)
    print(f"{response}\n")
