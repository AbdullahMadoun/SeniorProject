"""Tkinter GUI for quickrecord — Start / Stop button + MP4 fetch.

Threading model
---------------
Tk's mainloop runs on the main thread and is the only thread allowed
to touch widgets. All HTTP I/O (start, stop, download, health polling)
runs in worker threads which post results to a ``queue.Queue``; the
main thread drains the queue every 100 ms via ``root.after()`` and
applies the updates to the widgets. Calling Tk widgets from a worker
thread raises "main thread is not in main loop" and crashes randomly,
so this queue+after pattern is non-negotiable.

CLI
---
::

    python -m laptop_app --pi-url http://172.20.10.4:8765 \\
                         --save-folder ~/Videos/quickrecord
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Optional

import httpx

DEFAULT_PI_URL = "http://172.20.10.4:8765"
DEFAULT_SAVE_FOLDER = pathlib.Path.home() / "Videos" / "quickrecord"

HEALTH_POLL_INTERVAL_S = 2.0
HEALTH_HTTP_TIMEOUT_S = 3.0
QUEUE_DRAIN_INTERVAL_MS = 100
HTTP_TIMEOUT_S = 30.0
DOWNLOAD_TIMEOUT_S = 600.0
DOWNLOAD_PROGRESS_THROTTLE_S = 0.25
DOWNLOAD_CHUNK_BYTES = 64 * 1024


@dataclasses.dataclass
class GuiEvent:
    """Message posted from a worker thread to the main Tk thread."""

    kind: str  # health | start_done | stop_done | download_progress | download_done | error
    payload: dict[str, Any]


class QuickRecordApp:
    """Tkinter window with Start/Stop button, health indicator, save-folder picker.

    Construct then call :meth:`run` to enter the Tk mainloop. The
    constructor builds the UI, kicks off the health-poller worker
    thread, and schedules the queue-drain callback.
    """

    def __init__(self, pi_url: str, save_folder: pathlib.Path) -> None:
        self.pi_url = pi_url.rstrip("/")
        self.save_folder = save_folder
        self.save_folder.mkdir(parents=True, exist_ok=True)

        self.events: queue.Queue[GuiEvent] = queue.Queue()
        self.recording_id: Optional[str] = None
        self.button_busy = False
        self._stop_health = threading.Event()

        self._build_ui()
        self._start_health_poller()
        self.root.after(QUEUE_DRAIN_INTERVAL_MS, self._drain_events)

    # ---------- UI construction ---------------------------------------

    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("quickrecord")
        self.root.geometry("560x380")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=f"Pi: {self.pi_url}").pack(anchor="w")

        self.health_var = tk.StringVar(value="Disconnected")
        self.health_label = ttk.Label(
            frm, textvariable=self.health_var, foreground="gray"
        )
        self.health_label.pack(anchor="w", pady=(4, 8))

        folder_frame = ttk.Frame(frm)
        folder_frame.pack(fill="x", pady=4)
        ttk.Label(folder_frame, text="Save folder:").pack(side="left")
        self.folder_var = tk.StringVar(value=str(self.save_folder))
        ttk.Entry(folder_frame, textvariable=self.folder_var, width=42).pack(
            side="left", padx=4
        )
        ttk.Button(folder_frame, text="Browse…", command=self._pick_folder).pack(
            side="left"
        )

        self.button_var = tk.StringVar(value="Start Recording")
        self.button = ttk.Button(
            frm, textvariable=self.button_var, command=self._on_button
        )
        self.button.pack(pady=12, ipadx=20, ipady=8)

        ttk.Label(frm, text="Status:").pack(anchor="w")
        self.status = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.status.pack(fill="both", expand=True)

    # ---------- main-thread helpers -----------------------------------

    def _set_status(self, line: str) -> None:
        """Append a line to the status widget. Main thread only."""
        self.status.configure(state="normal")
        self.status.insert("end", line + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_var.get())
        if folder:
            self.folder_var.set(folder)
            self.save_folder = pathlib.Path(folder)
            self.save_folder.mkdir(parents=True, exist_ok=True)

    def _on_button(self) -> None:
        """Single button handler that dispatches to start or stop+download."""
        if self.button_busy:
            return
        self.button_busy = True
        self.button.configure(state="disabled")
        if self.recording_id is None:
            threading.Thread(target=self._do_start, daemon=True).start()
        else:
            threading.Thread(target=self._do_stop_and_download, daemon=True).start()

    def _on_close(self) -> None:
        self._stop_health.set()
        self.root.destroy()

    # ---------- worker-thread methods (NEVER touch Tk widgets) --------

    def _do_start(self) -> None:
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                resp = client.post(f"{self.pi_url}/start", json={})
            if resp.status_code == 200:
                self.events.put(
                    GuiEvent("start_done", {"ok": True, "data": resp.json()})
                )
            else:
                self.events.put(
                    GuiEvent(
                        "start_done",
                        {"ok": False, "status": resp.status_code, "body": resp.text},
                    )
                )
        except Exception as exc:
            self.events.put(
                GuiEvent("error", {"context": "start", "details": repr(exc)})
            )

    def _do_stop_and_download(self) -> None:
        rid = self.recording_id
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                resp = client.post(f"{self.pi_url}/stop")
        except Exception as exc:
            self.events.put(
                GuiEvent("error", {"context": "stop", "details": repr(exc)})
            )
            return

        if resp.status_code == 200:
            self.events.put(GuiEvent("stop_done", {"ok": True, "data": resp.json()}))
            self._download(rid)
        elif resp.status_code == 409:
            # Soft failure: the service may have crashed mid-recording.
            # Try the download anyway — the partial MP4 may be missing
            # its trailing moov atom but is often recoverable with
            # `ffmpeg -i broken.mp4 -c copy fixed.mp4`.
            self.events.put(
                GuiEvent(
                    "stop_done",
                    {"ok": False, "soft": True, "status": 409, "body": resp.text},
                )
            )
            self._download(rid)
        else:
            self.events.put(
                GuiEvent(
                    "stop_done",
                    {"ok": False, "status": resp.status_code, "body": resp.text},
                )
            )

    def _download(self, recording_id: Optional[str]) -> None:
        if recording_id is None:
            return
        url = f"{self.pi_url}/file/{recording_id}"
        dest = self.save_folder / f"{recording_id}.mp4"
        try:
            with httpx.Client(timeout=DOWNLOAD_TIMEOUT_S) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        self.events.put(
                            GuiEvent(
                                "error",
                                {
                                    "context": "download",
                                    "status": resp.status_code,
                                    "body": resp.read().decode("utf-8", errors="replace"),
                                },
                            )
                        )
                        return
                    total_str = resp.headers.get("Content-Length")
                    total = int(total_str) if total_str else None
                    written = 0
                    last_post = 0.0
                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=DOWNLOAD_CHUNK_BYTES):
                            fh.write(chunk)
                            written += len(chunk)
                            now = time.monotonic()
                            if now - last_post > DOWNLOAD_PROGRESS_THROTTLE_S:
                                self.events.put(
                                    GuiEvent(
                                        "download_progress",
                                        {"written": written, "total": total},
                                    )
                                )
                                last_post = now
            self.events.put(
                GuiEvent(
                    "download_done",
                    {"path": str(dest), "size_bytes": dest.stat().st_size},
                )
            )
        except Exception as exc:
            self.events.put(
                GuiEvent("error", {"context": "download", "details": repr(exc)})
            )

    def _start_health_poller(self) -> None:
        threading.Thread(target=self._health_loop, daemon=True).start()

    def _health_loop(self) -> None:
        while not self._stop_health.is_set():
            try:
                with httpx.Client(timeout=HEALTH_HTTP_TIMEOUT_S) as client:
                    resp = client.get(f"{self.pi_url}/health")
                if resp.status_code == 200:
                    self.events.put(
                        GuiEvent("health", {"ok": True, "data": resp.json()})
                    )
                else:
                    self.events.put(
                        GuiEvent("health", {"ok": False, "status": resp.status_code})
                    )
            except Exception:
                self.events.put(GuiEvent("health", {"ok": False}))
            self._stop_health.wait(HEALTH_POLL_INTERVAL_S)

    # ---------- queue drain (main thread) -----------------------------

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(QUEUE_DRAIN_INTERVAL_MS, self._drain_events)

    def _handle_event(self, event: GuiEvent) -> None:
        kind = event.kind
        payload = event.payload
        if kind == "health":
            self._apply_health(payload)
        elif kind == "start_done":
            self._apply_start_done(payload)
        elif kind == "stop_done":
            self._apply_stop_done(payload)
        elif kind == "download_progress":
            self._apply_download_progress(payload)
        elif kind == "download_done":
            self._apply_download_done(payload)
        elif kind == "error":
            self._apply_error(payload)

    def _apply_health(self, payload: dict[str, Any]) -> None:
        if not payload.get("ok"):
            self.health_var.set("Disconnected")
            self.health_label.configure(foreground="red")
            return
        data = payload["data"]
        if data.get("recording"):
            self.health_var.set("Recording")
            self.health_label.configure(foreground="orange")
        else:
            self.health_var.set("Connected")
            self.health_label.configure(foreground="green")

    def _apply_start_done(self, payload: dict[str, Any]) -> None:
        self.button_busy = False
        self.button.configure(state="normal")
        if payload.get("ok"):
            data = payload["data"]
            self.recording_id = data["recording_id"]
            self.button_var.set("Stop Recording")
            self._set_status(
                f"Recording started: id={data['recording_id']} at {data['started_at']}"
            )
        else:
            self._set_status(
                f"Start failed (HTTP {payload.get('status')}): {payload.get('body', '')}"
            )

    def _apply_stop_done(self, payload: dict[str, Any]) -> None:
        if payload.get("ok"):
            data = payload["data"]
            self._set_status(
                f"Recording stopped: id={data['recording_id']}, "
                f"size={data['size_bytes']} bytes, "
                f"duration={data['duration_s']:.1f}s"
            )
            self._set_status("Starting download...")
            # Button stays disabled until download_done; recording_id is
            # cleared in download_done.
        elif payload.get("soft"):
            self._set_status(
                "Stop returned 409 (service may have crashed). "
                "Attempting download anyway — file may be partial."
            )
        else:
            self.button_busy = False
            self.button.configure(state="normal")
            self._set_status(
                f"Stop failed (HTTP {payload.get('status')}): {payload.get('body', '')}"
            )
            # Don't clear recording_id; user can retry the stop.

    def _apply_download_progress(self, payload: dict[str, Any]) -> None:
        written = payload["written"]
        total = payload.get("total")
        if total:
            pct = 100.0 * written / total
            self._set_status(f"Downloading: {written}/{total} bytes ({pct:.1f}%)")
        else:
            self._set_status(f"Downloading: {written} bytes")

    def _apply_download_done(self, payload: dict[str, Any]) -> None:
        self.button_busy = False
        self.button.configure(state="normal")
        self.recording_id = None
        self.button_var.set("Start Recording")
        self._set_status(
            f"Saved to {payload['path']} ({payload['size_bytes']} bytes)"
        )

    def _apply_error(self, payload: dict[str, Any]) -> None:
        self.button_busy = False
        self.button.configure(state="normal")
        ctx = payload.get("context", "?")
        details = payload.get("details") or payload.get("body", "")
        self._set_status(f"Error during {ctx}: {details}")

    # ---------- entry point -------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="quickrecord laptop GUI")
    parser.add_argument(
        "--pi-url",
        default=DEFAULT_PI_URL,
        help="Base URL of the Pi quickrecord service (e.g. http://172.20.10.4:8765)",
    )
    parser.add_argument(
        "--save-folder",
        default=str(DEFAULT_SAVE_FOLDER),
        help="Folder where downloaded MP4s are written",
    )
    args = parser.parse_args()

    save_folder = pathlib.Path(os.path.expanduser(args.save_folder))
    QuickRecordApp(pi_url=args.pi_url, save_folder=save_folder).run()


if __name__ == "__main__":
    main()
