# ヤマビヨリ → biyori-proposal/1 対応表

元: biyori-hub `docs/yamabiyori-mapping.md`(`b3c967c`)。変えたところは `docs/ported-from-hub.md`。
入力: `mountain_weather_mvp.py --json-out` の出力(`yamabiyori-report-data/1`、mode `explore`)。棚では `yamabiyori/explore.json` にそのまま置く。
コード: `collect/yamabiyori.py`。方針: 取れない項目は推測で埋めず `null`(または空配列)にし、`diagnostics.warnings` に理由を書く。

## 0. 取得の側で確かめること

- 終了コード 0、出力の `schema` が `yamabiyori-report-data/1`、`mode` が `explore`、`days[]` に `date`・`rows`・`all` があり、各行に `mountain`・`score` がある(`output_problems()`)。どれかが違えば、その回の山は使わない(棚は前回のまま)。
- 子プロセスは `TZ=Asia/Tokyo` で動かす。ヤマビヨリは `date.today()` で対象の日(今日〜14 日先)を決めるため、UTC の Actions のマシンでは、朝 4:27 の実行で日付が 1 日ずれる。

## 1. 山の一覧(`yamabiyori/mountains.json`、スキーマ `biyori-mountains/1`)

`mountain_weather_core.py` の `MOUNTAINS` を ast で読む(実行しない)。`id` は各要素の `"id"`(`m001`〜。ヤマビヨリ 1.10.0 から)をそのまま使い、並び順では作らない(指示書 D10。2026-11-22)。イキモノビヨリ `data/sites.yaml` の `site_ref: yamabiyori:mNNN` と同じ名前(ヤマビヨリの最初の ID は 2026-11-16 時点の並び順の番号を固定したもの)。

次のときは山の一覧を読めないとして、そのビヨリを `failed`(理由 `mountains_unreadable`)にする(子プロセスを起動する前に分かる。`load_mountains()`):

- `id` が無い要素がある(古い版のヤマビヨリ)。並び順で作る形に戻す逃げ道は作らない。
- `id` が文字列でない、または `m` + 数字 3 桁の形でない(ヤマビヨリの決まりでは利用者が足す山は `u001`〜 だが、その仕組みはまだ無く、棚のスキーマも `^m\d{3}$` なので今は通さない)。
- 同じ `id` が 2 つ以上ある。

## 2. 提案(proposals[])

| 契約の項目 | 取り方 | 出典・備考 |
|---|---|---|
| `id` | `yamabiyori:explore:{date}:{山のID}` | 例 `yamabiyori:explore:2026-10-12:m002` |
| `title` | `{山名} {label}` | `label` は `2026-10-12(月)` 形式 |
| `place.name` | `rows[].mountain` の末尾 `(NNNNm)` を除いた名前 | |
| `place.lat`/`lon`/`elevation_m`/`region` | 行に `id` があれば、山の一覧の同じ `id` の山(ヤマビヨリ 1.10.0 からの `--json-out`。`rows[]`・`all[]` とも)。行に `id` が無い・`null` のときだけ、`MOUNTAINS` の名前と標高が一致する 1 件(古い棚・76 座に無い山)(2026-11-22) | 名前と標高で 0 件・複数件、行の `id` が一覧に無い、`id` で引いた山の名前が行の名前(末尾の `(NNNNm)` を除く)と違う(ID のずれ)ときは、提案を作らず `diagnostics.warnings` に書く(座標を推測しない)。`status: partial` |
| `place.site_ref` | `yamabiyori:{山のID}` | |
| `time_window` | 日の出・日没があれば `activity_window` = 日の出−1 時間 〜 日没+30 分(`mountain_weather_mvp.py:89` `TRIP_START_OFFSET_HOURS = -1`、`:149` `ACTIVITY_END_GRACE_MINUTES = 30`)。日の出・日没は、取得のあとにヤマビヨリの `cache/ecmwf_ifs025_{lat:.4f}_{lon:.4f}_15d.json` の `daily.sunrise/sunset` を読むだけで取る。なければ暦日(00:00〜翌 00:00 +09:00)で `calendar_day`(粗い値) | |
| `suitability.band` | `score >= 70` → `go`、未満 → `no`(ちょうど 70 は go) | `mountain_weather_mvp.py:63` `MIN_SCORE_THRESHOLD = 70.0`。`no` は「ヤマビヨリの基準(70 点)未満」の意味で「行ってはいけない」ではない |
| `suitability.score` | `{value, scale: "yamabiyori-0-100", go_threshold: 70.0}` | ビヨリ間で比べない |
| `evidence[]` | 70 点以上の行(`rows[]`)の列(下) | 70 点未満の簡易行(`all[]`)は空、`details.detail_level: score_only` |
| `constraints[]` | `hazards.thunder/wind/cold` が `-` 以外のとき `{kind: hazard, hazard, level, text: "雷:注意", hard}`。`警戒`・`危険` → `hard: true`、`注意` → `false`。簡易行は `hazard_class`(`warning` → 警戒以上・hard、`caution` → 注意) | 段階の語: `mountain_weather_core.py` `HAZARD_LEVELS = ((0,"-"),(40,"注意"),(80,"警戒"),(100.0001,"危険"))` |
| `uncertainty.lead_days` | 対象の日 − 変換した時刻(日本時間)の日付 | |
| `uncertainty.reliable_up_to_days` | `3` | ヤマビヨリ README「信用してよいのは3日前まで」 |
| `uncertainty.confidence` | `{value: null, method: "none", validated: false}` | explore は確信度を出さない |
| `native_ref` | `{format: "yamabiyori-report-data/1", path: "yamabiyori/explore.json"}` | 棚の中の相対パス |
| `details` | `native_row`(元の行そのまま)・`date`・`mountain_id`・`access`・`detail_level` | 答える側は根拠に使わない |

### evidence の列

`ridge_wind_ms`(m/s), `cape`(J/kg), `cloud_pct`(%), `cloud_pct_raw`(%), `ridge_visibility`(m), `precip_wet_pct`(%), `precip_wet_hours`(h), `precip_total_hours`(h), `precip_msm_hours`(h), `precip_moist_hours`(h), `precip_prob_hours`(h), `precip_total_mm`(mm), `chill`(℃), `day_peak_wind_ms`(m/s), `day_peak_wind_hour`(時), `day_total_precip_mm`(mm)。値は丸めずそのまま、欠損は `null`。

## 3. 提案の全体

| 項目 | 値 |
|---|---|
| `status` | `ok`。座標・スコアを確定できない行を落としたとき、またはヤマビヨリが一部の山を取得できなかったとき(`fetched < pool_size`)は `partial` |
| `generated_at` | 変換した時刻(オフセットつき) |
| `data_as_of` | `[{source: "Open-Meteo (yamabiyori)", fetched_at: 取得が終わった時刻}, {source: "Open-Meteo jma_msm", run_time: 初期時刻, …}, {… ecmwf_ifs025 …}]`。回が分からなければ `run_time: null` |
| `diagnostics` | `api_calls`(この回の HTTP リクエスト数。call 換算ではない)、`runtime_s`、`fetch_finished_at`、`warnings` |
| `details` | `native_generated`(ヤマビヨリの `generated`。日付のみ)、`pool_size`、`fetched`、`model_runs` |
| `agent` | `{id: yamabiyori, version: plugin.json の version, commit: 取り出した commit}` |
