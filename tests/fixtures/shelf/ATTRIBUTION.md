# 出典と利用条件

この棚(`data` ブランチ)のファイルは、ビヨリコンシェル(個人利用・非商用)が GitHub Actions で自動取得したものです。

## 山の予報(`yamabiyori/`・`proposals/yamabiyori.json`)

- 計算: [ヤマビヨリ](https://github.com/ktakemaru/yamabiyori)(MIT)。取得した commit は `manifest.json` の `agents.yamabiyori.commit`。
- 気象データ: Weather data by [Open-Meteo.com](https://open-meteo.com/)([CC BY 4.0](https://open-meteo.com/en/licence))。
  無料 API は[利用規約](https://open-meteo.com/en/terms)により非商用に限る。元データは気象庁 MSM(気象庁の利用条件)と ECMWF IFS(CC BY 4.0)。
  雲量・降水・風などはヤマビヨリが山頂標高へ補間・加工した値であり、元の予報値そのものではない。
- 地形: 出典: 国土地理院 (地理院タイル 標高タイル, cyberjapandata.gsi.go.jp)(ヤマビヨリ同梱の `terrain_profiles.json` の元データ。実行時には取得しない)。

## 星空(`hoshibiyori/`。段階 3 から)

- 計算: [ホシビヨリ](https://github.com/ktakemaru/hoshibiyori)。気象データは上と同じ Open-Meteo(CC BY 4.0)。
- 光害: NASA Black Marble VNP46A4(DOI 10.5067/VIIRS/VNP46A4.002)。手法は Duriscoe et al. 2018(CC BY)。
- その他の出典はホシビヨリの README「データの出典」に従う。

## 予報の回

どの回の予報か(気象庁 MSM・ECMWF の初期時刻)は、Open-Meteo のメタデータ(`/data/<model>/static/meta.json`)で取得の前後に確かめ、`manifest.json` の `model_runs` に記録しています。
