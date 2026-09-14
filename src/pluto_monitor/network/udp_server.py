from __future__ import annotations

import socket
from typing import Any

from pluto_monitor.network.messages import loads_message


class UdpJsonServer:
    def __init__(self, host: str, port: int, buffer_size: int = 65535) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, int(port)))
        self.buffer_size = int(buffer_size)

    def recv(self) -> tuple[dict[str, Any], tuple[str, int]]:
        data, addr = self.sock.recvfrom(self.buffer_size)
        return loads_message(data), addr

    def close(self) -> None:
        self.sock.close()
