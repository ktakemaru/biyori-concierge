# ビヨリコンシェル(biyori-concierge)

ヤマビヨリ(山の天気)・ホシビヨリ(星空)・イキモノビヨリ(花・紅葉・野鳥)の 3 つを束ねて、
「今週末、何をするといい?」に 1 つのまとまった提案で答える窓口です。**作成中(段階 1)**。個人利用・非商用。

## 仕組み(段階 1 の時点)

- **取得の側**(`collect/`、GitHub Actions の `collect.yml`): ヤマビヨリ(`ktakemaru/yamabiyori` の main)を取り出して通常のコマンドで実行し、
  結果を `data` ブランチ(棚)に置きます。Open-Meteo への通信はここだけで、計測フック(`collect/measure/`)で
  許可ホスト以外への送信を止め、回数を数え、429 で即中止します。定期実行はリポジトリの変数 `BIYORI_COLLECT_SCHEDULE` が `on` のときだけ動きます。
- **答える側**(`concierge/`): 段階 2 から。棚を読むだけで、Open-Meteo には通信しません。

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
