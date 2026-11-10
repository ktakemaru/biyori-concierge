"""テスト用: 引数の --url へ HTTP の GET を試みるだけ。計測フックが送信前に止めるかを確かめる。
フックが止めたら終了コード 75。止まらずに先へ進んだら 'hook_did_not_stop' を出して 0(テストが落ちる)。
ソケットは自分で禁止するので、フックが止めなくても実際には通信しない。元は biyori-hub tests/fixtures/stage11/agents/netbiyori/net_proposal.py。"""
import argparse
import socket
import urllib.request


def _no_network(*a, **k):
    raise OSError("test: ソケットは禁止")


socket.socket.connect = _no_network
socket.create_connection = _no_network
socket.getaddrinfo = _no_network

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="https://other.example.invalid/x")
ap.add_argument("--times", type=int, default=1)
a = ap.parse_args()
for _ in range(a.times):
    try:
        urllib.request.urlopen(a.url, timeout=1)
    except OSError:
        pass
print("hook_did_not_stop")
