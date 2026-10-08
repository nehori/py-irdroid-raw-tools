# SPDX-License-Identifier: MIT
# Copyright (c) 2026 py-irdroid-raw-tools contributors

"""Receive one raw IR frame from Irdroid and save it as Pronto Hex."""

import argparse
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

BAUDRATE = 115200
READ_TIMEOUT = 0.10
WRITE_TIMEOUT = 2
IRDROID_PID = 0xFD08
IRTOY_TICK_SECONDS = 21.333333e-6
DEFAULT_OUTPUT_FILE = "learned_pronto.txt"
DEFAULT_CARRIER_HZ = 40000
DEFAULT_LEAD_OUT_TICKS = 500
MAX_CAPTURE_BYTES = 65536

CMD_RESET = b"\x00\x00\x00\x00\x00"
CMD_VERSION = b"v"
CMD_RECORD_MODE = b"m"


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Receive one IR command with Irdroid and save it as Pronto Hex."
    )
    parser.add_argument(
        "--port",
        help="Serial port, for example COM4 or /dev/ttyACM0.",
    )
    parser.add_argument(
        "--carrier-hz",
        type=int,
        default=DEFAULT_CARRIER_HZ,
        help=f"Carrier frequency used in the Pronto header. Default: {DEFAULT_CARRIER_HZ}.",
    )
    parser.add_argument(
        "--divisor",
        type=lambda value: int(value, 16),
        help="Pronto carrier divisor in hexadecimal, for example 0067. Overrides --carrier-hz.",
    )
    parser.add_argument(
        "--lead-out-ticks",
        type=int,
        default=DEFAULT_LEAD_OUT_TICKS,
        help=f"Timing value treated as the frame-ending gap. Default: {DEFAULT_LEAD_OUT_TICKS}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_FILE),
        help=f"Output file. Default: {DEFAULT_OUTPUT_FILE}.",
    )
    return parser.parse_args()


def find_port(explicit_port):
    if explicit_port:
        return explicit_port

    ports = [
        port.device
        for port in serial.tools.list_ports.comports()
        if port.pid == IRDROID_PID
    ]

    if not ports:
        raise RuntimeError("No Irdroid device found. Specify the serial port with --port.")
    if len(ports) > 1:
        raise RuntimeError(
            "Multiple Irdroid devices found: {}. Specify one with --port.".format(
                ", ".join(ports)
            )
        )
    return ports[0]


def read_exact(serial_port, size, label):
    data = bytearray()
    deadline = time.monotonic() + WRITE_TIMEOUT

    while len(data) < size and time.monotonic() < deadline:
        chunk = serial_port.read(size - len(data))
        if chunk:
            data.extend(chunk)

    if len(data) != size:
        raise RuntimeError(
            f"Timeout reading {label}: expected {size} byte(s), got {len(data)}."
        )
    return bytes(data)


def initialize_record_mode(serial_port):
    serial_port.reset_input_buffer()
    serial_port.reset_output_buffer()
    serial_port.write(CMD_RESET)
    serial_port.flush()
    time.sleep(0.15)

    serial_port.reset_input_buffer()
    serial_port.write(CMD_VERSION)
    serial_port.flush()
    version = read_exact(serial_port, 4, "firmware version").decode(
        "ascii", errors="replace"
    )
    if not version.startswith("V"):
        raise RuntimeError(f"Unexpected firmware response: {version!r}")

    serial_port.write(CMD_RECORD_MODE)
    serial_port.flush()
    response = read_exact(serial_port, 3, "record mode")
    if response != b"S01":
        raise RuntimeError(f"Expected S01 after record mode command, got {response!r}.")

    return version


def capture_one_frame(serial_port, lead_out_ticks):
    pending = bytearray()
    timings = []
    received_bytes = 0

    while received_bytes < MAX_CAPTURE_BYTES:
        chunk = serial_port.read(256)
        if not chunk:
            continue

        received_bytes += len(chunk)
        pending.extend(chunk)

        while len(pending) >= 2:
            value = int.from_bytes(pending[:2], byteorder="big")
            del pending[:2]

            if value == 0xFFFF:
                if timings:
                    return timings, "device end marker"
                continue

            if value == 0:
                continue

            timings.append(value)

            if (
                len(timings) >= 4
                and len(timings) % 2 == 0
                and value >= lead_out_ticks
            ):
                return timings, f"lead-out 0x{value:04X}"

    raise RuntimeError(
        f"Capture exceeded {MAX_CAPTURE_BYTES} bytes without a frame end."
    )


def convert_to_pronto(timings, divisor):
    if len(timings) % 2:
        timings = timings[:-1]
    if len(timings) < 4:
        raise RuntimeError("Captured frame is too short.")

    pronto_tick_seconds = divisor / 4_145_146.0
    pronto_timings = [
        max(
            1,
            min(
                round(value * IRTOY_TICK_SECONDS / pronto_tick_seconds),
                0xFFFF,
            ),
        )
        for value in timings
    ]

    header = [0x0000, divisor, 0x0000, len(pronto_timings) // 2]
    return " ".join(f"{value:04X}" for value in header + pronto_timings)


def main():
    args = parse_arguments()

    if args.carrier_hz <= 0:
        raise ValueError("--carrier-hz must be greater than zero.")
    if args.lead_out_ticks <= 0:
        raise ValueError("--lead-out-ticks must be greater than zero.")

    divisor = (
        args.divisor
        if args.divisor is not None
        else round(4_145_146 / args.carrier_hz)
    )
    if not 1 <= divisor <= 0xFFFF:
        raise ValueError("Pronto divisor must be between 0001 and FFFF.")

    port = find_port(args.port)
    serial_port = serial.Serial(
        port,
        BAUDRATE,
        timeout=READ_TIMEOUT,
        write_timeout=WRITE_TIMEOUT,
    )

    try:
        version = initialize_record_mode(serial_port)
        print(f"Opened: {port} at {BAUDRATE} baud")
        print(f"Firmware: {version}")
        print("Point the remote at Irdroid and press one button once.")
        print("Capturing one RAW frame...")

        timings, end_reason = capture_one_frame(
            serial_port,
            args.lead_out_ticks,
        )
        pronto = convert_to_pronto(timings, divisor)
        args.output.write_text(pronto + "\n", encoding="ascii")

        print(f"Frame timings: {len(timings)}")
        print(f"Frame end: {end_reason}")
        print(f"Carrier divisor: {divisor:04X}")
        print(f"Saved: {args.output.resolve()}")
        return 0
    finally:
        try:
            serial_port.write(CMD_RESET)
            serial_port.flush()
        except Exception:
            pass
        serial_port.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
