# coding: utf-8
"""Replay a RAW infrared capture JSON through Irdroid."""

import argparse
import json
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

BAUDRATE = 115200
BUFFER_SIZE = 62
DEFAULT_CAPTURE = "learned_raw.json"
IRDROID_PID = 0xFD08
RESET = b"\x00\x00\x00\x00\x00"
VERSION = b"v"
TRANSMIT_MODE = b"n"
SAMPLE_MODE = b"s"
COUNT_REPORT = b"$"
NOTIFY_COMPLETE = b"%"
HANDSHAKE_MODE = b"&"
START_TRANSMIT = b"\x03"
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
        raise IrdroidError("Irdroid was not detected. Specify the COM port with --port.")
    if len(matches) > 1:
        raise IrdroidError(
            "Multiple Irdroid devices were detected: {}. Specify --port.".format(
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


def load_capture(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    raw_hex = record.get("raw_hex")
    if not raw_hex:
        raise IrdroidError(f"raw_hex is missing in {path}")
    try:
        return bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise IrdroidError("raw_hex contains invalid hexadecimal data.") from exc


def prepare_replay(raw):
    marker = raw.find(END_MARKER)
    if 0 <= marker <= 8:
        raw = raw[marker + 2:]

    while raw.endswith(END_MARKER):
        raw = raw[:-2]

    if len(raw) < 12:
        raise IrdroidError(f"Usable payload is too short: {len(raw)} byte(s).")
    if len(raw) % 2:
        raise IrdroidError(f"Payload has an odd byte length: {len(raw)}.")

    return raw + END_MARKER


def initialize_transmit_mode(ser):
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

    mode_command = TRANSMIT_MODE if int(version_text[1:]) > 224 else SAMPLE_MODE
    ser.write(mode_command)
    ser.flush()
    mode = read_exact(ser, 3, "mode")
    if mode != b"S01":
        raise IrdroidError(f"Expected S01, got {mode!r}")

    for command in (COUNT_REPORT, NOTIFY_COMPLETE, HANDSHAKE_MODE):
        ser.write(command)
        ser.flush()
        time.sleep(0.02)

    return version_text


def expect_handshake(ser, label):
    reply = read_exact(ser, 1, label)
    if reply != bytes([BUFFER_SIZE]):
        raise IrdroidError(f"Expected handshake 0x3E, got {reply!r}")


def transmit_once(ser, payload):
    ser.reset_input_buffer()
    ser.write(START_TRANSMIT)
    ser.flush()
    expect_handshake(ser, "start handshake")

    for index, offset in enumerate(range(0, len(payload), BUFFER_SIZE), start=1):
        chunk = payload[offset:offset + BUFFER_SIZE]
        ser.write(chunk)
        ser.flush()
        expect_handshake(ser, f"chunk {index} handshake")

    report = read_exact(ser, 3, "transmit count")
    if report[:1] != b"t":
        raise IrdroidError(f"Expected transmit-count response, got {report!r}")
    reported_length = int.from_bytes(report[1:3], byteorder="big")
    if reported_length != len(payload):
        raise IrdroidError(
            f"Length mismatch: sent {len(payload)}, device reported {reported_length}."
        )

    complete = read_exact(ser, 1, "completion")
    if complete != b"C":
        raise IrdroidError(f"Expected completion marker C, got {complete!r}")


def main():
    configure_console()
    parser = argparse.ArgumentParser(description="Replay an Irdroid RAW capture JSON.")
    parser.add_argument(
        "capture_json",
        nargs="?",
        default=DEFAULT_CAPTURE,
        help=f"Default: {DEFAULT_CAPTURE}",
    )
    parser.add_argument("--port", help="COM port. Auto-detected by default.")
    parser.add_argument("--repeat", type=int, default=1, help="Default: 1")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()

    if args.repeat < 1:
        raise SystemExit("--repeat must be 1 or greater.")

    capture_path = Path(args.capture_json)
    port = args.port or detect_port()

    try:
        raw = load_capture(capture_path)
        payload = prepare_replay(raw)
        with serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            timeout=args.timeout,
            write_timeout=args.timeout,
        ) as ser:
            print(f"Opened: {ser.port} at {ser.baudrate} baud", flush=True)
            version = initialize_transmit_mode(ser)
            print(f"Firmware: {version}", flush=True)
            print(f"Capture: {capture_path.resolve()}", flush=True)
            print(f"Payload: {len(payload)} byte(s)", flush=True)
            for count in range(1, args.repeat + 1):
                transmit_once(ser, payload)
                print(f"Transmission {count}/{args.repeat} completed.", flush=True)
            ser.write(RESET)
            ser.flush()
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"File error: {exc}") from exc
    except serial.SerialException as exc:
        raise SystemExit(f"Serial error: {exc}") from exc
    except IrdroidError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
