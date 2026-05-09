"""Entry point for ``python -m pi_service``.

Binds to ``0.0.0.0:8765`` so the laptop can reach the service over the
LAN. This deliberately exposes the service to anything on the same
network — only run it on a trusted dev hotspot, never on an open
network or with port-forward to the internet.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "pi_service.app:app",
        host="0.0.0.0",
        port=8765,
        log_level="info",
    )
