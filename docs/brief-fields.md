# 資料(`biyori-brief/1`)に出す予報の値と決まった文の出典

`concierge brief` が、棚の提案(`proposals/yamabiyori.json`)の `evidence[]` から資料に出す値の一覧。
名前と単位は、ヤマビヨリ(`C:/yamabiyori`、commit `fdadece`・1.10.1)の README と画面の列名に合わせた。**名前の出典が見つからない値は出さない。**
コードの対応表は `concierge/brief.py` の `VALUE_FIELDS`。

## 出す値

| 値(`metric`) | 答えに出る名前(資料での名前) | 単位 | 「約」の表記 | 出典の場所 |
|---|---|---|---|---|
| `score`(提案の `suitability.score.value`) | 点数(基準 70 点) | 点 | 1 点の刻み | README「行ける」の目安 70点以上・`mountain_weather_mvp.py` 表の列「スコア」 |
| `ridge_wind_ms` | 稜線風速 | m/s | 1 m/s の刻み | `mountain_weather_mvp.py` `print_ranking_table()` の列「稜線風速m/s」・README 探索モードの表「稜線風速」 |
| `day_peak_wind_ms`(+ `day_peak_wind_hour`) | 日中ピークの風速(と、その時刻「6時」) | m/s | 1 m/s の刻み | README「スコアの仕組み」の危険信号「稜線の強風(日中ピーク)」・`hazard_warning_cell()` の「強風…(06時16.4m/s)」 |
| `cloud_pct` | 雲量 | % | 1 % の刻み | README 探索モード「雲量%(較正/生)は左が採点に使う較正後の実効雲量」。**値はヤマビヨリが採点に使う実効雲量(予報の雲量を過去の的中率で直した較正後の値)**。README「スコア」の表は「雲量 … 実効雲量」と「雲量」の名前で書いている。答えには「較正」と書かない(資料の Markdown の注にだけある) |
| `cloud_pct_raw` | 山頂雲量(予報そのまま) | % | 1 % の刻み | 同「右が予報そのままの山頂雲量」 |
| `ridge_visibility` | 視程(稜線) | m | 「約○ km」(1 km の刻み) | `print_ranking_table()` の列「視程m(稜線)」 |
| `precip_wet_pct` | 雨天割合(活動時間) | % | 1 % の刻み | 同「雨天割合%(活動時間)」・README「活動時間中の雨天割合」 |
| `day_total_precip_mm` | 降水量(全日) | mm | 1 mm の刻み | 同「降水量mm(全日)」 |
| `chill` | 体感温度(稜線) | ℃ | 1 ℃ の刻み | 同「体感温度℃(稜線)」 |
| `cape` | 雷リスク(CAPE) | J/kg | なし | 同「雷リスクCAPE」・README「雷(CAPE)」 |

- 答えに出る名前は、ヤマビヨリの README・手順書・画面の列名にある言い方だけを使う。範囲の外になる言い換えはしない(候補は `docs/stage2-finish-report.md` 5 章)。
  「山頂雲量(予報そのまま)」「雷リスク(CAPE)」は、分かりやすい言い方が README にないので今のまま。
- 「約」の表記(丸め)は `brief` だけが作る(四捨五入。AI は丸めない)。丸めの刻みは仮置き。
- 70 点未満の山(簡易行)は `evidence` が空なので、点数と危険信号の段階(種類なし)だけを持つ。

## 出していない値

| 値 | 理由 |
|---|---|
| `precip_wet_hours`・`precip_total_hours`・`precip_msm_hours`・`precip_moist_hours`・`precip_prob_hours` | 雨天割合の内訳(どの規則で雨と数えたか。README 探索モードの `M`/`湿n`/`確n` の説明)。画面ではセルの中の記号で、答えに使う名前と単位の出典がない |
| `precip_total_mm` | 雨天割合のセルに添える量(`report` の `mm_tag`)。列の名前がない。全日の量は `day_total_precip_mm` を出す |
| 提案の `details`(`native_row`・`cells` など) | スキーマ `biyori-proposal/1` が「窓口は根拠として使わない」としている |
| 提案の `constraints[].text` | 簡易行は「種別はネイティブの簡易行にない」のような内部の言い方。文は `brief` が段階の語から作る |
| 確信度 | 探索モードは出力しない(提案の `uncertainty.confidence.value` は null) |

## 決まった文(`lines`)

| 文 | 中身 | 出典 |
|---|---|---|
| `data_time` | 「山の予報は 11月22日(日) 7:32 時点のものです(気象庁 MSM は … の回、ECMWF は … の回)。」棚が `collect.stale_after_hours`(12 時間)以上古いときは「… 時点のもので、○ 時間前の古い予報です」。前回のファイルを残した回(`kept_previous`)はその旨を足す | 棚の `manifest.json` の `agents.yamabiyori.data_time`・`model_runs` |
| `coverage` | 「山は、ヤマビヨリの 76 座のうち 76 座を調べた予報です。」`incomplete` や取れなかった山があるときは「… 座だけを調べた予報です(調べられなかった山があります)。」 | 同 `coverage` |
| `lead_time` | 「11月29日(日)は 7 日先の予報です。ヤマビヨリが山頂の値として信用してよいとしているのは 3 日先までなので、傾向として読んでください。」(対象の日が `data_time` の日から 4 日以上先のとき) | README「精度と限界」「3日前までは山頂の値として信用してよく…14日表示は『傾向』として読む」。境界の日数は `collect/yamabiyori.py` の `RELIABLE_UP_TO_DAYS`(3) |
| `hazards` | 「11月22日(日)の権現岳は、危険信号が出ています: 強風危険(6時に16.4 m/s)・低体温症危険(体感 -24.2℃)。」危険信号のある事実ごとに 1 文 | 段階の語(注意・警戒・危険)と種類(雷・強風・低体温症)は README「危険信号はスコアに混ぜない…注意 / 警戒 / 危険の3段階で別枠表示」、括弧の中の形は `mountain_weather_mvp.py` の `hazard_warning_cell()`(「雷注意(CAPE580)」「強風危険(06時16.4m/s)」「低体温症危険(体感-24.2℃)」)。装備などの注意の中身は足さない |
| `hazard_note` | 「危険信号は、点数とは別に出る警告です。」資料に危険信号つきの山が 1 つでもあれば入る。答えに危険信号の文が 1 つでもあれば 1 回入れる(照合 `hazard_note_missing`) | README「危険信号はスコアに混ぜない」 |
| `attribution` | 「気象データ: Weather data by Open-Meteo.com(CC BY 4.0)。元の予報は気象庁 MSM と ECMWF IFS で、ヤマビヨリ 1.10.1 が山頂の標高に合わせて計算した値です。」 | `collect/ATTRIBUTION.md`(棚の `ATTRIBUTION.md`)・README の出典と利用条件 |

## その日の順位

| 項目 | 中身 |
|---|---|
| `day_rank`・`day_rank_ties` | その日の順位(対象の日・直線 250km 以内・地域で絞った、基準点以上の山の中)と、その順位の山の数。**同点は同じ順位**(100 点が 5 座なら 5 座とも 1 位、次は 6 位)。書いてよい表記は「1位(同点 5 座)」。同点がなければ「1位」「1番目」 |
| `rank` | 並び順の番号(1, 2, 3…。点数 → 危険信号の軽さ → 距離 → 山の ID の順)。答えには書かない |

## 比べた結果(`comparisons`。印 `[C1]`〜)

日ごとに、主役の枠の山(`selected_by` が `top`)の中だけで比べる。枠の山が 2 座に満たない日・値のない山がある日・いちばんの山が 2 つ以上ある日は作らない。対象は仮置き(増やすのは、実際の質問を見てから)。

| `kind` | 書いてよい言い方 | 比べる値 |
|---|---|---|
| `ridge_wind_min` | 主役の候補の中で稜線の風がいちばん弱い | `ridge_wind_ms`(小数のまま) |
| `nearest` | 主役の候補の中で横浜(出発地)からいちばん近い | 出発地からの直線距離(0.1km) |

## 主役にできない山

- 点数が基準(70 点。`collect/yamabiyori.py` の `GO_THRESHOLD`、README「行ける」の目安)未満。
- 危険信号が「警戒」「危険」(簡易行は「警戒以上」)。段階の語はヤマビヨリの `report_data.py` の `hazard_class()`(警戒・危険を含むと warning)と `mountain_weather_core.py` の `HAZARD_LEVELS`。
- 「注意」の山は主役にしてよい。すすめるときは `hazards` の文を必ず入れる(照合が止める)。
