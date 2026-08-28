# Information Digestion — Concept & Roadmap

## 1. Concept

### One-liner

**通り過ぎる情報を、あとで使える知識へ変える。**

このプロダクトの目的は「情報をたくさん保存すること」ではない。

ユーザーが日常で触れた情報を、

```text
Capture
  ↓
Digest
  ↓
Context
  ↓
Insight
  ↓
Refresh
```

という流れで少しずつ価値ある状態へ変換する。

---

## 2. Product Principle

### Capture friction should be near zero

情報を保存するために、

- アプリを開く
- フォルダを選ぶ
- タグを書く
- タイトルを書く

といった作業を要求しない。

日常の操作の延長で情報を送れることを優先する。

MVPでは、

> **コピーした内容をホットキーで送る**

という単純な操作から始める。

### Store first, enrich later

すべての情報を最初から深く分析しない。

まず安全に保存し、必要に応じて段階的に価値を追加する。

```text
Raw information
      ↓
Stored knowledge
      ↓
Contextual knowledge
      ↓
Useful insight
```

これにより、処理コスト、AIによる過剰解釈、UIの複雑化、初期実装の肥大化を抑える。

### AI should create value, not decoration

AIの役割はタグを大量生成したり、長文要約を作ったり、何でも分類することではない。

重要なのは、

> **「この情報は自分にとって何に使えるか」を見つけること。**

### Time is part of knowledge

情報の価値は固定ではない。

昨日重要だった情報が今日も重要とは限らない。逆に、以前は意味がなかった情報が、新しいプロジェクトによって重要になることもある。

最終的には、

```text
Knowledge = Content + Context + Time
```

として扱う。

---

# 3. System Concept

## Capture Layer

ユーザーとシステムの接点。

```text
Desktop
Mobile
Browser
CLI
Other integrations
      ↓
Capture
```

初期はDesktopだけ。

役割は単純。

> **ユーザーが選んだ情報をサーバーへ届ける。**

## Digest Layer

受け取った情報を扱いやすい単位へ変換する。

```text
Receive
  ↓
Deduplicate
  ↓
Normalize
  ↓
Summarize
  ↓
Save
```

ここでは深い判断をしない。

目的は、

> **Raw dataを「あとで理解できる状態」にすること。**

## Context Layer

情報に「自分との関係」を追加する。

例:

```text
この情報についてどう思ったか
なぜ保存したか
どのProjectに関係するか
何を試したいか
どのTopicに属するか
```

AIによる推測だけでなく、ユーザー自身の短いコメントを重要視する。

## Insight Layer

保存した情報を材料に、新しい価値を生み出す。

例えば、

```text
複数情報の比較
共通点
矛盾
設計への応用
新しいアイデア
次のAction
未検証の仮説
深掘りすべきポイント
```

ここから「保存アプリ」ではなく、**思考支援システム**になる。

## Refresh Layer

時間経過によって知識を再評価する。

```text
Is it still valid?
Is it still important?
Has something changed?
Is it relevant to a new project?
```

情報を保存した瞬間だけでなく、

> **後から価値が変化する**

ことを扱う。

---

# 4. Roadmap

## Phase 1 — Capture & Digest

### Goal

**情報を一瞬で送り、後から理解できる状態で残せる。**

### Client

```text
Copy
+
Hotkey
     ↓
Send
```

アプリ側は可能な限り薄くする。役割はCaptureのみ。

### Server

```text
Receive
↓
Dedup
↓
Summarize
↓
Save
```

このフェーズでは、高度なタグ、Project管理、深掘り分析、Knowledge Graph、自動再評価は行わない。

### Validation

確認するのは、

> **このCapture方法を日常的に使いたくなるか。**

そして、

> **保存した情報を後から再利用できるか。**

---

## Phase 2 — Context

### Goal

**情報に「なぜ保存したか」を加える。**

保存された情報に対して、

```text
Thought
Note
Tag
Project
Intent
```

などのContextを追加できるようにする。

重要なのは、入力負荷を増やしすぎないこと。

例:

```text
URLを送信
↓
後から一言

「この設計だけ参考にしたい」
```

### Concept

```text
Content
+
User Context
=
Personal Knowledge
```

---

## Phase 3 — Insight

### Goal

**蓄積された情報から新しい価値を作る。**

AIが単独の情報を要約するだけでなく、複数のItemを横断して考える。

例えば、

```text
この3つのOSSの共通設計は？

今のProjectに使える部分は？

以前保存した情報と矛盾していないか？

次に調べるべきものは？

ここから新しいアイデアは作れるか？
```

このフェーズで初めて、**AI Research / Analysis / Ideation** が本格的に入る。

---

## Phase 4 — Refresh

### Goal

**知識を時間とともに更新する。**

保存された情報を定期的・条件付きで再評価する。

例えば、

```text
古くなった情報
更新された技術
リンク切れ
新しいバージョン
新しい競合
重要度が変わった情報
```

を検出する。

さらに、

```text
以前は無関係
↓
新しいProject開始
↓
実はRelevant
```

という再発見も可能にする。

---

## Phase 5 — Proactive Knowledge

### Goal

**探しに行かなくても、必要な知識が出てくる。**

ユーザーの現在の活動やProjectに応じて、

```text
You may want to revisit this.

This old item is now relevant.

These three items suggest the same direction.

This assumption may now be outdated.
```

のように情報を再提示する。

ここで初めて、**第二の脳**に近づく。

---

# 5. Roadmap Overview

```text
Phase 1
Capture
+
Digest
     ↓

Phase 2
Context
     ↓

Phase 3
Insight
     ↓

Phase 4
Refresh
     ↓

Phase 5
Proactive Knowledge
```

それぞれのフェーズは前フェーズの価値が確認できてから進める。

---

# 6. What We Are Not Building Yet

初期段階では以下を目的にしない。

```text
Knowledge Graph
Agent Platform
Workflow Engine
Team Collaboration
Community
Full Mobile App
Complex Taxonomy
Automatic Everything
```

これらは必要性が確認されてから追加する。

---

# 7. Product Evolution

このプロダクトは段階的に性質が変わる。

### Phase 1

```text
Smart Inbox
```

### Phase 2

```text
Personal Knowledge Base
```

### Phase 3

```text
Thinking Assistant
```

### Phase 4

```text
Living Knowledge Base
```

### Phase 5

```text
Proactive Second Brain
```

---

# 8. Core Architecture Principle

入力経路と知識処理を分離する。

```text
          Capture Clients

 Desktop    Mobile    Browser    CLI
    │          │         │        │
    └──────────┴────┬────┴────────┘
                    ↓
                Ingestion
                    ↓
              Knowledge Core
                    ↓
      ┌─────────────┼─────────────┐
    Digest        Context       Insight
                                   ↓
                                Refresh
```

これにより将来、Voice、Mobile Share、Browser extension、AI chat、API、integrationsを追加しても、Knowledge Coreを作り直さなくてよい。

---

# 9. Most Important Rule

機能を増やす条件は、

> **前のフェーズで実際にユーザー価値が確認できたこと。**

例えば、

Captureが使われないのにInsightを作らない。

保存した情報が再利用されないのにKnowledge Graphを作らない。

AI分析が役立たないのにAgentを作らない。

常に、

```text
Need
↓
Value
↓
Validation
↓
Next feature
```

の順で進める。

---

# 10. North Star

最終的に目指す体験は非常に単純。

ユーザーが、

> **「これ、前にどこかで見た」**

と思ったとき、このシステムがその情報を見つける。

さらに、

> **「これは今の自分に使える」**

まで教えてくれる。

---

## Vision

**情報を集めるためのアプリではなく、  
情報を自分の知識へ変えるためのインフラを作る。**

---

# 11. Design Inspirations Absorbed into the Concept

このプロダクトは、特定の既存プロジェクトやコードベースに依存する前提を置かない。

参考にするのは、実装そのものではなく、以下の**一般化された設計思想**である。

## Thin Capture Client

入力側はできるだけ薄く保つ。

```text
Capture Client
↓
Ingestion API
↓
Knowledge Core
```

Capture Clientの責務は、

- ユーザーが選んだ内容を取得する
- 最低限のローカル検査を行う
- サーバーへ送る
- 成否を返す

まで。

Knowledge処理やAI判断をClientへ持ち込みすぎない。

これにより、将来、

```text
Desktop
Mobile
Browser
CLI
Voice
Share
```

を追加しても、入力方式ごとに知識処理を再実装しなくてよい。

---

## Knowledge Lifecycle

保存された情報を、単なる「ノート」ではなく**状態を持つ知識**として扱う。

概念的には、

```text
Raw
↓
Captured
↓
Digested
↓
Contextualized
↓
Validated / Reused
↓
Stale / Refreshed
```

と変化していく。

重要なのは、一度保存したら完成ではないこと。

知識は、

- 補足される
- 再解釈される
- 再利用される
- 古くなる
- 更新される

ものとして設計する。

---

## Provenance First

AIが生成した要約やInsightと、元情報を混同しない。

常に、

```text
Source
User Context
AI Digest
AI Insight
```

を分離して保持する。

これにより、

- 元情報へ戻れる
- AIの誤解を確認できる
- 後から再生成できる
- モデル変更に耐えられる
- 信頼性を評価できる

ようにする。

**AI生成物をSource of Truthにしない。**

---

## Progressive Enrichment

情報は段階的に価値化する。

```text
Capture
↓
Metadata
↓
Digest
↓
Context
↓
Insight
↓
Refresh
```

最初から全処理を行わない。

必要なときだけ処理を深くすることで、

- コスト
- latency
- ノイズ
- AI誤判断
- 過剰設計

を抑える。

---

## Research Before Canonical Knowledge

未検証情報と、自分の中で信頼できる知識を区別する。

概念的には、

```text
External Information
↓
Captured / Research
↓
Compared / Validated
↓
Trusted Knowledge
```

と扱う。

すべての保存情報を同じ重要度で扱わない。

将来的には、

- source reliability
- confirmation count
- contradiction
- user endorsement
- reuse history

などを判断材料にできる。

---

## Freshness as a First-Class Property

知識には「いつ得たか」だけでなく、

> **今も有効か**

という属性がある。

将来的には、

```text
fresh
aging
stale
superseded
unknown
```

のような状態を持たせられる。

重要なのは、自動更新そのものではなく、

> **古くなった可能性を検出できること。**

---

## Reuse Over Storage

Storage量を成功指標にしない。

価値は、

```text
Saved
↓
Found again
↓
Used
↓
Changed a decision / project / action
```

で生まれる。

そのため、Knowledge Coreは最終的に、

- 検索
- 再提示
- Projectとの接続
- 関連情報の比較
- 古い情報の再評価

へ向かう。

---

# 12. Architecture Guardrails

将来機能が増えても、以下を崩さない。

## Capture is replaceable

入力手段は交換可能であること。

## Source is immutable

元情報は可能な限り保持し、AI生成結果で上書きしない。

## AI output is reproducible

要約や分析は再生成可能な派生データとして扱う。

## Context belongs to the user

ユーザー自身の感想・意図・判断はAI推測より優先する。

## Deep processing is optional

すべてのItemを深掘りしない。

## Freshness is explicit

古さを暗黙に扱わず、将来評価可能な設計にする。

## Reuse closes the loop

Capture → Save で終わらせず、Reuseまでを1サイクルと考える。

---

# 13. Refined Product Model

最終的な概念モデルは以下。

```text
                CAPTURE
                   │
                   ▼
               INGESTION
                   │
                   ▼
                SOURCE
                   │
                   ▼
                DIGEST
                   │
          ┌────────┴────────┐
          ▼                 ▼
       CONTEXT           RESEARCH
          │                 │
          └────────┬────────┘
                   ▼
                 INSIGHT
                   │
                   ▼
                  REUSE
                   │
                   ▼
                REFRESH
                   │
                   └─────────────→ 再評価
```

この循環を小さく始め、必要性が確認できた部分だけ拡張する。

---

# 14. Refined Vision

**情報を保存する場所ではなく、  
情報が知識になり、使われ、更新される循環を作る。**

MVPではその最初の一周、

```text
Capture
→ Digest
→ Save
→ Find
→ Reuse
```

だけを成立させる。
