# 予報を手で取り直す方法(GitHub の画面)

コンシェルは棚にある予報を読むだけで、予報を自分では取りに行きません。新しい予報にするには、利用者が GitHub で取得を動かします。
手順の元は `docs/revise-20261122-report.md` の「5. main から、全 76 座・publish ありで実行する」、入力の意味は `.github/workflows/collect.yml` です。

1. リポジトリの **Actions** タブ → 左の一覧で **collect** → 右上の **Run workflow**。
2. 入力
   - **Use workflow from**: `Branch: main`
   - `confirm`: `yes-run-live`
   - `agents`: `yamabiyori`
   - `yama_limit`: `all`(全 76 座。初期値は 3)
   - `yamabiyori_ref`: `main`
   - `publish`: **チェックを入れる**(入れないと棚が新しくならない。main 以外から取った回は棚に載らない)
3. 緑の **Run workflow** を押す。終わったら、コンシェルで質問し直す(`sync` が棚を取り込む)。

全 76 座の取得にかかった時間の記録: 2026-11-23 16:48 の回で 318.8 秒(棚の `manifest.json` の `runtime_s`。通信 228 件)。ほかの回は未確認です。
