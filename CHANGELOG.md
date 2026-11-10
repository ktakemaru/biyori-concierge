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
