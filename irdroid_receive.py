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
SAMPLE_MODE = b"s"
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

    ser.write(SAMPLE_MODE)
    ser.flush()
    mode = read_exact(ser, 3, "sample mode")
    if mode != b"S01":
        raise IrdroidError(f"Expected S01, got {mode!r}")

    ser.reset_input_buffer()
    return version_text


def capture_raw(ser, start_timeout, idle_timeout, max_seconds):
    print("Aim the remote at Irdroid and press and hold one button.", flush=True)
    print("Do not release and press the button repeatedly.", flush=True)

    captured = bytearray()
    start_deadline = time.monotonic() + start_timeout
    capture_deadline = time.monotonic() + max_seconds
    last_data_time = None

    while time.monotonic() < capture_deadline:
        waiting = ser.in_waiting
        chunk = ser.read(waiting if waiting > 0 else 1)
        if chunk:
            captured.extend(chunk)
            last_data_time = time.monotonic()
            print(f"Captured: {len(captured)} byte(s)", end="\r", flush=True)
            continue

        now = time.monotonic()
        if not captured:
            if now >= start_deadline:
                raise IrdroidError("No infrared signal was received before timeout.")
        elif last_data_time is not None and now - last_data_time >= idle_timeout:
            break

    print("", flush=True)
    if len(captured) < 12:
        raise IrdroidError(f"Captured data is too short: {len(captured)} byte(s).")

    return bytes(captured)


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
    parser.add_argument("--idle-timeout", type=float, default=0.5)
    parser.add_argument("--max-seconds", type=float, default=20.0)
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
                args.idle_timeout,
                args.max_seconds,
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
