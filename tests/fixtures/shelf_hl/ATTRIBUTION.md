# 出典と利用条件

この棚(`data` ブランチ)のファイルは、ビヨリコンシェル(個人利用・非商用)が GitHub Actions で自動取得したものです。

## 山の予報(`yamabiyori/`・`proposals/yamabiyori.json`)

- 計算: [ヤマビヨリ](https://github.com/ktakemaru/yamabiyori)(MIT)。取得した commit は `manifest.json` の `agents.yamabiyori.commit`。
- 気象データ: Weather data by [Open-Meteo.com](https://open-meteo.com/)([CC BY 4.0](https://open-meteo.com/en/licence))。
  無料 API は[利用規約](https://open-meteo.com/en/terms)により非商用に限る。元データは気象庁 MSM(気象庁の利用条件)と ECMWF IFS(CC BY 4.0)。
  雲量・降水・風などはヤマビヨリが山頂標高へ補間・加工した値であり、元の予報値そのものではない。
- 地形: 出典: 国土地理院 (地理院タイル 標高タイル, cyberjapandata.gsi.go.jp)(ヤマビヨリ同梱の `terrain_profiles.json` の元データ。実行時には取得しない)。

## 星空(`hoshibiyori/`・`proposals/hoshibiyori.json`)

出典の表記は、ホシビヨリ 1.2.0 の README「データ出典と利用上の注意」(確認日 2026-10-24)から写したものです。

- 計算: [ホシビヨリ](https://github.com/ktakemaru/hoshibiyori)(MIT)。取得した commit は `manifest.json` の `agents.hoshibiyori.commit`。
- 気象データ: Weather data by [Open-Meteo.com](https://open-meteo.com/)([CC BY 4.0](https://open-meteo.com/en/licence))。無料 API は[利用規約](https://open-meteo.com/en/terms)により非商用に限る。
  元データは気象庁 MSM(気象庁の利用条件)と ECMWF IFS(CC BY)。雲量は、ホシビヨリが観測者より上の雲(視界遮蔽雲量)に加工した値です。
- 地形地平線: 出典：国土地理院 地理院タイル(標高タイル)を加工して作成(ホシビヨリに入っているデータ。実行時には取得しない)。
- 光害: NASA Black Marble VNP46A4(DOI [10.5067/VIIRS/VNP46A4.002](https://doi.org/10.5067/VIIRS/VNP46A4.002))。手法は Duriscoe et al. 2018(CC BY)。ALR は日本で未較正の相対指数。
  推奨引用: NASA VIIRS Land Science Investigator-led Processing System. (2025). VIIRS/NPP Lunar BRDF-Adjusted Nighttime Lights Yearly L3 Global 15 arc second Linear Lat Lon Grid [Dataset]. NASA Level 1 and Atmosphere Archive and Distribution System Distributed Active Archive Center.
- 地点(名前・市町村・座標): © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)(Overpass API・Nominatim)。
  `hoshibiyori/*.json` と `proposals/hoshibiyori.json` の地点のデータは [ODbL 1.0](https://opendatacommons.org/licenses/odbl/) の条件に従います(ホシビヨリの `stargazing_spots.json` と同じ扱い)。
  この棚には OSM 由来の地点を含む全部の地点が入るので、ここでは全部に ODbL を書きます。コンシェルの答えでは、ホシビヨリの出力に地点の出どころ
  (`site_index[].origin`)があるとき、OSM 由来の地点(`viewpoint`・`curated+viewpoint`。出どころの無い地点を含む)を答えに使ったときだけ ODbL を書きます
  (出どころの無い出力では、いつも書きます。`docs/hoshibiyori-mapping.md` 6 章)。
- 天体位置: JPL DE421 暦([Skyfield](https://rhodesmill.org/skyfield/) 経由。利用条件は未確認)。

## 予報の回

どの回の予報か(気象庁 MSM・ECMWF の初期時刻)は、Open-Meteo のメタデータ(`/data/<model>/static/meta.json`)で取得の前後に確かめ、`manifest.json` の `model_runs` に記録しています。
