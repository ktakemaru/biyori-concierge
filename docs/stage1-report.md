# 段階 1 の報告: 骨組みと、山の取得

作成日: 2026-11-10 / 更新: 2026-11-11(手動実行と診断の結果を受けた追加の修正まで)/ 作業フォルダ `C:\biyori-concierge`(ブランチ main。commit まで。push は利用者)

段階 1 はまだ締めていません。全 76 座の手動実行で 60 座しか取れなかったため(`docs/collect-run4-analysis.md`)、原因を調べている途中です。

## できたこと

- **骨組み**: `LICENSE`(MIT)・`README.md`・`CHANGELOG.md`・`config.yaml`(値ごとに出典か「仮置き」)・`config.local.example.yaml`・`.gitignore`(`config.local.yaml`・生成物)・`requirements.txt`。
  `AGENTS.md`・`CLAUDE.md`・スキル・`concierge/` は段階 2 で作ります。
- **計測フック** `collect/measure/sitecustomize.py`(hub から内容を変えずに写した)。子プロセスへの付け方は `collect/runner.py`:
  シェルなしの引数の配列・`-X utf8` の検査、許可ホストは `collect/hosts.yaml` だけ(`api.open-meteo.com` のみ)、親の `BIYORI_*`・`PYTHONPATH`・`GITHUB_TOKEN` は渡さない、記録先は絶対パス、1 回の起動の中では再試行しない。
- **棚のスキーマ**: `biyori-shelf/1`(manifest)、`biyori-mountains/1`、`biyori-request-log/1`(座標などの余計な項目を入れると検査で落ちる)、`biyori-collect-run/1`(collect → publish の受け渡し。棚には載せない)。
- **山の取得** `python -X utf8 -m collect run`: ①Open-Meteo のメタデータ(前)→ ②ヤマビヨリ `mountain_weather_mvp.py --json-out`(計測フックつき・`TZ=Asia/Tokyo`)→ ③メタデータ(後)→ 出力の形の検査 → `proposals/yamabiyori.json`(biyori-proposal/1)へ変換・スキーマ検査 → `yamabiyori/mountains.json`(MOUNTAINS を ast で読む。ID `m001`〜)→ `logs/requests.json`。
  失敗(終了コード≠0・429・許可外ホスト・時間切れ・形の違い)はそのビヨリだけを ok でなくし、理由を残します。
- **何座取れたか**: ヤマビヨリの出力の `pool_size`・`fetched` を確かめ、`coverage`(何座のうち何座)を run.json・manifest・Summary に出します(例「76座のうち60座(16座取得できず)」)。
  **全座そろわない回は `ok` でなく `incomplete`**(理由 `partial_fetch`)。collect ジョブは赤になります。
- **取り直し**: `fetched` < `pool_size` なら、同じコマンドをもう一度実行します(1 回目を含めて最大 3 回)。ヤマビヨリのコードは変えていません。取れた山はヤマビヨリのキャッシュ(3 時間)で通信なしになる、とコードを読んで確かめました(`docs/collect-run4-analysis.md` 7 章)。
  通信の上限(仮置き 450)・時間の上限(仮置き 4500 秒)は全部の回の合計で、超えたら次の回を始めません。回ごとの通信の回数と `fetched` を `attempts` に出し、2 回目以降の通信が多すぎれば「キャッシュが効いていない疑い」と出します。2 回目以降でも 429 なら即中止です。
- **棚の組み立て** `python -X utf8 -m collect prepare`: ビヨリごとに「成功したら入れ替える」。`ok` と `incomplete` は入れ替え(利用者の決定 A)、失敗なら前回のファイルを残して `kept_previous`(理由・`kept_from` つき)、前回もなければ `failed`。許可したファイル名だけを載せ、`ATTRIBUTION.md` を置きます。
- **メタデータ**: meta.json の読み取りに失敗したモデルだけ、5 秒(仮置き)あけて 1 回だけ読み直します(4xx/5xx は読み直さない)。失敗の種類(例外の名前)を `logs/requests.json` の `by_error` と Summary に出します。
- **`collect.yml`**: collect(読み取りのみ・実通信はここだけ)と publish(書き込みはここだけ・取得のコードは動かさない・`data` にだけ強制 push)の 2 ジョブ。cron は UTC `27 19 * * *`/`47 7 * * *`(日本時間 4:27/16:47)、変数 `BIYORI_COLLECT_SCHEDULE` が `on` のときだけ定期実行(**まだ on にしないでください**)。
  手動実行の入力:
  - `confirm`(`yes-run-live` のときだけ実通信)・`agents`・`publish`(既定 off)。
  - `yama_limit`: 全 76 座は `all`、一部なら 1 以上の整数(初期値 3)。空・`all` 以外の文字・0 以下は、通信の前にエラーで止まります。定期実行は全 76 座。
  - **`yamabiyori_ref`**(今回足した): ヤマビヨリのブランチか commit(初期値 `main`。定期実行は常に `main`)。使った ref と commit を run.json・Summary に出し、main の回は manifest にも入れます。
    **main 以外の ref で取った回は、棚に載せません。** publish にチェックがあっても publish ジョブは動かず(skipped)、Summary に「この回は棚に載せません」と出ます。念のため `collect prepare` も、run.json の ref が main でなければ木を組み立てずに止まります。
    値は、ヤマビヨリを取り出す前に `collect check-inputs` で検査します(空・前後の空白・記号で始まる・`..` を含むなどはエラー)。
- **診断 `diagnose.yml`**(手動実行だけ。棚には書かない。ヤマビヨリは実行しない): api.open-meteo.com の IP ごとに meta.json を取り、失敗した段階(TCP・TLS・応答待ちなど)を分けて数えます。今は「新しい接続」と「接続の使い回し」を 30 回ずつ交互に行って比べる作りです。
- **`tests.yml`**: Ubuntu 24.04 と Windows、Python 3.13。
- 写した部品と commit の記録 `docs/ported-from-hub.md`、対応表 `docs/yamabiyori-mapping.md`、手動実行と診断の記録 `docs/collect-run4-analysis.md`。

途中で気づいて直した点: Actions のマシンは UTC なので、ヤマビヨリ(`date.today()` で対象の日を決める)をそのまま朝 4:27 に動かすと日付が 1 日ずれます。子プロセスに `TZ=Asia/Tokyo` を渡すようにしました(ヤマビヨリのコードは変えていません。テストあり)。

## 手動実行と診断で分かったこと(詳しくは `docs/collect-run4-analysis.md`)

- collect #4(全 76 座): **76 座のうち 60 座**。429 なし、止められたホストなし、所要 約 36 分、通信 285 件。失敗 90 件はすべて 20 秒の読み取りの時間切れ(`ReadTimeout`)で、時間の大部分がその待ちでした。
- 診断 1 回目: IP は 2 個。どちらも 10 回中 9 回成功。「一部のサーバーだけ応答しない」は外れ。
- 診断 2 回目: **新しい接続は 60 回中 11 回失敗(すべて TLS の途中)、使い回しは 60 回中 0 回。** 「新しい接続を張るときに止まる。使い回せば減る」という見立てと合います。
- これを受けて、利用者がヤマビヨリに接続の使い回しを入れる作業を始めました(ブランチ `feature/reuse-connection`)。その版を試すために `yamabiyori_ref` を足しました。

## テストの結果

`python -X utf8 -m unittest discover -s tests` → **140 件すべて成功**(Windows の手元、Python 3.13。約 65 秒)。テスト中はソケットを禁止し、子プロセスも自分でソケットを禁止します。

受け入れ条件との対応:
- 実通信なし: `tests/nonet.py`、`test_repo_rules.NoNetwork`、偽のヤマビヨリ(`tests/fixtures/yamabiyori/mountain_weather_mvp.py`)。
- 記録済みの入力から棚の木ができる: `test_shelf.FirstPublish.test_tree_from_recorded_input`(ヤマビヨリの `tests/fixtures/report/explore.json` の写しから manifest・山の 2 ファイル・提案 24 件)。
- `main` への強制 push がない・書き込み権限は publish だけ: `test_workflows.Collect`。
- そのほか: 429 で即中止、許可外ホストは送信前に止まる、失敗時は前回の棚を残す、`incomplete` の扱い、取り直し、同じ入力なら同じ木、cron が決定どおりでバックテストの収集と重ならない、診断の数え方。
- 今回足したもの(`test_yamabiyori_ref.py`・`test_workflows.py`): ref の検査、ref と commit の記録、main 以外の回は publish が skipped になり `collect prepare` も止まること、取り出しの前に入力を検査すること。
  `test_workflows` の「ヤマビヨリの取り出しは `ref: main`」という検査は、指示どおり ref を入力で変えられるようにしたので「`ref: ${{ env.YAMABIYORI_REF }}` で、定期実行のときは `main`」という検査に直しました。

## 未確認のこと

| 項目 | 今の値 | いつ確かめるか |
|---|---|---|
| U1 GitHub のマシンから全座取れるか | 429 は出ていない。新しい接続の約 2 割が TLS の途中で止まる | 下の手順 3(使い回しの版)と手順 4(main) |
| ヤマビヨリの使い回しで失敗が減るか | 診断(urllib・meta.json)では 0/60。ヤマビヨリ(requests・予報の本体)では未確認 | 手順 3 |
| 使い回しの接続が長い実行の途中で切られるか、張り直しでまた止まるか | 未確認 | 手順 3 |
| 取り直しの 2 回目が、欠けた山の分の通信だけになるか | コードからはそうなるはず。実機では未確認 | 取り直しが起きた実行の Summary(`attempts`) |
| U2 所要時間 | collect #4 で約 36 分(大部分は失敗の待ち)。`timeout-minutes: 90`、子プロセス 3600 秒・全回の合計 4500 秒(仮置き) | 手順 3・4 の実測で直す |
| 山の通信の上限 | `max_requests: 450`(全回の合計。仮置き。collect #4 は 1 回で 281 件) | 失敗が減った版の実測の 1.3 倍程度に直す |
| Open-Meteo 以外に要るホスト | `api.open-meteo.com` だけ。collect #4 で止められたホストはなし | 段階 3(星) |
| call の換算(U7) | 変数 10 個・14 日で 1 call とする推定(`config.yaml`) | 段階 5 |
| バックテストの収集と離す間隔 | 30 分(仮置き)。今の時刻は最も近い収集から 67 分以上離れている | 段階 5 |
| 山の並びとイキモノビヨリの `site_ref` | MOUNTAINS の並び順で ID を付けている | 段階 4(main の並びが変わったら突き合わせが崩れる) |
| 初回の publish で `data` ブランチが無いときの取り出し | `continue-on-error` で空として進む作り(hub と同じ) | main・全座・publish ありの最初の実行 |

## 利用者がやること

### 1. push する(PowerShell)

1. PowerShell で `cd C:\biyori-concierge`
2. `git log --oneline -1` で、いちばん上が今回の commit(「yamabiyori_ref」を含む題)であることを確かめる。
3. `git push`
4. 成功の見分け方: エラーなく終わる。

### 2. テストが通ることを見る(ブラウザ)

1. `https://github.com/ktakemaru/biyori-concierge` の上の **Actions** タブを開く。
2. 左の一覧の **tests** を押し、いちばん上の実行を開く。
3. 成功の見分け方: `unittest (ubuntu-24.04)` と `unittest (windows-latest)` の両方に緑のチェック。

### 3. 使い回しの版で全 76 座を取る(棚には載りません)

前提: ヤマビヨリのブランチ `feature/reuse-connection` が GitHub(`ktakemaru/yamabiyori`)に push されていること。commit を指定する場合は 40 桁で入れてください。

1. **Actions** タブ → 左の一覧の **collect** を押す。
2. 右の **Run workflow** ボタンを押す(「Use workflow from」は `main` のまま)。
3. 入力: `confirm` に `yes-run-live`、`agents` は `yamabiyori`、`yama_limit` に `all`、`yamabiyori_ref` に `feature/reuse-connection`、`publish` は**チェックしない**(入れても載りません)。
4. 緑の **Run workflow** を押す。
5. 成功の見分け方: `collect` ジョブに緑のチェック(全座そろったとき。そろわなければ赤で、その場合も記録は残ります)、`publish` は灰色(skipped)。
   Summary に「ヤマビヨリの取り出し: ref `feature/reuse-connection`、commit `…`」と「この回は棚(data ブランチ)に載せません」が出る。
6. 伝えてほしいこと(Summary から): 山の数(何座のうち何座)、回ごとの表(通信・山・所要)、取り直しをやめた理由(あれば)、通信の合計・ステータス別・失敗の種類、所要(秒)。
   できれば実行のページ下の **Artifacts** の `collect-result`(zip)もダウンロードしてください(collect #4 と同じ調べ方で比べます)。
7. 入力の検査で止まったとき: 「Check inputs (no network)」の行に理由が出ます(このときは通信していません)。「Get yamabiyori」の行で止まったときは、ブランチ名が GitHub にあるかを確かめてください。

### 4. (手順 3 で失敗が大きく減ったら)ヤマビヨリの PR をマージしてから、main で棚に載せる

1. ヤマビヨリ側の PR をマージする(`C:\mountain-weather-main` の作業の側で)。
2. 手順 3 と同じ画面で、`yamabiyori_ref` は `main`(初期値のまま)、`yama_limit` に `all`、`publish` に**チェックを入れる**。
3. 成功の見分け方: `collect` と `publish` の両方に緑のチェック。リポジトリの **Code** タブでブランチ切り替え(`main` と書かれたボタン)から `data` を選ぶと、`manifest.json`・`ATTRIBUTION.md`・`yamabiyori/`・`proposals/`・`logs/` がある。
   全座そろわなかった回は `collect` が赤ですが、`publish` は動き、manifest の yamabiyori は `incomplete` になります。
4. `publish` が `403` などの権限エラーで落ちたとき: **Settings** → **Actions** → **General** → 下の **Workflow permissions** を見て、伝えてください(勝手には変えないでください)。

**変数 `BIYORI_COLLECT_SCHEDULE` は作らない・`on` にしないでください**(段階 5 まで)。

## 利用者に決めてほしいこと

1. 段階 1 を締める条件。案: 「main の版で、全 76 座・publish ありの実行が 1 回 `ok`(または取り直しで全座そろう)」。決めなければ、この案で進めます。
2. バックテストの収集と取得の時刻を離す間隔の目安(今は仮置き 30 分。今の時刻は 67 分以上離れているので、変えなくても動作には影響しません)。決めなければ、そのまま仮置きで進めます。
