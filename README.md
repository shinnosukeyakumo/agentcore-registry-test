# AWS Agent Registry 検証

Amazon Bedrock AgentCore の **Agent Registry** を Python から操作する検証コードです。
MCPサーバーの登録・承認・検索から、Strands Agents との連携まで一通り試せます。

## ファイル構成

| ファイル | 内容 |
|---------|------|
| `registry_test.py` | Registry 作成 → Record 作成 → 承認フローの基本検証 |
| `registry_test2.py` | Auto-approval Registry の検証・APIパス探索 |
| `registry_test3.py` | 手動承認 + Strands Agent から Registry を利用 |
| `demo.py` | Registry × Strands Agent の対話デモ（ターミナルで対話可能） |
| `email_agent.py` | Registry から email-sender を発見して Amazon SES でメール送信 |

## 必要条件

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)
- AWS アカウント・IAM 権限（bedrock-agentcore, ses）

## セットアップ

```bash
# リポジトリをクローン
git clone <repo-url>
cd agentcore-registry-test

# 依存パッケージのインストール
uv sync

# AWS 認証
aws login
```

## 設定

各スクリプトの先頭にある定数を環境に合わせて書き換えてください。

```python
REGION = "YOUR_REGION"        # 例: us-east-1
REGISTRY_ID = "YOUR_REGISTRY_ID"  # registry_test.py 実行後に取得
```

`email_agent.py` のみ追加設定が必要です。

```python
SES_REGION = "YOUR_SES_REGION"          # SES を使用するリージョン
FROM_EMAIL = "your-verified@example.com" # SES で検証済みのメールアドレス
```

## 実行手順

### 1. 基本フロー（Registry 作成〜承認）

```bash
# Step 1: Registry 作成 → Record 作成 → 承認申請まで
uv run python registry_test.py

# Step 2: Auto-approval の検証
uv run python registry_test2.py

# Step 3: 手動承認 + Strands Agent 連携
uv run python registry_test3.py
```

> `registry_test2.py` と `registry_test3.py` は `REGISTRY_ID` / `RECORD_ID` を
> `registry_test.py` の実行結果から取得して設定してください。

### 2. 対話デモ

```bash
uv run python demo.py
```

起動後、以下のような質問を入力できます。

```
あなた > 登録されているツールを見せて
あなた > 天気ツールの使い方を教えて
あなた > weather で検索して
あなた > quit
```

### 3. メール送信デモ

Amazon SES でメールアドレスを検証済みであれば、実際にメールを送れます。

```bash
uv run python email_agent.py
```

```
あなた > test@example.com にテストメールを送って
```
## 参考リンク

- [Amazon Bedrock Agent Registry 公式ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry.html)
- [Registry Concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-concepts.html)
- [Strands Agents](https://strandsagents.com/)
