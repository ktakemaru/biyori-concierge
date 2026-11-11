# 段階 1 の報告: 骨組みと、山の取得(**完了**)

作成日: 2026-11-10 / 完了: 2026-11-11 / 作業フォルダ `C:\biyori-concierge`(ブランチ main。commit まで。push は利用者)

**段階 1 は完了しました。** 締める条件「main の版で、全 76 座・publish ありの実行が 1 回 ok」(利用者の決定)を、実行 B が満たしました:
ヤマビヨリ main `29b04e7`(1.9.1)、76 座のうち 76 座、ok、所要 137.7 秒、失敗 0 件、data ブランチに棚が公開され、手元でスキーマの検査に通りました。
経過と比較は `docs/collect-run4-analysis.md`(collect #4 → 診断 2 回 → 実行 A・B)。

## できたこと

- **骨組み**: `LICENSE`(MIT)・`README.md`・`CHANGELOG.md`・`config.yaml`(値ごとに出典か「仮置き」)・`config.local.example.yaml`・`.gitignore`(`config.local.yaml`・生成物)・`requirements.txt`。
  `AGENTS.md`・`CLAUDE.md`・スキル・`concierge/` は段階 2 で作ります。
- **計測フック** `collect/measure/sitecustomize.py`(hub から内容を変えずに写した)。子プロセスへの付け方は `collect/runner.py`:
  シェルなしの引数の配列・`-X utf8` の検査、許可ホストは `collect/hosts.yaml` だけ(`api.open-meteo.com` のみ)、親の `BIYORI_*`・`PYTHONPATH`・`GITHUB_TOKEN` は渡さない、記録先は絶対パス、1 回の起動の中では再試行しない。
- **棚のスキーマ**: `biyori-shelf/1`(manifest)、`biyori-mountains/1`、`biyori-request-log/1`(座標などの余計な項目を入れると検査で落ちる)、`biyori-collect-run/1`(collect → publish の受け渡し。棚には載せない)。
- **山の取得** `python -X utf8 -m collect run`: ①Open-Meteo のメタデータ(前)→ ②ヤマビヨリ `mountain_weather_mvp.py --json-out`(計測フックつき・`TZ=Asia/Tokyo`)→ ③メタデータ(後)→ 出力の形の検査 → `proposals/yamabiyori.json`(biyori-proposal/1)へ変換・スキーマ検査 → `yamabiyori/mountains.json`(MOUNTAINS を ast で読む。ID `m001`〜)→ `logs/requests.json`。
  失敗(終了コード≠0・429・許可外ホスト・時間切れ・形の違い)はそのビヨリだけを ok でなくし、理由を残します。
- **何座取れたか**: ヤマビヨリの出力の `pool_size`・`fetched` を確かめ、`coverage`(何座のうち何座)を run.json・manifest・Summary に出します。
  全座そろわない回は `ok` でなく `incomplete`(理由 `partial_fetch`)で、collect ジョブは赤。棚には載せます(利用者の決定 A)。
- **取り直し**: `fetched` < `pool_size` なら、同じコマンドをもう一度実行します(1 回目を含めて最大 3 回)。取れた山はヤマビヨリのキャッシュ(3 時間)で通信なしになる作り(コードで確認)。
  通信・時間の上限は全部の回の合計。回ごとの通信の回数と `fetched` を `attempts` に出し、2 回目以降の通信が多すぎれば「キャッシュが効いていない疑い」と出します。2 回目以降でも 429 なら即中止。
- **棚の組み立て** `python -X utf8 -m collect prepare`: ビヨリごとに「成功したら入れ替える」。`ok` と `incomplete` は入れ替え、失敗なら前回のファイルを残して `kept_previous`(理由・`kept_from` つき)、前回もなければ `failed`。許可したファイル名だけを載せ、`ATTRIBUTION.md` を置きます。
- **メタデータ**: meta.json の読み取りに失敗したモデルだけ、5 秒(仮置き)あけて 1 回だけ読み直します(4xx/5xx は読み直さない)。失敗の種類(例外の名前)を `logs/requests.json` の `by_error` と Summary に出します。
- **`collect.yml`**: collect(読み取りのみ・実通信はここだけ)と publish(書き込みはここだけ・取得のコードは動かさない・`data` にだけ強制 push)の 2 ジョブ。cron は UTC `27 19 * * *`/`47 7 * * *`(日本時間 4:27/16:47)、変数 `BIYORI_COLLECT_SCHEDULE` が `on` のときだけ定期実行(**まだ on にしないでください**。段階 5)。
  手動実行の入力: `confirm`(`yes-run-live` のときだけ実通信)・`agents`・`yama_limit`(全 76 座は `all`、一部なら 1 以上の整数、初期値 3)・`yamabiyori_ref`(初期値 `main`。定期実行は常に `main`。**main 以外で取った回は棚に載せない**)・`publish`(既定 off)。
  入力は、ヤマビヨリを取り出す前に `collect check-inputs` で検査します(通信なし)。
- **診断 `diagnose.yml`**(手動実行だけ。棚には書かない): api.open-meteo.com の IP ごとに meta.json を取り、失敗した段階を分けて数え、「新しい接続」と「接続の使い回し」を比べます。今は役目を終えていますが、同じ症状が戻ったときのために残してあります。
- **`tests.yml`**: Ubuntu 24.04 と Windows、Python 3.13。
- 写した部品と commit の記録 `docs/ported-from-hub.md`、対応表 `docs/yamabiyori-mapping.md`、手動実行と診断の記録 `docs/collect-run4-analysis.md`。

途中で気づいて直した点:
- Actions のマシンは UTC なので、ヤマビヨリ(`date.today()` で対象の日を決める)をそのまま朝 4:27 に動かすと日付が 1 日ずれます。子プロセスに `TZ=Asia/Tokyo` を渡すようにしました(ヤマビヨリのコードは変えていません)。
- 全 76 座の 1 回目(collect #4)は 60 座しか取れず、所要 約 36 分でした。診断で「新しい接続の開始(TLS の途中)が約 2 割止まる・使い回しなら 0」と分かり、利用者がヤマビヨリに接続の使い回しを入れました(1.9.1)。そのあとは 76 座・失敗 0・約 137 秒です。**なぜ GitHub のマシンからだと接続の開始が止まるのか(根本の原因)は未確認のままです。**

## 手動実行の結果(段階 1 の受け入れの記録)

| 実行 | ヤマビヨリ | 山 | 所要(ヤマビヨリ) | 通信(合計) | 失敗 | 429 | 止められたホスト | 棚 |
|---|---|---|---|---|---|---|---|---|
| collect #4 | main `b018355`(1.9.0) | 76 座のうち 60 座 | 2152.7 秒 | 285 件 | 91 件 | なし | なし | — |
| 実行 A | `feature/reuse-connection` `4a695e7` | 76 座のうち 76 座 | 137.1 秒 | 232 件 | 0 件 | なし | なし | 載せない(ref が main でない) |
| 実行 B | main `29b04e7`(1.9.1) | 76 座のうち 76 座 | 137.7 秒 | 232 件 | 0 件 | なし | なし | **公開**(data `9844e0c`) |

実行 B の棚の検査(手元。通信は `git fetch origin data` だけ): manifest・mountains・提案(1,140 件 = 76 座 × 15 日)・通信の記録・explore の形が、すべてスキーマに通りました。data ブランチは親なしの 1 コミットで、ファイルは許可した 6 個だけ。manifest と通信の記録に出発地・座標は入っていません。

## テストの結果

`python -X utf8 -m unittest discover -s tests` → **140 件すべて成功**(Windows の手元、Python 3.13)。テスト中はソケットを禁止し、子プロセスも自分でソケットを禁止します。

受け入れ条件との対応:
- 実通信なし: `tests/nonet.py`、`test_repo_rules.NoNetwork`、偽のヤマビヨリ(`tests/fixtures/yamabiyori/mountain_weather_mvp.py`)。
- 記録済みの入力から棚の木ができる: `test_shelf.FirstPublish.test_tree_from_recorded_input`。加えて、本物の棚(実行 B)が手元のスキーマの検査に通った(上)。
- `main` への強制 push がない・書き込み権限は publish だけ: `test_workflows.Collect`。
- そのほか: 429 で即中止、許可外ホストは送信前に止まる、失敗時は前回の棚を残す、`incomplete` の扱い、取り直し、`yamabiyori_ref`(main 以外は載せない)、同じ入力なら同じ木、cron が決定どおりでバックテストの収集と重ならない、診断の数え方。

## 未確認のこと

| 項目 | 今わかっていること | いつ確かめるか |
|---|---|---|
| 接続の開始が止まる根本の原因 | 未確認。使い回しで避けているだけ | 原因を突き止める予定はない。症状が戻ったら `diagnose.yml` で調べ直す |
| 定期実行の時刻(4:27・16:47)や別の日でも失敗が出ないか | 成功は同じ日の夜(22 時台)の 2 回だけ | 段階 3 の手動実行、段階 5 の定期実行 |
| 取り直しの 2 回目が、欠けた山の分の通信だけになるか | 実行 A・B は 1 回目で全座そろったので、取り直しは起きていない | 取り直しが起きた実行の Summary(`attempts`) |
| 上限の値 | 下の「決めてほしいこと」に案 | 利用者の決定のあと |
| Open-Meteo 以外に要るホスト | 山は `api.open-meteo.com` だけで足りた | 段階 3(星) |
| call の換算(U7) | 推定 call は山 1 回で 1,222(推定)。朝夕 2 回で約 2,444/日(推定) | 段階 5 |
| バックテストの収集と離す間隔 | 30 分(仮置き)。今の時刻は 67 分以上離れている | 段階 5 |
| 山の並びとイキモノビヨリの `site_ref` | MOUNTAINS の並び順で ID を付けている | 段階 4 |

## 利用者がやること

### 1. push する(PowerShell)

1. PowerShell で `cd C:\biyori-concierge`
2. `git log --oneline -1` で、いちばん上が今回の commit(「段階1を締める」を含む題)であることを確かめる。
3. `git push`
4. 成功の見分け方: エラーなく終わる。Actions の **tests** に、`unittest (ubuntu-24.04)` と `unittest (windows-latest)` の緑のチェックが出る。

**変数 `BIYORI_COLLECT_SCHEDULE` は作らない・`on` にしないでください**(段階 5 まで)。

## 利用者に決めてほしいこと

### 1. 上限の値(まだ変えていません)

実測: 全 76 座で、良い日(実行 A・B)は 228 件・約 137 秒、悪い日(collect #4。使い回しの前)は 281 件・2153 秒。
ヤマビヨリの 1 回の実行が理屈の上で最も多く通信するのは 76 座 × 3 回の通信 × 3 回の試行 = 684 件。

| 値 | 今 | 案 | 理由 |
|---|---|---|---|
| 通信の上限 `max_requests`(全部の回の合計) | 450(仮置き) | **300** | 指示書 5.2「実測の 1.3 倍程度」: 228 × 1.3 ≈ 296。collect #4 程度の悪い日(1 回目 281 件)でも 1 回目は収まる。ただし、その日は取り直しにほとんど回せず(残り 19 件)、`incomplete` で終わりやすい |
| 時間の上限 `total_timeout_s`(全部の回の合計) | 4500 秒(仮置き) | **2700 秒**(45 分) | 悪い日の実測 2153 秒 × 約 1.25。良い日の約 20 倍。これより短くすると、collect #4 程度の日は 1 回目の途中で打ち切られ、出力が無くなって `kept_previous`(山が前回のまま)になる |
| 1 回の子プロセスの時間 `timeout_s`(参考。挙げられた 3 つの外) | 3600 秒(仮置き) | **2700 秒** | 合計の上限より長くても意味がないので、合計とそろえる |
| collect ジョブの `timeout-minutes` | 90 | **90 のまま** | 段階 3 で星(PC では 1 モード 約 21 分 × 2 モード)が同じジョブに入るが、まだ実測がない。指示書でも段階 3 の実測で直すことになっている。朝の回は 4:27 + 90 分 = 5:57 で、6 時前に終わる |

別の案: 通信の上限を 450 のまま残す。1 日 10,000 call の枠から見ると 300 と 450 の差は小さく、悪い日にも取り直しの余地が残ります。ただし、指示書の「1.3 倍」からは外れます。

### 2. バックテストの収集と取得の時刻を離す間隔

今は 30 分(仮置き)。今の時刻は 67 分以上離れているので、変えなくても動作には影響しません。決めなければ、仮置きのまま段階 5 で見直します。
