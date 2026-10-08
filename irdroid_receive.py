# coding: utf-8
"""Capture a RAW infrared signal from Irdroid and save it as JSON."""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import serial
import serial.tools.list_ports

BAUDRATE = 115200
DEFAULT_OUTPUT = "learned_raw.json"
IRDROID_PID = 0xFD08
RESET = b"\x00\x00\x00\x00\x00"
VERSION = b"v"
RECORD_MODE = b"m"
END_MARKER = b"\xff\xff"


class IrdroidError(RuntimeError):
    pass


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def detect_port():
    matches = [
        port.device
        for port in serial.tools.list_ports.comports()
        if port.pid == IRDROID_PID
    ]
    if not matches:
        raise IrdroidError("Irdroid was not detected. Specify the COM port explicitly.")
    if len(matches) > 1:
        raise IrdroidError(
            "Multiple Irdroid devices were detected: {}. Specify one port.".format(
                ", ".join(matches)
            )
        )
    return matches[0]


def read_exact(ser, size, label):
    data = bytearray()
    deadline = time.monotonic() + max(float(ser.timeout or 0), 0.1)
    while len(data) < size and time.monotonic() < deadline:
        chunk = ser.read(size - len(data))
        if chunk:
            data.extend(chunk)
    if len(data) != size:
        raise IrdroidError(
            f"Timeout for {label}: expected {size} byte(s), got {len(data)}."
        )
    return bytes(data)


def initialize_receive_mode(ser):
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(RESET)
    ser.flush()
    time.sleep(0.15)
    ser.reset_input_buffer()

    ser.write(VERSION)
    ser.flush()
    version = read_exact(ser, 4, "version")
    version_text = version.decode("ascii", errors="strict")
    if not version_text.startswith("V") or not version_text[1:].isdigit():
        raise IrdroidError(f"Invalid version response: {version!r}")

    ser.write(RECORD_MODE)
    ser.flush()
    mode = read_exact(ser, 3, "record mode")
    if mode != b"S01":
        raise IrdroidError(f"Expected S01, got {mode!r}")

    ser.reset_input_buffer()
    return version_text


def capture_raw(ser, start_timeout, max_seconds, max_bytes):
    print("Point the remote at Irdroid and press one button once.", flush=True)
    print("Capturing one RAW frame...", flush=True)

    captured = bytearray()
    start_deadline = time.monotonic() + start_timeout
    capture_deadline = time.monotonic() + max_seconds
    minimum_timing_words = 8
    lead_out_threshold = 0x0100

    while time.monotonic() < capture_deadline:
        waiting = ser.in_waiting
        chunk = ser.read(waiting if waiting > 0 else 1)
        if not chunk:
            if not captured and time.monotonic() >= start_deadline:
                raise IrdroidError("No infrared signal was received before timeout.")
            continue

        captured.extend(chunk)
        print(
            f"RX fragment: {chunk.hex(' ')} "
            f"({len(chunk)} byte(s)), total={len(captured)}",
            flush=True,
        )

        if len(captured) > max_bytes:
            raise IrdroidError(
                f"Capture exceeded the safety limit of {max_bytes} byte(s)."
            )

        # Record mode returns 16-bit big-endian timing values continuously.
        # A complete frame ends at the first long lead-out gap. In the verified
        # capture this is approximately 0x04B3 to 0x04B5. Stop there instead of
        # waiting for serial idle, because a held remote immediately repeats.
        even_length = len(captured) - (len(captured) % 2)
        words = [
            int.from_bytes(captured[i:i + 2], "big")
            for i in range(0, even_length, 2)
        ]
        for index, value in enumerate(words):
            if index >= minimum_timing_words and value >= lead_out_threshold:
                frame_end = (index + 1) * 2
                frame = bytes(captured[:frame_end])
                print(
                    f"Lead-out detected: 0x{value:04X}; "
                    f"one frame={len(frame)} byte(s)",
                    flush=True,
                )
                return frame

    raise IrdroidError(
        f"No complete frame lead-out was detected within {max_seconds} second(s)."
    )


def main():
    configure_console()
    parser = argparse.ArgumentParser(
        description="Capture a RAW infrared signal from Irdroid."
    )
    parser.add_argument("port", nargs="?", help="COM port. Auto-detected by default.")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help=f"Default: {DEFAULT_OUTPUT}"
    )
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--start-timeout", type=float, default=15.0)
    parser.add_argument("--max-seconds", type=float, default=20.0)
    parser.add_argument("--max-bytes", type=int, default=65536)
    args = parser.parse_args()

    port = args.port or detect_port()
    output_path = Path(args.output)

    try:
        with serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            timeout=args.timeout,
            write_timeout=args.timeout,
        ) as ser:
            print(f"Opened: {ser.port} at {ser.baudrate} baud", flush=True)
            version = initialize_receive_mode(ser)
            print(f"Firmware: {version}", flush=True)
            raw = capture_raw(
                ser,
                args.start_timeout,
                args.max_seconds,
                args.max_bytes,
            )
            ser.write(RESET)
            ser.flush()
    except serial.SerialException as exc:
        raise SystemExit(f"Serial error: {exc}") from exc
    except IrdroidError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    record = {
        "format": "irdroid-raw-v1",
        "port": port,
        "firmware": version,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "byte_count": len(raw),
        "raw_hex": raw.hex(" "),
    }
    output_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"RAW bytes: {len(raw)}", flush=True)
    print(f"End marker found: {END_MARKER in raw}", flush=True)
    print(f"Saved: {output_path.resolve()}", flush=True)


if __name__ == "__main__":
    main()
