# Stop フック(送る前の検査)

`verify` を通さずに答えを送ること、`verify` の出した文の前後に文を足すことを、Claude Code の Stop フックで止めます。
考え方はイキモノビヨリ(`.claude/hooks/stop_check.py`・`ikimonobiyori/stop_hook.py`・`docs/guide-mode.md` 3 章)にそろえました(コードは import しない・写さない)。

| 場所 | 中身 |
|---|---|
| `.claude/settings.json` | Stop フックの登録 |
| `.claude/hooks/stop_check.py` | 入口(薄い。失敗しても終了コード 0 で通す) |
| `concierge/stop_hook.py` | 中身(通信しない・決定的) |
| `concierge/data/stop_hook.yaml` | 語と値(仮置き) |
| 置き場の `last_answer.json` | `verify` が出した最後の文(合格した最終の文か控えの文)。不合格のときは残さない |
| 置き場の `logs/stop_hook_state.json` | 同じ回で止めた回数 |

## 止めるとき

この回(利用者の最後の文のあと)に `concierge brief` を実行したときだけ見ます。

1. `no_verify`: 最後の `brief` のあとに `concierge verify … --brief` を実行していない。
2. `mismatch`: 最後のメッセージが、`verify` の出した文と一致しない(前後の空白と改行の形の違いは見ない。2 問に続けて答えたときは、`verify` の文だけを並べた形も通す)。この回と違う資料の文は認めない。

止めたときは、次の手順(`verify` に通して、その標準出力だけを送る)をエージェントに返します。**同じ回で 2 回止めたら、3 回目は通します**(イキモノビヨリと同じ)。

## 止めないとき(迷う場合は通す)

- この回に `brief` を使っていない。`brief` が失敗した。文書や `grep` の引数に書かれているだけ。
- 開発の作業の回: 利用者の文に `skip_words` の語(指示書・テスト・コード・`.md` など)がある、`git commit` などの変更のコマンドか unittest を使った、リポジトリの中のファイルを書いた(下書きを一時フォルダに書くのは開発とみなさない)。
- スラッシュコマンド・`!` のコマンド・裏の作業の知らせのあとの回(回の区切りとして数える)。
- 会話の記録・入力が読めない。フックの中でエラーが起きた。

## 切る方法

環境変数 `BIYORI_CONCIERGE_STOP_HOOK=off` を付けて Claude Code を開きます(PowerShell なら `$env:BIYORI_CONCIERGE_STOP_HOOK='off'; claude`)。

## 分かっている限界

- `brief` の出力を見ないで変数に入れて使うなどすると、資料の id が分からないことがある(そのときは最後の文だけと比べる)。
- `python` と `-m concierge` のあいだに見慣れない書き方があると、`brief` を見つけられない(通す)。
- 同じ置き場を 2 つの会話で同時に使うと `last_answer.json` は後のものになる(この回の資料の文 `briefs/<id>.final.txt` とも比べるので、ふつうは困らない)。
- コマンドを呼ぶ合間の文(「最終確認しています」など)は見ない(見るのは最後のメッセージだけ)。手順として守る(`AGENTS.md` §2 の 6)。
- 開発の作業と質問を 1 つの文で頼まれた回は見ない。
