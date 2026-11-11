# 変更履歴

## 未公開(段階 1)

- リポジトリの骨組み(MIT、`config.yaml`、`config.local.example.yaml`、`schemas/`、`collect/`、`tests/`)。
- 計測フック(biyori-hub から写し)とテスト。
- 棚のスキーマ `biyori-shelf/1`(manifest)・`biyori-collect-run/1`・`biyori-request-log/1`・`biyori-mountains/1`。
- 山の取得(ヤマビヨリ `--json-out` を計測フックつきで実行)と、共通の形 `biyori-proposal/1` への変換。
- 予報の回(気象庁 MSM・ECMWF)を Open-Meteo のメタデータで取得の前後に記録。
- `collect.yml`(collect / publish の 2 ジョブ。定期実行は停止スイッチで止めたまま)、`tests.yml`。
- (段階 1 の追加の修正)meta.json の読み取りに失敗したモデルだけ、5 秒(仮置き)あけて 1 回だけ読み直す(計測フックの下のまま。4xx/5xx は読み直さない)。
  手動実行 2 回で 8 回中 3 回失敗し、same_before_after が None になったため。失敗の原因は未確認。
- (段階 1 の追加の修正)失敗の種類(例外の名前)を `logs/requests.json` の `by_error` と、取得の結果の表示(Summary・`collect run` の出力)に出す。
- (段階 1 の追加の修正)`yama_limit` の全 76 座は `all` と入れる方式にした(初期値 3 はそのまま)。空・`all` 以外の文字・0 以下は通信の前にエラーで止める。
  定期実行は `all` を渡す。手動実行で欄を空にしても 3 座で動いたため(GitHub が初期値を入れ直したためかは未確認)。
- (段階 1 の追加の修正)ヤマビヨリの explore.json の `pool_size`・`fetched` を確かめ、run.json・manifest に `coverage`(何座のうち何座)を入れ、
  Summary と `collect run` の出力に「76座のうち60座」の形で出す。全座そろわない回は `ok` でなく新しい状態 `incomplete`(理由 `partial_fetch`)。
  `pool_size`・`fetched` が無い・おかしい出力は `unexpected_output`。そろわない回を棚に載せるかは未決(暫定は載せる。`docs/collect-run4-analysis.md` 6 章)。
- 手動実行 collect #4(全 76 座。60 座だけ取れた)の記録の調べ `docs/collect-run4-analysis.md`。
- (段階 1 の追加の修正)全座そろわない回も棚に載せる(利用者の決定 A。状態 `incomplete` と `coverage`)。指示書 4 章・5.2・6.2(`lines.coverage`: 76 座のうち何座を調べたかを必ず言う)を直した。
- (段階 1 の追加の修正)ヤマビヨリの取り直し: `fetched` < `pool_size` なら同じコマンドをもう一度実行する(1 回目を含めて最大 3 回)。
  通信の上限(仮置き 450)と時間の上限(仮置き 4500 秒)は全部の回の合計。回ごとの通信の回数・`fetched` を run.json・manifest(`attempts`)・Summary に出す。
  2 回目以降の通信が多すぎれば「キャッシュが効いていない疑い」と出す。2 回目以降の 429 は即中止(rate_limited)。
- 診断のワークフロー `diagnose.yml`(手動実行だけ): api.open-meteo.com の IP アドレスごとに meta.json(jma_msm)を 10 回ずつ取り、
  成功・失敗の数・失敗した段階(TCP・TLS・応答待ちなど)・所要時間を Summary の表に出す。計測フックつき。ヤマビヨリは実行しない。
- 診断に比べ方を足した: IP ごとに「新しい接続」30 回と「接続の使い回し」30 回(切れたら張り直し、その回数と失敗を記録)を交互に行い、
  方式ごとの成功・失敗・失敗した段階・接続を張った回と張らなかった回の失敗を Summary に並べる。上限は仮置きで 300 回・1800 秒、ジョブは 40 分。
- (段階 1 の追加の修正)`collect.yml` の手動実行に `yamabiyori_ref`(ヤマビヨリのブランチか commit。初期値 `main`。定期実行は常に `main`)を足した。
  使った ref と commit を run.json・Summary・manifest に出す。main 以外の ref で取った回は棚に載せない(publish ジョブは skipped、`collect prepare` も止まる)。
  入力はヤマビヨリを取り出す前に `collect check-inputs` で検査する。診断 2 回目(新しい接続 60 回中 11 回失敗・使い回し 0 回)を受けて、使い回しを入れたヤマビヨリの版を試すため。
- `docs/collect-run4-analysis.md` に診断 2 回目の結果、`docs/stage1-report.md` を今の状態に合わせて書き直した。
- 段階 1 を締めた。ヤマビヨリ 1.9.1(接続の使い回し)の main で、全 76 座・失敗 0 件・約 137 秒、data ブランチに棚を公開(実行 B)。
  `docs/collect-run4-analysis.md` 9 章に実行 A・B と collect #4 の比較と、公開された棚の検査(すべてのスキーマに通った)を書いた。
  接続の開始が止まる根本の原因は未確認のまま。上限の値(通信 450・時間 4500 秒・ジョブ 90 分)の見直し案は `docs/stage1-report.md` に書き、値はまだ変えていない。
- 上限の値を利用者の決定に合わせた: ヤマビヨリの時間の上限を、1 回ごと(`timeout_s` 3600 → 2700 秒)・全部の回の合計(`total_timeout_s` 4500 → 2700 秒)とも 2700 秒に。
  通信の上限は 450 のまま、`timeout-minutes` は 90 のまま、バックテストとの間隔は 30 分のまま(仮置き)。
  指示書 5.2 の通信の上限の考え方を「1 回目の実測に、取り直しの分の余裕を足した値」に直した。
