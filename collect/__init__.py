"""取得の側(GitHub Actions で動く)。Open-Meteo への通信は、計測フックを付けた子プロセスの中だけで起きる。
答える側(concierge/)はこのパッケージを import しない。"""
