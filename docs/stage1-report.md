# 段階 1 の報告: 骨組みと、山の取得

作成日: 2026-11-11 / 作業フォルダ `C:\biyori-concierge`(ブランチ main、commit のみ。push はしていません)

## できたこと

- **骨組み**: `LICENSE`(MIT)・`README.md`・`CHANGELOG.md`・`config.yaml`(値ごとに出典か「仮置き」)・`config.local.example.yaml`・`.gitignore`(`config.local.yaml`・生成物)・`requirements.txt`。
  `AGENTS.md`・`CLAUDE.md`・スキル・`concierge/` は段階 2 で作ります。
- **計測フック** `collect/measure/sitecustomize.py`(hub から内容を変えずに写した)。子プロセスへの付け方は `collect/runner.py`:
  シェルなしの引数の配列・`-X utf8` の検査、許可ホストは `collect/hosts.yaml` だけ(最初は `api.open-meteo.com` のみ)、親の `BIYORI_*`・`PYTHONPATH`・`GITHUB_TOKEN` は渡さない、記録先は絶対パス、再試行しない。
- **棚のスキーマ**: `biyori-shelf/1`(manifest)、`biyori-mountains/1`、`biyori-request-log/1`(座標などの余計な項目を入れると検査で落ちる)、`biyori-collect-run/1`(collect → publish の受け渡し。棚には載せない)。
- **山の取得** `python -X utf8 -m collect run`: ①Open-Meteo のメタデータ(前)→ ②ヤマビヨリ `mountain_weather_mvp.py --json-out`(計測フックつき・`TZ=Asia/Tokyo`)→ ③メタデータ(後)→ 出力の形の検査 → `proposals/yamabiyori.json`(biyori-proposal/1)へ変換・スキーマ検査 → `yamabiyori/mountains.json`(MOUNTAINS を ast で読む。ID `m001`〜)→ `logs/requests.json`。
  失敗(終了コード≠0・429・許可外ホスト・時間切れ・形の違い)はそのビヨリだけを ok でなくし、理由を残します。
- **棚の組み立て** `python -X utf8 -m collect prepare`: ビヨリごとに「成功したら入れ替える」。失敗なら前回のファイルを残して `kept_previous`(理由・`kept_from` つき)、前回もなければ `failed`。許可したファイル名だけを載せ、`ATTRIBUTION.md` を置きます。
- **`collect.yml`**: collect(読み取りのみ・実通信はここだけ)と publish(書き込みはここだけ・取得のコードは動かさない・`data` にだけ強制 push)の 2 ジョブ。cron は UTC `27 19 * * *`/`47 7 * * *`(日本時間 4:27/16:47)、変数 `BIYORI_COLLECT_SCHEDULE` が `on` のときだけ定期実行(**まだ on にしないでください**)。手動実行の入力は `confirm`・`agents`・`yama_limit`(既定 3)・`publish`(既定 off)。
- **`tests.yml`**: Ubuntu 24.04 と Windows、Python 3.13。
- 写した部品と commit の記録 `docs/ported-from-hub.md`、対応表 `docs/yamabiyori-mapping.md`。

途中で気づいて直した点: Actions のマシンは UTC なので、ヤマビヨリ(`date.today()` で対象の日を決める)をそのまま朝 4:27 に動かすと日付が 1 日ずれます。子プロセスに `TZ=Asia/Tokyo` を渡すようにしました(ヤマビヨリのコードは変えていません。テストあり)。

## テストの結果

`python -X utf8 -m unittest discover -s tests` → **77 件すべて成功**(Windows の手元、Python 3.13.15。約 25 秒)。テスト中はソケットを禁止し、子プロセスも自分でソケットを禁止します。

受け入れ条件との対応:
- 実通信なし: `tests/nonet.py`、`test_repo_rules.NoNetwork`、偽のヤマビヨリ(`tests/fixtures/yamabiyori/mountain_weather_mvp.py`)。
- 記録済みの入力から棚の木ができる: `test_shelf.FirstPublish.test_tree_from_recorded_input`(ヤマビヨリの `tests/fixtures/report/explore.json` の写しから manifest・山の 2 ファイル・提案 24 件)。
- `main` への強制 push がない・書き込み権限は publish だけ: `test_workflows.Collect`。
- そのほか: 429 で即中止・再試行なし、許可外ホストは送信前に止まりホスト名が記録に残る、失敗時は前回の棚を残す、同じ入力なら同じ木、cron が決定どおりでバックテストの収集と重ならない。

GitHub 上の `tests.yml` はまだ動かしていません(push 後に動きます)。

## 未確認のこと

| 項目 | 今の値 | いつ確かめるか |
|---|---|---|
| U1 GitHub のマシンから 429 が出ないか | — | 下の手動実行 ①② |
| U2 所要時間(PC では山 約 6 分) | `timeout-minutes: 90`、子プロセス 3600 秒(仮置き) | ①② |
| 山の通信の上限 | `max_requests: 300`(仮置き) | ② の実測の 1.3 倍程度に直す(段階 2 の最初) |
| Open-Meteo 以外に要るホスト | `api.open-meteo.com` だけ | ①② で「止められたホスト」を見る。地形は同梱の `terrain_profiles.json` を使うので国土地理院への通信は無い見込み(未確認) |
| call の換算(U7) | 変数 10 個・14 日で 1 call とする推定(`config.yaml`) | 段階 5 |
| バックテストの収集と離す間隔 | 30 分(仮置き)。今の時刻は最も近い収集から 67 分以上離れている | 段階 5 |
| メタデータの取り方 | 手本(backtest)は「最終更新から 10 分待つ」が、ここでは待たずに前後を記録するだけ(`same_before_after` で確定かどうかが分かる) | ①② の結果を見て必要なら足す |
| 山の並びとイキモノビヨリの `site_ref` | ヤマビヨリ `de66f10` と `b018355` で `mountain_weather_core.py` は同じ(差分なし) | 段階 4(main の並びが変わったら突き合わせが崩れる) |
| 初回の publish で `data` ブランチが無いときの取り出し | `continue-on-error` で空として進む作り(hub と同じ) | ② |

## 利用者がやること

### 1. push する(PowerShell)

1. PowerShell で `cd C:\biyori-concierge`
2. `git log --oneline -1` で、段階 1 の commit があることを確かめる。
3. `git push -u origin main`
4. 成功の見分け方: エラーなく終わり、ブラウザで `https://github.com/ktakemaru/biyori-concierge` を開くとファイルが見える。

### 2. テストが通ることを見る(ブラウザ)

1. リポジトリの上の **Actions** タブを開く。
2. 左の一覧の **tests** を押し、いちばん上の実行を開く。
3. 成功の見分け方: `unittest (ubuntu-24.04)` と `unittest (windows-latest)` の両方に緑のチェック。

### 3. 手動実行 ①: 山 3 座・棚に残さない

1. **Actions** タブ → 左の一覧の **collect** を押す。
2. 右の **Run workflow** ボタンを押す(ブランチは `main` のまま)。
3. 入力: `confirm` に `yes-run-live`、`agents` は `yamabiyori`、`yama_limit` は `3`、`publish` は **チェックしない**。
4. 緑の **Run workflow** を押す。数秒後に一覧へ新しい実行が出る。
5. 成功の見分け方: 実行を開くと `collect` ジョブに緑のチェック、`publish` は灰色(skipped)。下の **Summary** に「取得の結果」の表が出て、yamabiyori が `ok`、「429: なし」「止められたホスト: なし」。
6. 失敗したとき: Summary の「理由」の列(`blocked_host` ならホスト名も)と、`collect` ジョブの「Collect (live)」の行を開いた中身を、そのまま伝えてください。成果物は実行のページ下の **Artifacts** の `collect-result` から zip で取れます。

### 4. 手動実行 ②: 山 全 76 座・棚に残す

1. ① と同じ手順で、`yama_limit` に **`all`** と入れる(空にするとエラーで止まります)、`publish` に **チェックを入れる**。
2. 成功の見分け方: `collect` と `publish` の両方に緑のチェック。リポジトリの **Code** タブでブランチ切り替え(`main` と書かれたボタン)から `data` を選ぶと、`manifest.json`・`ATTRIBUTION.md`・`yamabiyori/`・`proposals/`・`logs/` がある。
3. `publish` が `403` などの権限エラーで落ちたとき: **Settings** → **Actions** → **General** → 下の **Workflow permissions** を見て、伝えてください(勝手には変えないでください)。

### 5. 結果を伝える(次の段階の最初に記録します)

①② それぞれについて: 429 が出たか / 所要時間(実行ページの右上の時間、または Summary の「所要(秒)」)/ 通信の回数(Summary の「通信の回数」と「通信: 合計」)/ 止められたホスト / ② の `data` ブランチにファイルができたか。

**変数 `BIYORI_COLLECT_SCHEDULE` は作らない・`on` にしないでください**(段階 5 まで)。

## 利用者に決めてほしいこと

1. バックテストの収集と取得の時刻を離す間隔の目安(今は仮置き 30 分。今の時刻は 67 分以上離れているので、変えなくても動作には影響しません)。決めなければ、そのまま仮置きで進めます。
