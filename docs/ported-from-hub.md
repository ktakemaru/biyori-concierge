# biyori-hub から写したもの

`C:\biyori-hub`(ktakemaru/biyori-hub)は読み取り専用で参照した。写した時点の hub の HEAD は `694371c3916677027314e4eb6229fa3559ae8c66`。
下の「commit」は、そのファイルを最後に変えた hub の commit(写した版)。

## そのまま写したもの(内容は同じ)

| このリポジトリ | hub での場所 | commit | 用途 |
|---|---|---|---|
| `collect/measure/sitecustomize.py` | `hub/measure/sitecustomize.py` | `9f324bf8d5e102c3420b461b35e2f5d851fbcef7` | 通信の計測フック。許可ホスト以外は送信前に止める・回数を数える・4xx/5xx(429 を含む)で即中止・記録先が書けなければ通信前に止める |
| `schemas/biyori-proposal.schema.json` | `schemas/biyori-proposal.schema.json` | `7ad88b09fd8207a208315d3f91fb2efce5cca8e2` | 提案の契約(biyori-proposal/1) |
| `schemas/biyori-vocabulary.yaml` | `schemas/biyori-vocabulary.yaml` | `6019ed233bfc391c10eae406e7c7918af11c3b8e` | 興味の語(段階 2 から使う) |

## 書き直して写したもの(考え方・一部のコードを使い、形を変えた)

| このリポジトリ | 元 | commit | 変えたところ |
|---|---|---|---|
| `collect/yamabiyori.py` の `convert()` と下まわり | `adapters/yamabiyori_adapter.py` の `convert()` | `6940b27a826ca0e49badbac9a01fc4d532ec5ed2` | explore だけにした(diagnosis は棚に載せない)。提案の `id` を山名から山の ID(`m002` など)に変えた。`site_ref` は全件に付ける(ID が MOUNTAINS の並びから決まるため)。`data_as_of` に取得の終了時刻と予報の回を入れた(hub では空だった)。危険信号に `hazard`・`level` の項目を足した(項目の追加のみ)。取得ができなかった山があれば `partial`。vendor・runtime・livegate の仕組みは持ち込まない |
| `collect/yamabiyori.py` の `load_sun_times()` | `adapters/yamabiyori_suntimes.py` | `102700e209e0f97b5ffba6733f5a580e95e6145d` | 1 つの関数にまとめた。読む場所は Actions で取り出したヤマビヨリの `cache/` |
| `collect/yamabiyori.py` の `load_mountains()` | `adapters/yamabiyori_adapter.py` の `load_mountains()` | `6940b27a826ca0e49badbac9a01fc4d532ec5ed2` | ID(`m001`〜。並び順の 1 始まり)を付ける |
| `docs/yamabiyori-mapping.md` | `docs/yamabiyori-mapping.md` | `b3c967c691a5bd9e78e022575dd8b1cfc92deab6` | 上の変更に合わせた |
| `collect/shelf.py`(棚の組み立て) | `hub/cloud_data.py` の prepare | `97e678cacb25cfcb43870a46f58263b7b2a3c5ae` | 考え方(許可リストのファイルだけ取り込む・シンボリックリンクを拒否・出力先は空)だけ使い、中身は新しく書いた。台帳・スナップショットの世代管理はない。ビヨリごとに「成功したら入れ替える」 |
| `.github/workflows/collect.yml` の publish ジョブ | `.github/workflows/fetch-autumn.yml` の publish ジョブ | `73e8a4de0e41844d9342785a4d3ba9d5938496a8` | 親なしの 1 コミットを `data` にだけ強制 push する部分は同じ。`git add -A` をやめて、置いてよい名前だけを add する |
| `tests/nonet.py` | `tests/nonet.py` | `7ad88b09fd8207a208315d3f91fb2efce5cca8e2` | hub 固有の環境変数(BIYORI_UNDER_TEST など)を外した |
| `tests/fixtures/net_probe.py` | `tests/fixtures/stage11/agents/netbiyori/net_proposal.py` | `6940b27a826ca0e49badbac9a01fc4d532ec5ed2` | 引数を減らし、回数(`--times`)を足した |
| `tests/test_hook.py` | `tests/test_stage11_phase2.py`(`0ff696f`)・`test_stage10_phase3.py`(`9f324bf`)・`test_stage9b.py`(`97e678c`)・`test_stage5a.py`(`73e8a4d`)のフックの部分 | 左のとおり | hub の他の部品(snapshotter など)に頼らない形にした |
| `requirements.txt` | `requirements-hub.txt` | `846bc2b932a6170492a91db7dc3e315897aa761a` | 答える側・取得の側に要るもの(jsonschema・PyYAML とその依存)だけ。requests は入れない |

## まだ写していないもの(段階 2 で写す)

| hub での場所 | 用途 |
|---|---|
| `hub/core/dates.py`(`97e678c`)・`docs/dates.md`(`102700e`) | 「今週末」「来週末」の計算(答える側の `--when`) |
| `adapters/hoshibiyori_transform.py`・`docs/hoshibiyori-mapping.md` | 星の変換(段階 3。入力の形は H1 に合わせて直す) |

## 写さなかったもの(指示書 3.2)

`snapshotter`・台帳・`scheduled_run`・`concierge_v0`・`concierge_skill`・`hub/core/checktext.py`・イキモノビヨリの古い手順。

## ほかのリポジトリから(参照・写し)

| このリポジトリ | 元 | commit | 用途 |
|---|---|---|---|
| `tests/fixtures/yamabiyori/explore.json` | ヤマビヨリ `tests/fixtures/report/explore.json` | `04de59d44e81ac780fd3faaa34e46af7e846402e` | 記録済みの入力(そのままの写し) |
| `tests/fixtures/yamabiyori/mountain_weather_core.py` | ヤマビヨリ `mountain_weather_core.py` の `MOUNTAINS`(88〜173 行) | `b0183552217c9dc116547c272f3b4192f44f6ea0` | 山の一覧を ast で読むテスト(データの部分だけ。コードは写していない) |
| `tests/fixtures/yamabiyori/.claude-plugin/plugin.json` | ヤマビヨリ `.claude-plugin/plugin.json` | `b0183552217c9dc116547c272f3b4192f44f6ea0` | 版(1.9.0)を読むテスト |
| `tests/fixtures/meta/before.json` | yamabiyori-backtest `data/snapshots/forecast/2026-09-24/06Z_meta_before.json.gz` の一部の項目 | `964293a9ff0e69bae222b0701b26aa457669cd99` | 予報の回の読み取りのテスト |
| `collect/meta_fetch.py` | yamabiyori-backtest `backtest/collect_forecast_snapshot.py` の `fetch_metadata`(手本。コードは写していない) | `964293a9ff0e69bae222b0701b26aa457669cd99` | 取得の前後に meta.json を読む |

`tests/fixtures/yamabiyori/mountain_weather_mvp.py`(偽のヤマビヨリ)と `tests/fixtures/yamabiyori/cache/`(日の出・日没)はテスト用に新しく作ったもので、本物のデータではない。
