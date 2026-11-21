"""答える側(PC で動く)。棚(data ブランチ)の写しを読むだけで、Open-Meteo には通信しない(指示書 3 章・6 章)。
通信は `sync` が行う「自分のリポジトリの data ブランチの取り込み」(git fetch origin data)だけ。
collect/ のうち通信しない部品(collect.common の設定・スキーマの検査、collect.shelf のファイルの検査、collect.yamabiyori の定数)は使う。
通信する部品(collect.runner・collect.meta_fetch・collect.run・collect.diag_probe)は import しない(テストで検査する)。"""
