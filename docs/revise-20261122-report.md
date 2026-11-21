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
| イキモノビヨリ `C:/ikimonobiyori` | `8d9a15e25d87f409c7538ae42e17839bb6af803d` 2026-11-15 11:44:20 +0900(Merge PR #70)、版 0.2.0(`.claude-plugin/plugin.json` が無いため、`CHANGELOG.md` の先頭「0.2.0(2026-11-15。段階75〜85)」) |

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
- あとから足した commit: `docs/ported-from-hub.md` の `load_mountains()`・`convert()` の行に「並び順の 1 始まり」が残っていたので直しました(`1e18dc8`)。**このブランチの最後の commit は `1e18dc8`** です。

### 第 3 部: 計測フックが 429 を決まった回数まで通す(ブランチ `feature/hook-tolerate-429`。上のブランチの先頭 `1e18dc8` から作成。commit `a60fbba`・`0bda77f`・`3a13dda`、最後はこの報告書の追記)

- **フック** `collect/measure/sitecustomize.py`
  - 環境変数 `BIYORI_HTTP_429_MAX_TOTAL` を足しました。1〜10 の整数のときだけ有効で、上の限りの 10 は仮置きです。
  - 渡された子プロセスだけ、429 を実行全体でその回数まで通します。通した 429 の記録には `rate_limit_tolerated: true` を付けます。
  - 回数を超えた 429 は即中止します。理由の文は「HTTP 429(429 を通す回数の上限 N 回を超えた)」です。
  - 未設定なら今までどおり、429 は 1 回で即中止します。不正な値・0 以下・10 を超える値は無効にし、標準エラーに 1 行出します。
  - `_RETRYABLE` は 502/503/504 のままです(`test_429_is_never_tolerated_even_if_opted_in` はそのまま通ります)。
  - ほかの 4xx/5xx、許可ホスト、件数の上限、壁時計の検査は変えていません。
  - 先頭の説明と `docs/ported-from-hub.md`(「写したあとに変えたもの」の節)に書きました。
- **取得の側**
  - `config.yaml` の `collect.agents.yamabiyori.http_429_max_total: 5` を足しました。出典は `C:/yamabiyori` の `MINUTELY_RETRY_MAX = 5` で、実物の値も 5 でした。
  - `run_hooked(..., max_429=)` が、この値を `BIYORI_HTTP_429_MAX_TOTAL` として渡します。設定が無い・0 なら渡しません。親の環境の同じ名前の変数は捨てます(今の `BIYORI_*` と同じ)。
  - メタデータの取得と診断には渡しません(今までどおり)。
- **判定**
  - 429 があった回は、次の 4 つがそろったときだけ `ok` にします(待って取り直せた回)。
    - フックに止められていない。
    - 終了コード 0。
    - 出力が正しい。
    - `fetched` = `pool_size`。
  - それ以外は `rate_limited` で、取り直しの回は始めません。そのビヨリは今までどおり `kept_previous` です。
  - 設定が無いときは、今までどおり 429 があれば `rate_limited` です。
- **429 の回数**
  - 次の 2 つを足しました。
    - `http_429`: その回の 429 の回数。
    - `http_429_tolerated`: フックが通した回数。
  - 書く場所: run.json(ビヨリごと・`attempts[]` ごと)、manifest、`logs/requests.json` のビヨリごとの集計。成功した回でも残します。
  - スキーマ `biyori-collect-run`・`biyori-shelf`・`biyori-request-log` は項目を足しただけです。版の番号は上げていません。
- **まとめの文**: 「429」の行を、回数と結果が分かる文にしました(`collect/shelf.py` の `rate_limit_text`)。
  - 例: 「429: yamabiyori 2 回(待って取り直し、全座そろった)」「429: yamabiyori 1 回(rate_limited。取り直しの回は始めず、棚は前回のまま)」。
  - 429 が無ければ今までどおり「429: なし」です。
- **時間の上限**: 65 秒 × 5 回 = 325 秒は、時間の上限 2700 秒の内側に収まります。値は変えていません。
- **文書**: `README.md`・`CHANGELOG.md` を直しました。`collect/runner.py`・`collect/run.py`・`collect/diag_probe.py`・`collect/meta_fetch.py` の説明の文も直しました(メタデータの取得と診断は、通す設定を渡さないので今までどおり、と書きました)。

止まる条件 5 には当たりませんでした。設定を入れたあとも、既存のテストは書き換えずにすべて通りました。

## 3. テストの結果

`python -X utf8 -m unittest discover -s tests`(Windows の手元、Python 3.13)

| 時点 | 件数 |
|---|---|
| 変更前 | 141 件すべて成功 |
| 第 2 部のあと | **152 件すべて成功**(+11) |
| 第 3 部のあと | **165 件すべて成功**(+13) |

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

足したテスト(第 3 部。`tests/test_rate_limit.py`):

- `Hook`(6 件)
  - `test_without_the_variable_429_still_aborts_at_once`
  - `test_two_are_tolerated_and_the_third_aborts`
  - `test_invalid_or_too_large_values_are_ignored`
  - `test_other_statuses_are_unchanged`
  - `test_runner_passes_the_value_and_drops_the_parents`
  - `test_config_value_comes_from_yamabiyori`
- `Collect`(5 件)
  - `test_429_then_every_mountain_is_ok_and_counted`
  - `test_429_and_missing_mountains_is_rate_limited_without_another_run`(子プロセスの起動が 1 回だけ)
  - `test_more_than_allowed_is_stopped_by_the_hook`
  - `test_without_the_setting_it_behaves_as_before`
  - `test_429_in_a_retry_that_completes_is_ok`
- `Shelf`(2 件)
  - `test_ok_run_with_429_keeps_the_count_everywhere`
  - `test_rate_limited_run_keeps_the_previous_files`

偽のヤマビヨリ(`tests/fixtures/yamabiyori/mountain_weather_mvp.py`)に、`rl<k>ok`・`rl<k>partial` の形を足しました。429 を k 回受けたあと、ok か partial の出力を書く形です。今の形は変えていません。

既存のテストの期待値は変えていません。
- 第 2 部: `tests/test_yamabiyori.py` の `m001` 谷川岳・`m002` 八ヶ岳(赤岳) などは、見本に `id` を足したあともそのまま通りました。
- 第 3 部: 作業指示 6.6 の例外(「429 を通さない設定」を渡す変更)を使ったテストは**ありません**。
  - `tests/test_retry.py` は自分の設定(`http_429_max_total` なし)を渡すので、今までの動きのまま通りました。
  - `tests/test_collect_run.py`・`tests/test_shelf.py` は `config.yaml` の値(5)で動きます。それでも通りました。偽のヤマビヨリの `429` の形は、フックの中止の記録を書いて終わるので、判定は今までどおり `rate_limited` になるためです。

## 4. 確かめられていないこと

- **本物の 429(U9)**: フック・ヤマビヨリ・取得の側の判定が設計どおりに動くかは、テスト(偽のヤマビヨリと、フックの関数の単体)でしか確かめていません。本物の 429 が出た回の記録で確かめる必要があります。
- **ヤマビヨリが 1 回の実行で受けうる 429 の回数**: ヤマビヨリ(`mountain_weather_core.py` の `get_with_retry`)は通信を 1 本ずつ行います。1 分の上限の 429 では、5 回まで 65 秒待って取り直し、6 回目の 429 で探索をやめます。フックの回数を 5 にしたので、6 回目の 429 はヤマビヨリがやめる前にフックが止めます(終了コード 75)。どちらでも判定は `rate_limited` で同じなので、5 のままにしました(作業指示どおり)。
- **ヤマビヨリ 1.10.x の全 76 座の所要時間と通信の回数(U8)**: ヤマビヨリが通信の間隔を調整するようになってからは、まだ実測していません。時間の上限 2700 秒・通信の上限 450 のままでよいかは、下の手順 3 の結果で決まります。
- **行に `id` が入った本物の `--json-out`**: まだ通していません。ヤマビヨリ側の記録済みの見本(`tests/fixtures/report/explore.json`)も、行に `id` が無い古い形です。テストでは見本に `id` を足して確かめました。→ 下の手順 2・3 で確かめます。
- **仮置きの値**: フックの上の限り `_429_CAP = 10`。暴走を止める安全弁としての値で、出典はありません。

## 5. 利用者がやること

### 1. 2 つのブランチを push する(この Claude Code のウィンドウ)

1. 入力欄に `! git push -u origin feature/revise-and-mountain-ids` と打って Enter。
2. 続けて `! git push -u origin feature/hook-tolerate-429` と打って Enter。
3. 成功の見分け方:
   - どちらも最後に `branch '…' set up to track 'origin/…'` と出て、エラーが無い。
   - ブラウザの GitHub で **Actions** タブを開くと、**tests** の実行が 2 つ(ブランチごと)あり、`unittest (ubuntu-24.04)` と `unittest (windows-latest)` が緑のチェックになる。

### 2. `feature/hook-tolerate-429` のブランチから、山 3 座・publish なしで実行する(ブラウザの GitHub)

collect.yml は手動実行のときに、使うブランチを選べる作りです。入力やジョブの条件に、ブランチの制限はありません。

1. リポジトリの **Actions** タブ → 左の一覧で **collect** → 右上の **Run workflow** ボタン。
2. 開いた欄で、次のように入れる。
   - **Use workflow from**: `Branch: feature/hook-tolerate-429` を選ぶ。
   - `confirm`: `yes-run-live`
   - `agents`: `yamabiyori`
   - `yama_limit`: `3`
   - `yamabiyori_ref`: `main`
   - `publish`: **チェックを外したまま**
3. 緑の **Run workflow** を押す。
4. 成功の見分け方: 実行を開き、collect ジョブが緑で、publish ジョブが skipped になっていること。collect の Summary は次のとおりになっていること。
   - 表の yamabiyori の状態が `ok`。
   - 山が「3座のうち3座(全76座の先頭3座)」。
   - 「ヤマビヨリの取り出し」の commit が、実行した時点のヤマビヨリ main の commit(2026-11-22 時点では `fdadece…`)。
   - 「429: なし」(または「429: yamabiyori N 回(待って取り直し、全座そろった)」)。
   - 「止められたホスト: なし」。

**注意**: ブランチから実行するときは、`publish` にチェックを入れないでください。今の collect.yml は、ブランチから実行しても publish ジョブが動く作りです(ワークフローは変えていません)。

### 3. 同じブランチから、全 76 座・publish なしで実行する(U8)

1. 手順 2 と同じ画面で、`yama_limit` だけ `all` にして **Run workflow**(ほかは同じ。publish はチェックなし)。
2. 実行が終わったら、collect の Summary から次を控えて、次の作業のときに伝えてください。
   - 表の yamabiyori の「所要(秒)」。
   - 「通信: 合計 … 件」。
   - 「429:」の行。
   - 回の表(取り直しがあったか)。
3. 成功の見分け方: yamabiyori が `ok` で「76座のうち76座」。
   - `incomplete` のとき: 欠けた山があったことを意味します。回の表と `retry_stop` を控えてください。
   - `rate_limited` のとき: 「429:」の行を控えてください。

### 4. PR を作ってマージする(ブラウザの GitHub)

- 手順 2・3 に問題がなければ: **Pull requests** → **New pull request** で、base `main` ← compare `feature/hook-tolerate-429` の PR を 1 本作り、tests が緑なのを見て **Merge pull request** を押す。このブランチは第 1 部・第 2 部を含むので、PR は 1 本でよいです。
- 第 3 部に問題があれば: base `main` ← compare `feature/revise-and-mountain-ids` の PR だけを作ってマージする。
  - このブランチの報告書は第 0〜2 部の分だけです。
  - 第 3 部の分は `feature/hook-tolerate-429` に残ります。この手順(5 章)も、`feature/hook-tolerate-429` の報告書にだけあります。

### 5. main から、全 76 座・publish ありで実行する(ブラウザの GitHub)

1. **Actions** → **collect** → **Run workflow** で、次のように入れて実行する。
   - **Use workflow from**: `Branch: main`
   - `confirm`: `yes-run-live`
   - `agents`: `yamabiyori`
   - `yama_limit`: `all`
   - `yamabiyori_ref`: `main`
   - `publish`: **チェックを入れる**
2. 成功の見分け方: collect と publish の両方が緑。
3. 棚の確かめ方(ブラウザ):
   1. リポジトリの **Code** タブで、ブランチの選択を `data` にする。
   2. `manifest.json` を開き、`agents` → `yamabiyori` → `version` が `"1.10.1"`、`commit` が実行した時点のヤマビヨリ main の commit(2026-11-22 時点では `fdadece` で始まる)であること、`status` が `"ok"` であることを見る。
   3. 429 があった回なら、同じ所に `http_429` の回数が出ます。
   4. `yamabiyori/mountains.json` を開き、`"count": 76`、`mountains` の最初の `id` が `"m001"`(谷川岳)、最後が `"m076"` であることを見る。`id_rule` が「MOUNTAINS の各要素の id をそのまま…」になっていること。

## 6. 利用者に決めてほしいこと

- **利用者が足す山の ID(`u001`〜)を、コンシェルでも通すか。** 今は `m` + 数字 3 桁だけを通します(棚のスキーマと同じ)。ヤマビヨリに `u` の山を足す仕組みができたときに、スキーマと `load_mountains()` を一緒に広げるのがよいと考えます。
- **フックが受け付ける回数の上の限り(仮置き 10)をそのままにするか。** 今の設定(5)の 2 倍です。ホシビヨリの取得(段階 3)で、待つ回数の定数が 10 を超えるようなら見直しが要ります。
