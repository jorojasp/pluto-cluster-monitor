"""Web frontend for locally-connected Pluto radios (single PC, USB).

This package intentionally does not depend on `pluto_monitor.nodes` or
`pluto_monitor.network` (the Raspberry Pi distributed architecture). It
drives receivers/transmitter attached directly to the host running this
process, reusing the same building blocks as `pluto_monitor.app`.

The acquisition/service layer (`service.py`) is kept separate from the
HTTP/WebSocket layer (`server.py`) on purpose: when the distributed RPi
architecture is wired in later, a second data provider that reads
aggregated state from `nodes.central_server` can be added and swapped in
without touching the frontend (static/ + server.py stay the same, since
both providers can emit the same JSON shape produced by
`service._result_to_json`).
"""
