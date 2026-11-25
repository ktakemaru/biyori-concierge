# ホシビヨリ → biyori-proposal/1 対応表

入力: `explore_hoshibiyori.py --json-out` の出力(`hoshibiyori-explore/1`)。コード: `collect/hoshibiyori.py`・`collect/run.py` の `run_hoshibiyori()`。
元: biyori-hub `docs/hoshibiyori-mapping.md`(v1.0.0 の内部のダンプが入力。考え方と点数の尺度の名前だけ使い、中身は新しく書いた)。
確かめた版: ホシビヨリ 1.2.0、commit `3860af7e7a7fb8556f73387e1fbb9e2e562d05ff`(出力の `version`・`commit` と、`C:/hoshibiyori` の HEAD が同じ)。
確かめた実物: 2026-11-25 の `stars.json`(22:08 作成、7,133,932 バイト)と `milkyway.json`(22:34 作成、1,971,350 バイト)。14 夜ぶんの `--nights` つき。
方針: 取れない項目は推測で埋めず `null` にし、`diagnostics.warnings` に理由を書く。

## 0. 取得の側で確かめること

- 実行は 2 回。**順番は 星空・星座モード(`stars`)→ 天の川モード(`milkyway`)で、変えない。** `--nights` は「その回に取ったセルと、期限内の保存」だけを読む(`requested_nights.py`)。
  天の川モードを先にすると、天の川の候補の地点のセルしか取らないので、ほとんどの地点が `not_examined` になりうる。2 つのモードは同じ `HOSHIBIYORI_DATA_DIR` を使い、保存の期限(MSM 3 時間・ECMWF 6 時間)の内側で続けて実行する。
- 実測(2026-11-25、手元の PC。`C:/temp/stage3/run-log.txt`): 星空・星座モード 通信 455 回・234.1 秒、天の川モード 通信 0 回・583.2 秒。**2 回目で通信は増えなかった。**
- 成功の条件: 終了コード 0、出力がある、`schema` が `hoshibiyori-explore/1`、取り出した版の `schemas/hoshibiyori-explore.schema.json` の検査に通る、`target` が頼んだモード、`requested_nights` の夜が渡した 14 夜と同じ。
  終了コード 2(ホシビヨリは JSON を書かない)・時間切れ・検査に通らないものは失敗で、その回の星は使わない(棚は前回のまま)。片方のモードだけ失敗したときも、2 つとも前回のまま(一緒に入れ替える)。
- `fetch.status` が `partial`(取得できなかったセルが 20% 未満)は成功として扱い、提案の `status` を `partial`(`fetch_incomplete`)にする。
- 子プロセスは `TZ=Asia/Tokyo`(山と同じ)。HTML レポート・天気図・ひまわり画像は取得しない(`generate_report.py` を実行しない)。

## 1. 棚に置くもの

| ファイル | 中身 |
|---|---|
| `hoshibiyori/stars.json` | 星空・星座モードの `--json-out` そのまま |
| `hoshibiyori/milkyway.json` | 天の川モードの `--json-out` そのまま |
| `proposals/hoshibiyori.json` | 下の 4 章。3,271 件・9.6MB(実物で変換した数。検査に 5.1 秒) |

## 2. 使う項目(実物で確かめた意味)

| 項目 | 意味・実物で確かめたこと |
|---|---|
| `site_index[]` | 全 897 地点。`site_id`・`name`・`label`・`municipality`・`lat`・`lon`・`is_primary`・`group`・`requires_lift_access`。**`site_id` が `null` の地点は 0**(897 とも別々の ID)。`label` も 897 とも別々、`name` は 822 種類(同じ名前がある)。`requires_lift_access` が真は 9 地点。2 つのモードで中身は同じ。**`origin`(出どころの語)は入っていない**が、OSM 由来の地点を含む(ODbL) |
| `requested_nights[].night_date` | 夜の始まりの日付 |
| `.window_kind` | `moon_free` = 月の無い暗い時間帯で調べた / `dark` = 月の無い時間帯が無い(または最小の晴れ間 1 時間より短い)ので、暗い時間帯ぜんぶで調べた / `none` = 調べていない。実物: 11/25・11/26 が `dark`、11/27〜12/8 が `moon_free`、`none` は 0 夜 |
| `.none_reason` | 調べていない理由。実物には無い(全部 `null`) |
| `.forecast_regime` | `MSM` / `ECMWF`。実物: 11/25〜11/27 が MSM、11/28〜12/8 が ECMWF。**ECMWF の夜の雲量は目安**(`notes` の文) |
| `.selected`・`.not_selected_reason` | 候補の上位 6 夜に入ったか。実物: 12/3〜12/8 が候補の夜。11/25・11/26 は `no_moon_free_window`、11/27〜12/2 は `not_in_top_n`。**今週末(11/28・29)は候補の夜でない** |
| `.moon` | 基準地点(石廊崎)の暗い時間帯のうち月が出ている時間 `up_hours`・区間・輝面比 |
| `.moon_free_hours`・`window_start`・`window_end` | 基準地点の月の無い時間帯。`dark` の夜は `null` |
| `.counts` | `all`(897 地点)・`primary`(146)・`reference`(751)ごとの件数。**全国の数で、出発地からの距離では絞られていない** |
| `.sites[]` | 条件を通った地点は全部、それ以外は主軸の地点だけ。`status` = `passed`/`failed`/`not_examined`。**`dark` の夜の `passed` は、月が出ている夜に雲と光害の条件を通ったという意味**(11/25 は 541 地点、11/26 は 287 地点が `passed` だが、月は暗い時間帯ぜんぶに出ている) |
| `.sites[].window_start`・`window_end` | その地点で調べた時間帯(`moon_free` の夜は月の無い時間帯) |
| `.sites[].clear_start`・`clear_end`・`clear_hours` | 視界遮蔽雲量 30% 以下が 1 時間以上続く、最長の晴れ間。条件を通った地点には必ずある |
| `.sites[].score` | いつも `null`(`--nights` ではスコアを出さない) |
| `finals[]`・`outlooks[]` | 候補の夜(上位 6 夜)の候補。`rank` は `group`(主軸・参考)ごとの順位で、夜をまたいだ通しの番号。実物: `finals` は 2 つのモードとも 0 件(候補の夜が全部 MSM の範囲の外)、`outlooks` は星空・星座 3,288 件・天の川 0 件。**候補の夜でない夜の地点には `rank` が無い** |
| `outlooks[].score` | 星空・星座モードは `null`(順位は `rank`)、天の川モードは数値 |
| `scanned_nights[]` | 走査した 14 夜。`selected`・`regime`・`not_selected_reason`・`winter_milky_way`(冬の天の川の帯。基準地点・平らな地平線の目安) |
| `fetch` | `api_calls`・`cache_hits`・`total_cells`・`failed_cells`・`rate_limited`・`retries`。実物: 星空・星座 455・6133・456・0・偽・0、天の川 0・12・2・0・偽・0 |
| `thresholds` | `milkyway_few_results` = 5、`min_clear_window_hours` = 1.0、`cloud_obstruction_threshold_pct` = 30.0、`lp_alr_threshold` = 10.66 |

## 3. 理由のコード(実物とスキーマから)

| 項目 | コード | 実物の件数・夜 | ホシビヨリの言い方(画面の文・`AGENTS.md`・スキーマの説明) |
|---|---|---|---|
| `reasons` | `cloud_filter` | 出る | 「雲」(画面「通らなかった理由(重なりあり): 雲 …」) |
| | `light_pollution_filter` | 出る | 「光害」(同) |
| | `direction_filter` | 天の川モードだけ出る | 「方角」(同) |
| `not_examined_reason` | `no_window_at_site`・`cell_not_fetched`・`fetch_failed`・`no_forecast` | 0 件 | 地点ごとの言い方は画面に無い(未確認)。件数は「調べていない N地点」 |
| `not_selected_reason` | `no_moon_free_window` | 11/25・11/26 | 夜ごとの言い方は「暗い時間帯ぜんぶで調べた」「月が出ているのは N時間」 |
| | `not_in_top_n` | 11/27〜12/2 | 「候補の上位の夜に入っていない」 |
| | `no_sunset_or_sunrise`・`no_astronomical_darkness` | 0 夜 | 「日没・日の出が求まらない」「天文薄明の終わり・始まりが無い」 |
| `none_reason` | `out_of_scanned_range` | 0 夜 | 「調べていない(今日から14夜の外)」 |
| | `out_of_forecast_range` | 0 夜 | 「調べていない(予報の範囲の外)」 |
| | `reference_forecast_not_fetched` | 0 夜 | 「調べていない(基準地点の予報を取っていない)」 |
| | `no_sunset_or_sunrise`・`no_astronomical_darkness` | 0 夜 | 上と同じ文に「調べていない」が付く |

`requested_nights[].sites[]` の理由の組(実物): 星空・星座 = 通った 4,099・雲 932・光害 61・雲と光害 9 / 天の川 = 方角 1,042・雲と方角 932・光害 61・雲と光害 9(通った地点は 0)。

## 4. 提案(proposals[])

1 件は「モード・地点・夜」。入れるのは、`window_kind` が `moon_free` の夜に `status` が `passed` の地点だけ。

| 契約の項目 | 取り方 | 備考 |
|---|---|---|
| `id` | `hoshibiyori:{mode}:{night_date}:{site_id}` | |
| `title` | `{label} {night_date} の夜` | |
| `place` | `name` = `label`、`lat`・`lon`、`region` = `municipality`、`site_ref` = `hoshibiyori:{site_id}`、`elevation_m` = `null`(出力に無い) | |
| `time_window` | `clear_start`〜`clear_end`(`kind: clear_window`)。無ければ `window_start`〜`window_end`(`kind` は付けない。契約に合う語が無い)。どちらも無い行は提案にせず警告 | 契約の `start`・`end` は文字列が必須で `null` を入れられないため |
| `suitability.band` | MSM の夜 `go`、ECMWF の夜 `maybe`(雲量は目安) | `no` は作らない |
| `suitability.score` | 候補の夜の地点でスコアがあれば `{value, scale: hoshibiyori-final-score / hoshibiyori-outlook-score, go_threshold: null}`、無ければ `null` | 星空・星座モードは `null`。**山の `yamabiyori-0-100` とは尺度が違い、比べない** |
| `evidence[]` | `clear_hours`(h)・`mean_obstruction`(%)・`forecast_regime`・`moon_free_hours`(h)・`alr`・`alr_rank_pct`(%)・`rank` | 無い値は `null` |
| `constraints[]` | `requires_lift_access` → `{kind: access, text: "リフト要の地点(運行は確かめていない)", hard: false}` | |
| `uncertainty` | `lead_days` = 夜の日付 − 変換した日、`reliable_up_to_days` = 3(README「直近約3日は気象庁MSM」)、確信度は `null` | |
| `details` | `mode`・`night_date`・`site_id`・`group`・`rank_kind`・地点の時間帯 | |

`site_id` が `null` の地点は提案にしない(名前だけで突き合わせない。実物には 0 件。見本の作り物でテストした)。

## 5. 夜に見られるもの(見どころ)

**どの星・星座・惑星・流星群が見えるかは、JSON に無い。** あるのは `scanned_nights[].winter_milky_way`(冬の天の川の帯の、基準地点・平らな地平線での目安)だけ。
レポート(HTML)の「この時期の見どころ」(`sky_highlights.py`)は `--json-out` に入らない。今回は足さない(`docs/hoshibiyori-proposal-20261125.md` に、ホシビヨリへの提案として書いた)。

## 6. 通信先

- `api.open-meteo.com`(予報)。
- 天文暦 `de421.bsp`(無いときだけ 1 回): `hb_paths.py` の `_EphemerisLoad` が Skyfield の `Loader` に渡す。取得先は Skyfield 1.55(手元に入っている版)の `iokit.py` 64 行 `_JPL = 'https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/'` と 127 行 `('*.bsp', _JPL)`。
  実通信では確かめていない(転送先が別のホストなら、計測フックが止める)。`load.timescale()` は Skyfield に入っている表を使い、通信しない(`builtin=True` が既定)。
- 光害・地平線のデータ(`step3_light_pollution/data/`・`step2_terrain/horizon_*.csv`)と `stargazing_spots.json` はリポジトリに入っていて、実行時に取得しない。
