# ホシビヨリ → biyori-proposal/1 対応表

入力: `explore_hoshibiyori.py --json-out` の出力(`hoshibiyori-explore/1`)。コード: `collect/hoshibiyori.py`・`collect/run.py` の `run_hoshibiyori()`。
元: biyori-hub `docs/hoshibiyori-mapping.md`(v1.0.0 の内部のダンプが入力。考え方と点数の尺度の名前だけ使い、中身は新しく書いた)。
確かめた版: ホシビヨリ 1.2.0、commit `3860af7e7a7fb8556f73387e1fbb9e2e562d05ff`(出力の `version`・`commit` と、`C:/hoshibiyori` の HEAD が同じ)。
確かめた実物: 2026-11-25 の `stars.json`(22:08 作成、7,133,932 バイト)と `milkyway.json`(22:34 作成、1,971,350 バイト)。14 夜ぶんの `--nights` つき。
**新しい項目(`night_rank`・`origin`・`highlights`。ホシビヨリ main `dd2f792`、PR #42。版は 1.2.0 のまま)を確かめた実物**: `C:/temp/hoshi-followup-20261127/after3/` の
`st_nights.out.json`(星空・星座、2026-11-27 09:06:17 作成)と `mw_nights.out.json`(天の川、09:05:58 作成)。出力の `commit` は `bfc0a92a…`、
**主軸 146 地点だけ**(参考の地点 751 は入っていない)、固定キャッシュで作ったもの、14 夜(11/27〜12/10)の `--nights` つき。見本は `tests/fixtures/shelf_hl/`(16 地点に減らした。作り方は `tests/make_highlights_fixture.py`)。
**新しい項目は「あれば使う」**: 版の番号(どちらも 1.2.0)では見分けず、項目があるかどうかで見分ける。無い出力(段階 3 の見本・2026-11-25 の実物)では、答えは段階 3 と 1 バイトも変わらない。
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
| `site_index[]` | 全 897 地点。`site_id`・`name`・`label`・`municipality`・`lat`・`lon`・`is_primary`・`group`・`requires_lift_access`。**`site_id` が `null` の地点は 0**(897 とも別々の ID)。`label` も 897 とも別々、`name` は 822 種類(同じ名前がある)。`requires_lift_access` が真は 9 地点。2 つのモードで中身は同じ。1.2.0 の出力には `origin` が無いが、OSM 由来の地点を含む(ODbL) |
| `site_index[].origin` | 地点の出どころ(新しい出力だけ)。スキーマの値: `curated`・`curated+test_site`・`curated+viewpoint`・`curated_external`(主軸)、`viewpoint`・`test_site`(参考)。**OSM 由来(ODbL)は `viewpoint` と `curated+viewpoint`**(スキーマの説明「viewpoint は OpenStreetMap の展望データ(ODbL)由来、curated+viewpoint は OSM の地点と統合した主軸の地点(座標は curated 側)」)。実物(主軸 146): `curated` 78・`curated_external` 62・`curated+viewpoint` 3・`curated+test_site` 3。**`viewpoint` は実物に無い**(参考の地点が入っていないため。実物では確かめられていない)。使い方は 6 章 |
| `requested_nights[].night_date` | 夜の始まりの日付 |
| `.window_kind` | `moon_free` = 月の無い暗い時間帯で調べた / `dark` = 月の無い時間帯が無い(または最小の晴れ間 1 時間より短い)ので、暗い時間帯ぜんぶで調べた / `none` = 調べていない。実物: 11/25・11/26 が `dark`、11/27〜12/8 が `moon_free`、`none` は 0 夜 |
| `.none_reason` | 調べていない理由。実物には無い(全部 `null`) |
| `.forecast_regime` | `MSM` / `ECMWF`。実物: 11/25〜11/27 が MSM、11/28〜12/8 が ECMWF。**ECMWF の夜の雲量は目安**(`notes` の文) |
| `.selected`・`.not_selected_reason` | 候補の上位 6 夜に入ったか。実物: 12/3〜12/8 が候補の夜。11/25・11/26 は `no_moon_free_window`、11/27〜12/2 は `not_in_top_n`。**今週末(11/28・29)は候補の夜でない** |
| `.moon` | 基準地点(石廊崎)の暗い時間帯のうち月が出ている時間 `up_hours`・区間・輝面比 |
| `.moon_free_hours`・`window_start`・`window_end` | 基準地点の月の無い時間帯。`dark` の夜は `null` |
| `.counts` | `all`(897 地点)・`primary`(146)・`reference`(751)ごとの件数。**全国の数で、出発地からの距離では絞られていない** |
| `.sites[]` | 条件を通った地点は全部、それ以外は主軸の地点だけ。`status` = `passed`/`failed`/`not_examined`。**`dark` の夜の `passed` は、月が出ている夜に雲と光害の条件を通ったという意味**(11/25 は 541 地点、11/26 は 287 地点が `passed` だが、月は暗い時間帯ぜんぶに出ている)。新しい出力では、ホシビヨリの注記とスキーマの `status` の説明にも「`window_kind` が `dark` の夜の `passed` は、月を条件にしていない」と書かれた |
| `.sites[].night_rank` | **その夜の中の順位**(新しい出力だけ)。`group`(主軸・参考)ごとに 1 から、`status` が `passed` の地点だけ(ほかは `null`)。星空・星座モードはどの夜も「光害(ALR)が小さい → 月の影響が小さい時間が長い順」、天の川モードはスコア順(スキーマの説明)。実物(星空・星座): 11/27〜12/9 の `passed` の地点の全部に付き、`passed` でない地点には付かない(0 件)。天の川モードは `passed` が 0 地点なので、どの夜も `null` だけ |
| `.sites[].window_start`・`window_end` | その地点で調べた時間帯(`moon_free` の夜は月の無い時間帯) |
| `.sites[].clear_start`・`clear_end`・`clear_hours` | 視界遮蔽雲量 30% 以下が 1 時間以上続く、最長の晴れ間。条件を通った地点には必ずある |
| `.sites[].score` | いつも `null`(`--nights` ではスコアを出さない) |
| `finals[]`・`outlooks[]` | 候補の夜(上位 6 夜)の候補。`rank` は `group`(主軸・参考)ごとの順位で、夜をまたいだ通しの番号。実物: `finals` は 2 つのモードとも 0 件(候補の夜が全部 MSM の範囲の外)、`outlooks` は星空・星座 3,288 件・天の川 0 件(11/27 の実物は 846 件・0 件)。**候補の夜でない夜の地点には `rank` が無い**。新しい出力では、その夜の地点を `night_rank` で並べられる(2.1) |
| `outlooks[].score` | 星空・星座モードは `null`(順位は `rank`)、天の川モードは数値 |
| `scanned_nights[]` | 走査した 14 夜。`selected`・`regime`・`not_selected_reason`・`winter_milky_way`(冬の天の川の帯。基準地点・平らな地平線の目安) |
| `fetch` | `api_calls`・`cache_hits`・`total_cells`・`failed_cells`・`rate_limited`・`retries`。実物: 星空・星座 455・6133・456・0・偽・0、天の川 0・12・2・0・偽・0 |
| `highlights` | 夜ごとの見どころ(新しい出力だけ。5 章) |
| `thresholds` | `milkyway_few_results` = 5、`min_clear_window_hours` = 1.0、`cloud_obstruction_threshold_pct` = 30.0、`lp_alr_threshold` = 10.66 |

### 2.1 `rank` と `night_rank` の違い(新しい出力)

| | `finals[]`・`outlooks[]` の `rank` | `requested_nights[].sites[].night_rank` |
|---|---|---|
| ある夜 | 候補の夜(上位 6 夜)だけ | 聞かれた夜の全部(`passed` の地点だけ) |
| 番号 | `group` ごとの、**夜をまたいだ通しの番号**(12/5 の先頭が 1 なら、12/6 の先頭は 1 でない) | `group` ごとの、**その夜の中の番号**(どの夜も 1 から) |
| 実物で確かめたこと | 11/27 の実物で `outlooks` は 846 件(12/5〜12/9) | 候補の夜(12/5〜12/9)の主軸の地点の並びは、同じ夜の `outlooks` の `rank` の並びと同じ(ホシビヨリの報告書。こちらでも確かめた) |

- **星空・星座モードで予報が MSM の夜は、2 つの並びが違いうる**(ホシビヨリの報告書の「決めてほしいこと 1」): `finals` は「晴れ時間が長い → 平均雲量が低い → ALR → 月」、`night_rank` は「ALR → 月」。
  実物は MSM の候補の夜が 0 夜(`finals` が 0 件)で、食い違いは実物では起きていない(確かめられていない)。
- コンシェルでの使い方(`concierge/stars.py` の `site_key`): 星の地点の並びは「主軸の地点を先 → `rank`(あれば)→ `night_rank`(あれば)→ 直線距離 → `site_id`」。
  候補の夜で `rank` がある地点は、今までどおり `rank` で並べる(ホシビヨリの画面と同じ並び。MSM の夜の食い違いは、このとき `rank` が勝つ。仮置き)。`rank` が無い地点にだけ `night_rank` を使う。
  どちらも無い出力(1.2.0)では、今までの並び(距離 → `site_id`)のまま。

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
| `evidence[]` | `clear_hours`(h)・`mean_obstruction`(%)・`forecast_regime`・`moon_free_hours`(h)・`alr`・`alr_rank_pct`(%)・`rank` | 無い値は `null`。`rank` は、候補の夜の `rank` があればそれ、無ければ `night_rank`(新しい出力。どちらも無ければ `null`)。番号の意味が違う(2.1)ので、どちらの番号かは `details.rank_kind` に書く |
| `constraints[]` | `requires_lift_access` → `{kind: access, text: "リフト要の地点(運行は確かめていない)", hard: false}` | |
| `uncertainty` | `lead_days` = 夜の日付 − 変換した日、`reliable_up_to_days` = 3(README「直近約3日は気象庁MSM」)、確信度は `null` | |
| `details` | `mode`・`night_date`・`site_id`・`group`・`rank_kind`(`final`・`outlook` = 候補の夜の `rank`、`night` = その夜の中の順位 `night_rank`、`null` = 順位なし)・地点の時間帯 | `night` は新しい出力のときだけ(`details` は自由欄で、契約に語の一覧は無い) |

`site_id` が `null` の地点は提案にしない(名前だけで突き合わせない。実物には 0 件。見本の作り物でテストした)。

## 5. 夜に見られるもの(見どころ)

**1.2.0 の出力(2026-11-25 の実物・段階 3 の見本)には無い。** あるのは `scanned_nights[].winter_milky_way`(冬の天の川の帯の、基準地点・平らな地平線での目安)だけ。
**新しい出力には `highlights` がある**(ホシビヨリのレポートの「この時期の見どころ」と同じ値。`--json-out` のときだけ計算。探索・順位・スコアには使っていない)。形はスキーマ(`$defs.highlights` ほか)と実物から写した:

| 項目 | 意味・実物で確かめたこと |
|---|---|
| `highlights` | 計算しなかったときは `null`。実物は 2 つのモードともある。コンシェルは、使うモードの出力のものを使う |
| `.basis` | `text`「基準の地点・平らな地平線の目安(地形・雲は見ていない)」、`reference_site`(石廊崎)、`flat_horizon: true`・`terrain: false`・`clouds: false`、`min_alt_deg` 15(この高度以上を「見える」)、`max_items_per_slot` 4 |
| `.computed_at` | 流星群の「これから 30 日以内」の起点 |
| `.by_night[night_date]` | 夜の始まりの日付 → その夜の見どころ。**暗い時間帯が無い夜は `null`**、走査した夜の外の夜はキーが無い。実物: 14 夜とも中身がある(`null` は 0 夜。**`null` の夜は実物では確かめられていない**)。12/10(`window_kind: none` の夜)にも中身がある |
| `.slots[]` | 時間帯 `key`/`label` = `evening` 宵・`midnight` 夜半・`dawn` 明け方、`start`・`end`、`moonlit`(新月に近くない月が出ている時刻がある)・`moon_up_intervals`、`items[]`。実物はどの夜も 3 つ、`items` は 4 つずつ(上限 4) |
| `.slots[].items[]` | `type`(`planets` = 惑星の組 / `target` = 星座・星の並び・対象)、`name`(`planets` は「惑星」、ほかは組の名前。例「みなみのうお座」)、`in_season`、`has_first_magnitude`、`members[]` |
| `.items[].members[]` | `id`・`name`・`kind`(惑星・星・星団・星雲・銀河・星の並び。従来からの対象は `null`)・`faint_in_moonlight`・**`coordinates_unverified`**・`start`・`end`(その時間帯の中で高度 15° 以上の最初と最後の時刻。**時間帯で切られている**ので、出・入りの時刻ではない)・`peak_time`・`peak_az`・`peak_alt`(その時間帯でいちばん高い時刻と高度)。時刻は丸めていない(秒より下あり) |
| `.not_visible[]` | **その夜は一度も 15° 以上に出ない対象**(`name`・`next_month`・`ids`・`kinds`・`coordinates_unverified`)。実物はどの夜も「天の川銀河中心」(未照合でない)・「さそり座」(未照合) |
| `.showers[]` | これから 30 日以内に極大がある流星群(夜によらないので 1 回だけ): `name`・`peak_time`・`zhr`・**`zhr_note`**「例年の目安(理想の条件での1時間あたりの出現数。その年の予報ではない)」・**`caveat`**「理想の条件での目安で、実際に見える数はこれより少ない。突発的な増減は予測できない」・`night_date`(極大の夜)・`radiant_min_alt_deg` 20・`radiant_start`/`radiant_end`・月。実物: ふたご座流星群 1 件、`night_date` は 12/14 で、**聞かれた 14 夜(11/27〜12/10)の外**(流星群の夜の答えは実物では確かめられていない) |

- **`coordinates_unverified: true`** = 座標を星表と照らしていない対象(ホシビヨリの `targets.json` で「未照合」の 19 件)。`false` は惑星と従来からの対象で、照合済みという意味ではない(記録が無い)。実物の 11/28: 31 件のうち 19 件が真。真は、星(実物に出たものは全部)・オリオン大星雲・アンドロメダ銀河・秋の四辺形。偽は、金星・火星・木星・土星・オリオン座・カシオペヤ座・夏の大三角・冬の大三角・すばる。
- **`slots` に無い対象が「見えない」とは限らない**(時間帯ごとの上限 4 件・見える時間が 30 分より短い対象は入らない)。見えないと言えるのは `not_visible` の対象だけ。

### 5.1 コンシェルでの使い方(段階 3 見どころ。`concierge/stars.py`)

- 見どころの事実 `[H…]`(1 件 = 夜と対象。`members[]` の 1 つ。同じ夜に 2 つ以上の時間帯に出る対象は 1 件にまとめ、時間帯ごとの時刻を持つ)。今の時期は見えない対象(`not_visible`)も同じ字 `[H…]` の事実にする(種類が違う)。流星群は別の字 `[M…]`(1 件 = 流星群)。
- 作るのは、`highlights` があり、その夜の `by_night` が `null` でなく、**その夜に星の地点が付く(案の夜の枠に地点がある)**ときだけ。地点の付かない夜には作らない(仮置き)。
- **`coordinates_unverified: true` の対象は事実にしない**(今回は答えに書かせない。安全側)。名前は「見どころの名前の一覧」に入れて、書いたら照合で止める。
- 流星群の事実は、極大の夜(`night_date`)が聞かれた夜で、その夜に星の地点が付くときだけ。
- 書いてよい名前は `members[]` の名前・`not_visible` の名前・流星群の名前だけ。組の名前(`items[].name`。例「みなみのうお座」「惑星」)は書かせない。
- 決まった文: `star_basis`(`basis.text` を入れた文。見どころを書いた答えに必ず)、`star_showers`(流星群ごと。`zhr_note` と `caveat`)。

## 6. 地点の出どころと ODbL(段階 3 見どころ)

- 答えの星の帰属の文(`star_attribution`)の「地点は © OpenStreetMap contributors(ODbL)」は、**`origin` が無い出力では今までどおりいつも付ける**(安全側)。
- `origin` がある出力では、ODbL の無い帰属の文(`star_attribution_plain`)も資料に入れ、**答えに使った星の地点(印を付けた地点とおすすめの地点)に OSM 由来(`viewpoint`・`curated+viewpoint`)が 1 つでもあれば ODbL のある文、無ければどちらか**を写させる(`verify` が照らす)。`origin` の無い地点(新しい出力でも)は OSM 由来とみなす。
- 棚の `ATTRIBUTION.md` は棚のファイル全部の帰属で、今までどおり ODbL を書く(棚には OSM 由来の地点を含む全部の地点が入るため)。

## 7. 通信先

- `api.open-meteo.com`(予報)。
- 天文暦 `de421.bsp`(無いときだけ 1 回): `hb_paths.py` の `_EphemerisLoad` が Skyfield の `Loader` に渡す。取得先は Skyfield 1.55(手元に入っている版)の `iokit.py` 64 行 `_JPL = 'https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/'` と 127 行 `('*.bsp', _JPL)`。
  実通信では確かめていない(転送先が別のホストなら、計測フックが止める)。`load.timescale()` は Skyfield に入っている表を使い、通信しない(`builtin=True` が既定)。
- 光害・地平線のデータ(`step3_light_pollution/data/`・`step2_terrain/horizon_*.csv`)と `stargazing_spots.json` はリポジトリに入っていて、実行時に取得しない。
