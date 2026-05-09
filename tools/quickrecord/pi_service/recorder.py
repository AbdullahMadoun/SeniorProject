"""Thread-safe wrapper around Picamera2 for MP4 video recording."""

from __future__ import annotations

import pathlib
import threading
from typing import Optional

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput


class CameraRecorder:
    """Owns a single Picamera2 instance with a start / stop lifecycle.

    Concurrency: an internal ``threading.Lock`` serialises ``start()``
    and ``stop()`` so HTTP handlers cannot race each other into a half
    state. ``is_recording()`` also acquires the lock so callers see a
    consistent view.

    Cleanup contract: ``stop()`` always returns the recorder to the
    not-recording state, even if the underlying camera teardown raises.
    This guarantees that a subsequent ``start()`` succeeds even after a
    partial failure during stop.

    The ``FfmpegOutput`` wrapper is used (not ``FileOutput``) so the
    H264 stream is muxed into an MP4 container automatically. ``FileOutput``
    would produce a raw .h264 file that most viewers cannot play without
    a manual remux.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._camera: Optional[Picamera2] = None
        self._recording = False

    def start(
        self,
        output_path: pathlib.Path,
        resolution: tuple[int, int],
        bitrate_bps: int,
    ) -> None:
        """Begin recording into ``output_path`` as an MP4.

        Raises:
            RuntimeError: with message ``"already recording"`` if a
                recording is already active.
            Exception: any error raised by picamera2 (e.g. when another
                process holds the camera) is propagated unchanged. The
                HTTP layer translates these to 503.
        """
        with self._lock:
            if self._recording:
                raise RuntimeError("already recording")

            camera = Picamera2()
            try:
                config = camera.create_video_configuration(
                    main={"size": resolution},
                )
                camera.configure(config)
                encoder = H264Encoder(bitrate=bitrate_bps)
                output = FfmpegOutput(str(output_path))
                camera.start_recording(encoder, output)
            except Exception:
                try:
                    camera.close()
                except Exception:
                    pass
                raise

            self._camera = camera
            self._recording = True

    def stop(self) -> None:
        """Stop the active recording and release the camera.

        State is cleared first, so even if camera teardown raises the
        recorder is left in the not-recording state and the next
        ``start()`` can succeed. The teardown error, if any, is
        re-raised so the caller can surface it.

        Raises:
            RuntimeError: with message ``"not recording"`` if no
                recording is active.
        """
        with self._lock:
            if not self._recording:
                raise RuntimeError("not recording")

            camera = self._camera
            self._camera = None
            self._recording = False

            stop_err: Optional[BaseException] = None
            if camera is not None:
                try:
                    camera.stop_recording()
                except Exception as exc:
                    stop_err = exc
                try:
                    camera.close()
                except Exception as exc:
                    if stop_err is None:
                        stop_err = exc
            if stop_err is not None:
                raise stop_err

    def is_recording(self) -> bool:
        """Return ``True`` iff a recording is currently active."""
        with self._lock:
            return self._recording
