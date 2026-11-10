"""診断: api.open-meteo.com の IP アドレスごとに応答するかを調べる(diagnose.yml。手動実行だけ)。
通信は collect/diag_probe.py の子プロセスだけが行い、計測フックを付ける(許可ホストは hosts.yaml の diag、上限は config.yaml の diag)。
ヤマビヨリは実行しない。棚には何も書かない。

確かめたい見立て(未確認の仮説): 「api.open-meteo.com の一部のサーバーが、GitHub のマシンから応答しない」。

  python -X utf8 -m collect diagnose --out <フォルダ>
  python -X utf8 -m collect diagnose-summary --artifact <フォルダ>
"""
import sys
from pathlib import Path

from .common import COLLECT, allow_hosts, config, read_json, write_json
from .runner import child_summary, run_hooked

PROBE = COLLECT / "diag_probe.py"
STAGES = {"tcp": "TCP の接続", "tls": "TLS の途中", "request": "リクエストの送信", "response": "応答待ち",
          "body": "本文の受信", "check": "中身が JSON でない", None: "不明"}


def diagnose(out_dir, python=None, cfg=None, test_ips=None):
    """→ 結果の dict(out_dir/diag.json にも書く)。test_ips はテスト用(名前解決をしない)。"""
    cfg = cfg or config()["diag"]
    out_dir = Path(out_dir).resolve()
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    probe_out = out_dir / "raw" / "probe.json"
    argv = [str(python or sys.executable), "-X", "utf8", str(PROBE), "--out", str(probe_out),
            "--per-ip", str(cfg["per_ip"]), "--interval", str(cfg["interval_s"]), "--timeout", str(cfg["timeout_s"]),
            "--max-requests", str(cfg["max_requests"]), "--max-ips", str(cfg["max_ips"]), "--total-timeout", str(cfg["total_timeout_s"])]
    if test_ips:
        argv += ["--ips", ",".join(test_ips)]
    res = run_hooked(argv, cwd=out_dir, req_log=out_dir / "raw" / "probe-requests.jsonl", max_requests=cfg["max_requests"],
                     allow=allow_hosts("diag"), timeout_s=float(cfg["total_timeout_s"]) + 120)
    (out_dir / "raw" / "probe-output.txt").write_text(res.stdout_tail + "\n--- stderr ---\n" + res.stderr_tail, encoding="utf-8", newline="\n")
    doc = read_json(probe_out) if res.returncode == 0 else None
    out = {"schema": "biyori-diag-run/1", "probe": doc, "hook": child_summary(res), "returncode": res.returncode,
           "timed_out": res.timed_out}
    write_json(out_dir / "diag.json", out)
    return out


def _q(d):
    return "—" if not d else f"{d['median']}({d['min']}〜{d['max']})"


def _tally(d):
    return ", ".join(f"{k} {v}" for k, v in d.items()) if d else "—"


def render_summary(artifact):
    """$GITHUB_STEP_SUMMARY 用の Markdown(通信なし)。"""
    d = read_json(Path(artifact) / "diag.json")
    lines = ["## 診断: api.open-meteo.com の IP アドレスごとの応答", ""]
    if not isinstance(d, dict):
        return "\n".join(lines + ["diag.json がありません(診断の前に止まった可能性。ジョブのログを見る)。", ""])
    h = d.get("hook") or {}
    lines += [f"- 計測フック: 通信 {h.get('requests')} 件、ステータス別 {h.get('by_status')}、失敗の種類 {_tally(h.get('by_error'))}、"
              f"中止 {h.get('aborted') or 'なし'}、429 {'あり' if h.get('rate_limited') else 'なし'}"]
    p = d.get("probe")
    if not isinstance(p, dict):
        return "\n".join(lines + [f"- 調べの結果がありません(終了コード {d.get('returncode')}、時間切れ {d.get('timed_out')})。", ""]) + "\n"
    s = p.get("settings") or {}
    lines += [f"- 取得したもの: `{p.get('path')}` だけ。IP ごとに {s.get('per_ip')} 回、{s.get('interval_s')} 秒以上あけて、打ち切り {s.get('timeout_s')} 秒(段階ごと)",
              f"- 名前解決: {len(p.get('resolved') or [])} 個(" + ", ".join(f"{x['ip']}[{x['family']}]" for x in p.get("resolved") or []) + ")"
              + (f"。失敗: {p['resolve_error']}" if p.get("resolve_error") else ""),
              f"- 途中でやめた理由: {p.get('stop') or 'なし'}", "",
              "| IP | 種類 | 回数 | 成功 | 失敗 | 失敗した段階 | 失敗の種類 | TLS(秒) | 応答待ち(秒) | 合計・成功(秒) | 合計・失敗(秒) |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in p.get("summary") or []:
        st = ", ".join(f"{STAGES.get(k, k)} {v}" for k, v in (x.get("failed_stage") or {}).items()) or "—"
        lines.append(f"| {x['ip']} | {x['family']} | {x['tries']} | {x['ok']} | {x['failed']} | {st} | {_tally(x.get('errors'))} | "
                     f"{_q(x.get('tls_s'))} | {_q(x.get('wait_s'))} | {_q(x.get('total_s_ok'))} | {_q(x.get('total_s_failed'))} |")
    lines += ["", "所要は 中央値(最小〜最大)。「応答待ち」はリクエストを送ってから応答の先頭が届くまで。",
              "この表は見立ての確認の材料で、原因を決めるものではありません。"]
    return "\n".join(lines) + "\n"
