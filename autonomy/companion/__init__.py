"""Companion-computer hardware integration layer.

This package is intentionally isolated from the live dashboard and mission API.
The same modules are designed to run on either:

- a Raspberry Pi with physical GPIO, ADS1115, UART MAVLink, and USB cameras
- a Windows laptop with mock GPIO, mock ADC readings, mock camera frames, and mock MAVLink
"""

