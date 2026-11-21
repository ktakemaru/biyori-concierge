# 2026-11-22 の見直しの報告: 指示書の改訂・山の ID・429 の扱い

作成日: 2026-11-22 / 作業指示: `docs/revise-20261122-instructions.md` / 作業フォルダ `C:\biyori-concierge`(commit まで。push・PR・マージは利用者)

## 1. 始める前の状態(第 0 部)

| 項目 | 結果 |
|---|---|
| 追跡中のファイルの未 commit の変更 | なし(`git status --porcelain --untracked-files=no` が空) |
| ブランチ | `main` |
| main の最新 | `36e4a028a6af99f266d10c7311afc87cf0ae2b6b` 2026-11-11 23:47:22 +0900「上限の値を利用者の決定に合わせる(時間 2700 秒、通信 450 のまま)」 |
| `origin/main`(手元の控え) | `36e4a028a6af99f266d10c7311afc87cf0ae2b6b`(main と同じ。未 push の commit なし) |
| 変更前のテスト | **141 件すべて成功**(Windows の手元、Python 3.13、約 65 秒) |
| ヤマビヨリ `C:/yamabiyori` | `fdadecea87a53cce4384c77d4bd1493400e0b52c` 2026-11-22 02:00:11 +0900(Merge PR #27)、版 1.10.1。`MOUNTAINS` に `id` あり(76 座、m001〜m076)。`MINUTELY_RETRY_MAX = 5`、`PACING_LIMIT_PER_MINUTE = 300.0` |
| ホシビヨリ `C:/hoshibiyori` | `73c1f43c0a5d8b3dd51663be4d9031bbbd50e61e` 2026-11-16 06:50:37 +0900(Fix/no terrain horizon #37)、版 1.1.0 |
| イキモノビヨリ `C:/ikimonobiyori` | `8d9a15e25d87f409c7538ae42e17839bb6af803d` 2026-11-15 11:44:20 +0900(Merge PR #70)、版 0.2.0(`plugin.json` に版が無く、`CHANGELOG.md` の先頭「0.2.0(2026-11-15。段階75〜85)」) |

止まる条件(1〜4)には当たりませんでした。

作業指示の 1 章「今の実物」との違い:

- テストの件数は、Windows の手元でも 141 件でした(違いなし)。
- イキモノビヨリには `.claude-plugin/plugin.json` が無いため、版は `CHANGELOG.md` から取りました。
- ヤマビヨリの `MOUNTAINS` の上のコメント(「Candidate mountain pool (75座…)」)は 75 座のままですが、要素は 76 個です(ヤマビヨリ側のコメントの古さ。動きには関係しません)。
- ほかは作業指示のとおりでした。

## 2. できたこと

### 第 1 部: 開発指示書の改訂(ブランチ `feature/revise-and-mountain-ids`、commit `ec8cad7`)

`docs/biyori-concierge-instructions.md` を作業指示 4.1〜4.11 のとおり直しました。章の番号と並びは変えていません。直した段落の行の終わりに「(2026-11-22 改訂)」を付け、12 章(改訂の記録)を足しました。`CHANGELOG.md` に項目を足しました。

- 作業指示の文から言い回しだけを変えたところ:
  - 4 章の突き合わせの項目にあった「5 章の第 2 部で実装」は、開発指示書の 5 章と取り違えないよう「2026-11-22 の見直しの第 2 部で実装。`docs/revise-20261122-instructions.md` 5 章」と書きました。
  - 5.2 の「429 の扱い」は、前の文(計測フックの項目の下にあった)から外し、5.2 の直下の項目にしました。
  - 6 章は置き換えたので、節の見出しと章の頭に改訂の印を付けました(行ごとには付けていません)。
- 直していない箇所: 4 章のファイルの一覧(`hoshibiyori/milkyway.json` の「7章 H1」)と、5.2 の星の行(「7 章 H1 の `--json-out`」)には「H1」が残っています。作業指示の 4.x に入っていないので、そのままにしました。H1 は 7 章に「済んだもの」として残っているので、意味は通ります。
- 9 章: `C:\mountain-weather-main` を `C:\yamabiyori` に直しました。ほかの文書で残っているのは `docs/collect-run4-analysis.md`(記録なので直していません)だけでした。

### 第 2 部: 山の ID を `MOUNTAINS` の `id` から読む(同じブランチ。commit `5c087a0`・`bbab979`・`2e03c21`)

- `collect/yamabiyori.py` の `load_mountains()`: 各要素の `id` をそのまま使います。次のときは `ValueError` になり、呼び出し側では `mountains_unreadable` として扱います(子プロセスを起動する前に分かります)。
  - `id` が無い(古い版のヤマビヨリ)。
  - 文字列でない。
  - `m` + 数字 3 桁の形でない。
  - 重なっている。

  並び順で作る形に戻す道は作っていません。
- `u001` の形は今は通していません。ヤマビヨリの `AGENTS.md` には「利用者が自分で足す山は `u` で始める(例 `u001`。その仕組みはまだ無い)」とあります。一方、棚のスキーマ `schemas/biyori-mountains.schema.json` の `id` は `^m\d{3}$` です。→ 6 章「決めてほしいこと」。
- 突き合わせ(`convert()`):
  - 行に `id` があれば、山の一覧の同じ `id` で引きます。
  - 行に `id` が無い・`null` のときだけ、名前と標高で引きます。
  - 行の `id` が一覧に無いとき、または `id` で引いた山の名前が行と違う(ID のずれ)ときは、提案にしません。理由を `diagnostics.warnings` に書きます。
  - 提案の `id`・`place.site_ref`・`details.mountain_id` の形は変えていません。
- 見本: `tests/fixtures/yamabiyori/mountain_weather_core.py` の 76 座に、`C:/yamabiyori` の実物と同じ `id` を足しました。並び順では付けず、名前と標高で引いて付けました。結果は並び順とも一致しました。座標などは `b018355` のままです(日の出・日没の見本のファイル名が座標によるため)。`tests/fixtures/yamabiyori/explore.json` は古い形(行に `id` なし)のまま残しています。
- `docs/yamabiyori-mapping.md`(1 章と `place.lat` などの行)、`schemas/biyori-mountains.schema.json` の説明の文、`README.md`、`CHANGELOG.md` を直しました。
- 実物の確かめ(読むだけ): `load_mountains("C:/yamabiyori")` が 76 座・m001〜m076 を返しました。

## 3. テストの結果

`python -X utf8 -m unittest discover -s tests`(Windows の手元、Python 3.13)

| 時点 | 件数 |
|---|---|
| 変更前 | 141 件すべて成功 |
| 第 2 部のあと | **152 件すべて成功**(+11) |

足したテスト(`tests/test_mountain_ids.py`):

- `LoadMountains`(6 件)
  - `test_ids_come_from_the_list_not_from_the_order`
  - `test_fixture_ids_are_the_real_ones`
  - `test_missing_id_is_refused`
  - `test_bad_id_forms_are_refused`
  - `test_duplicate_id_is_refused`
  - `test_unreadable_before_any_request`
- `MatchById`(5 件)
  - `test_rows_with_ids_give_the_same_proposals_as_name_matching`
  - `test_id_decides_the_mountain`
  - `test_name_mismatch_is_not_a_proposal_and_warns`
  - `test_unknown_id_is_dropped_not_matched_by_name`
  - `test_null_id_falls_back_to_name_and_elevation`

既存のテストの期待値は変えていません(`tests/test_yamabiyori.py` の `m001` 谷川岳・`m002` 八ヶ岳(赤岳) などは、見本に `id` を足したあともそのまま通りました)。

## 4. 確かめられていないこと

- 行に `id` が入ったヤマビヨリ 1.10.x の本物の `--json-out` は、まだ通していません。ヤマビヨリ側の記録済みの見本(`tests/fixtures/report/explore.json`)も行に `id` が無い古い形なので、テストでは見本に `id` を足して確かめました。→ 5 章の手動実行で確かめます。

## 5. 利用者がやること

第 3 部(`feature/hook-tolerate-429`)の結果と合わせて、この下に書き足します。

## 6. 利用者に決めてほしいこと

- **利用者が足す山の ID(`u001`〜)を、コンシェルでも通すか。** 今は `m` + 数字 3 桁だけを通します(棚のスキーマと同じ)。ヤマビヨリに `u` の山を足す仕組みができたときに、スキーマと `load_mountains()` を一緒に広げるのがよいと考えます。
