# ビヨリコンシェル(biyori-concierge)

ヤマビヨリ(山の天気)・ホシビヨリ(星空)・イキモノビヨリ(花・紅葉・野鳥)の 3 つを束ねて、
「今週末、何をするといい?」に 1 つのまとまった提案で答える窓口です。**作成中(段階 2: 山の予報だけで、質問から答えまで通せます)**。個人利用・非商用。

## 仕組み(段階 3 の時点)

- **取得の側**(`collect/`、GitHub Actions の `collect.yml`): ヤマビヨリ(`ktakemaru/yamabiyori` の main)を取り出して通常のコマンドで実行し、
  結果を `data` ブランチ(棚)に置きます。Open-Meteo への通信はここだけで、計測フック(`collect/measure/`)で
  許可ホスト以外への送信を止め、回数を数え、4xx/5xx で即中止します。429 だけは、ヤマビヨリが 1 分の上限で待って取り直せるよう、
  1 回の実行で 5 回(ヤマビヨリの `MINUTELY_RETRY_MAX`)まで通します。429 があった回は、全部の山がそろったときだけ成功とし、
  そろわなければ取り直さずに棚を前回のままにします。どの上限(1 日・1 時間・1 分)の 429 だったかも、種類ごとの回数だけを記録します(`http_429_kinds`)。定期実行はリポジトリの変数 `BIYORI_COLLECT_SCHEDULE` が `on` のときだけ動きます。
  山の ID(`m001`〜)は、ヤマビヨリの `MOUNTAINS` の `id` をそのまま使います(並び順では作りません。`id` の無い古いヤマビヨリは読めないとして止まります)。
- **答える側**(`concierge/`): 棚を読むだけで、Open-Meteo には通信しません(通信は `sync` の `git fetch origin data` だけ)。
  「資料 → AI が書く → 照合」の形で答えます: コード(`brief`)が質問のための資料(確かめた事実・決まった文・足りないもの)を作り、
  エージェントが資料だけを見てガイドとして下書きを書き、コード(`verify`)が資料と照らしてから送ります。段階 3 からは、星の興味の語を渡した質問で、昼の山と夜の星を一日の流れにまとめます(花・紅葉・野鳥は段階 4 から)。
  資料の候補は日ごとに、主役にできる山の枠(8 座)と、点数は基準以上だが危険信号が「警戒」「危険」の見送りの枠(3 座)で選びます
  (並びは 点数 → 危険信号の軽さ → 出発地からの直線距離。好みの仮置き。`config.yaml`)。見送りの山の危険信号は、日ごとのまとめの文 1 つで書きます。危険信号の注記は `verify` が正しい位置に置きます。

## 使い方(答える側)

手順と決まりの正本は `AGENTS.md`(Claude Code・Codex 共通)。Claude Code では、このフォルダで「今週末、登山に行くならどこ?」のように聞けば、
スキル `.claude/skills/biyori-concierge/` が `AGENTS.md` の手順で答えます。手で動かすときは:

```
python -X utf8 -m concierge sync                       # 棚(data ブランチ)を取り込む。失敗しても前回の写しを使う
python -X utf8 -m concierge status                     # 棚がいつ時点か・どの回か・何時間前か・何座のうち何座か
python -X utf8 -m concierge brief --question "今週末、登山に行くならどこ?" [--when 今週末|来週末|明日|YYYY-MM-DD|A..B] [--region 関東甲信] [--mountain 大菩薩嶺]...
python -X utf8 -m concierge verify <下書きのファイル> --brief <資料の id>   # 合格なら送る文。不合格なら理由(2 回まで直せる。3 回目は控えの文)
```

- 置き場は `BIYORI_CONCIERGE_DATA_DIR`(未設定なら Windows は `%LOCALAPPDATA%\biyori-concierge`)。棚の写し・資料・照合の記録が入ります。リポジトリの中には書きません。
- Claude Code では、`verify` を通さない答え・`verify` の文に足し引きした答えを Stop フックで止めます(`docs/stop-hook.md`。切るときは環境変数 `BIYORI_CONCIERGE_STOP_HOOK=off`)。
- 長い作業の前の予告の決まり(4 つのビヨリ共通の正本)は `docs/wait-notice.md`、コンシェルの実測の表は `AGENTS.md` §6。
- 資料の形は `schemas/biyori-brief.schema.json`、予報の値の名前と出典は `docs/brief-fields.md`、検査の一覧は `docs/answer-checks.md`、書き方の手本は `docs/answer-voice.md`、日付の規則は `docs/dates.md`、試験問題は `docs/qa.md`。

棚の形式は `schemas/biyori-shelf.schema.json`(manifest)ほか。対応表は `docs/yamabiyori-mapping.md`。

## テスト

```
python -m pip install -r requirements.txt
python -X utf8 -m unittest discover -s tests
```

テストはソケットを禁止して動き、実通信はしません。

## 出典と利用条件

- 気象データ: Weather data by [Open-Meteo.com](https://open-meteo.com/)([CC BY 4.0](https://open-meteo.com/en/licence))。無料 API は非商用に限ります。
  元データは気象庁 MSM・ECMWF IFS。山頂標高の値はヤマビヨリが加工したものです。
- 棚に置くファイルの出典は `collect/ATTRIBUTION.md`(棚では `ATTRIBUTION.md`)。

## ライセンス

MIT(`LICENSE`)。
