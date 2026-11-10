# 変更履歴

## 未公開(段階 1)

- リポジトリの骨組み(MIT、`config.yaml`、`config.local.example.yaml`、`schemas/`、`collect/`、`tests/`)。
- 計測フック(biyori-hub から写し)とテスト。
- 棚のスキーマ `biyori-shelf/1`(manifest)・`biyori-collect-run/1`・`biyori-request-log/1`・`biyori-mountains/1`。
- 山の取得(ヤマビヨリ `--json-out` を計測フックつきで実行)と、共通の形 `biyori-proposal/1` への変換。
- 予報の回(気象庁 MSM・ECMWF)を Open-Meteo のメタデータで取得の前後に記録。
- `collect.yml`(collect / publish の 2 ジョブ。定期実行は停止スイッチで止めたまま)、`tests.yml`。
