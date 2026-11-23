"""取得の側(GitHub Actions で動く)。Open-Meteo への通信は、計測フックを付けた子プロセスの中だけで起きる。
答える側(concierge/)は、このパッケージのうち通信しない部品だけを使う:
collect.common(ROOT・SCHEMAS・config・schema_errors)、collect.shelf(AGENT_FILES・agent_files_problems)、
collect.yamabiyori の定数(GO_THRESHOLD・HAZARD_HARD・RELIABLE_UP_TO_DAYS)。
通信する部品(collect.runner・collect.meta_fetch・collect.run・collect.diag・collect.diag_probe)は import しない(テストで検査する)。"""
