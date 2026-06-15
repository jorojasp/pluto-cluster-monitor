from __future__ import annotations

import socket
from typing import Any

from pluto_monitor.network.messages import dumps_message


class UdpJsonClient:
    def __init__(self, host: str, port: int) -> None:
        self.addr = (host, int(port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, message: dict[str, Any]) -> None:
        self.sock.sendto(dumps_message(message), self.addr)

    def close(self) -> None:
        self.sock.close()
