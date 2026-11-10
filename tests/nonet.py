"""テスト中のソケット通信を禁止する。import するだけで有効(プロセス全体)。通信が試みられたら AssertionError。
子プロセスには及ばないので、テストが起動する子のスクリプトは自分でソケットを禁止する(tests/fixtures/*)。
元は biyori-hub tests/nonet.py(docs/ported-from-hub.md)。"""
import socket

_REAL = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex,
         "create_connection": socket.create_connection, "getaddrinfo": socket.getaddrinfo}


def _blocked(*a, **k):
    raise AssertionError("テスト中にネットワーク通信が試みられた(禁止)")


def block():
    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked


block()
