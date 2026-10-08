# -*- coding: utf-8 -*-
"""Capture one Irdroid RAW IR frame and save it as Pronto Hex."""

import argparse
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

BAUDRATE = 115200
TIMEOUT = 0.10
PID = 0xFD08
CMD_RESET = b"\x00\x00\x00\x00\x00"
CMD_VERSION = b"v"
CMD_RECORD_MODE = b"m"
IRTOY_TICK_S = 21.333333e-6
DEFAULT_FILE = "learned_pronto.txt"
DEFAULT_CARRIER_HZ = 40000
DEFAULT_LEAD_OUT_TICKS = 500
MAX_CAPTURE_BYTES = 65536


def parse_args():
    parser = argparse.ArgumentParser(description="Capture one IR command with Irdroid and save Pronto Hex.")
    parser.add_argument("--port", help="Serial port, for example COM4 or /dev/ttyACM0.")
    parser.add_argument("--carrier-hz", type=int, default=DEFAULT_CARRIER_HZ,
                        help=f"Carrier frequency used in the Pronto header. Default: {DEFAULT_CARRIER_HZ}.")
    parser.add_argument("--divisor", type=lambda value: int(value, 16),
                        help="Pronto carrier divisor in hexadecimal, for example 0067. Overrides --carrier-hz.")
    parser.add_argument("--lead-out-ticks", type=int, default=DEFAULT_LEAD_OUT_TICKS,
                        help=f"Irdroid timing value treated as the frame-ending gap. Default: {DEFAULT_LEAD_OUT_TICKS}.")
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_FILE),
                        help=f"Output Pronto text file. Default: {DEFAULT_FILE}.")
    return parser.parse_args()


def find_port(explicit_port):
    if explicit_port:
        return explicit_port
    matches = [port.device for port in serial.tools.list_ports.comports() if port.pid == PID]
    if not matches:
        raise RuntimeError("No Irdroid device found. Specify the port with --port.")
    if len(matches) > 1:
        raise RuntimeError("Multiple Irdroid devices found: {}. Specify one with --port.".format(", ".join(matches)))
    return matches[0]


def read_exact(ser, size, label):
    data = bytearray()
    deadline = time.monotonic() + 2.0
    while len(data) < size and time.monotonic() < deadline:
        chunk = ser.read(size - len(data))
        if chunk:
            data.extend(chunk)
    if len(data) != size:
        raise RuntimeError(f"Timeout reading {label}: expected {size}, got {len(data)}.")
    return bytes(data)


def initialize_record_mode(ser):
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(CMD_RESET)
    ser.flush()
    time.sleep(0.15)
    ser.reset_input_buffer()
    ser.write(CMD_VERSION)
    ser.flush()
    version = read_exact(ser, 4, "firmware version").decode("ascii", errors="replace")
    if not version.startswith("V"):
        raise RuntimeError(f"Unexpected firmware response: {version!r}")
    ser.write(CMD_RECORD_MODE)
    ser.flush()
    mode = read_exact(ser, 3, "record mode")
    if mode != b"S01":
        raise RuntimeError(f"Expected S01 after record mode command, got {mode!r}.")
    return version


def capture_one_frame(ser, lead_out_ticks):
    pending = bytearray()
    timings = []
    received_bytes = 0
    while received_bytes < MAX_CAPTURE_BYTES:
        chunk = ser.read(256)
        if not chunk:
            continue
        received_bytes += len(chunk)
        pending.extend(chunk)
        while len(pending) >= 2:
            value = int.from_bytes(pending[:2], "big")
            del pending[:2]
            if value == 0xFFFF:
                if timings:
                    return timings, "device end marker"
                continue
            if value == 0:
                continue
            timings.append(value)
            if len(timings) >= 4 and len(timings) % 2 == 0 and value >= lead_out_ticks:
                return timings, f"lead-out 0x{value:04X}"
    raise RuntimeError(f"Capture exceeded {MAX_CAPTURE_BYTES} bytes without a frame end.")


def make_pronto(timings, divisor):
    if len(timings) % 2:
        timings = timings[:-1]
    if len(timings) < 4:
        raise RuntimeError("Captured frame is too short.")
    pronto_tick_s = divisor / 4_145_146.0
    words = [max(1, min(round(value * IRTOY_TICK_S / pronto_tick_s), 0xFFFF)) for value in timings]
    header = [0x0000, divisor, 0x0000, len(words) // 2]
    return " ".join(f"{value:04X}" for value in header + words)


def main():
    args = parse_args()
    if args.carrier_hz <= 0:
        raise ValueError("--carrier-hz must be greater than zero.")
    if args.lead_out_ticks <= 0:
        raise ValueError("--lead-out-ticks must be greater than zero.")
    divisor = args.divisor if args.divisor is not None else round(4_145_146 / args.carrier_hz)
    if not 1 <= divisor <= 0xFFFF:
        raise ValueError("Pronto divisor must be between 0001 and FFFF.")
    port = find_port(args.port)
    ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT, write_timeout=2)
    try:
        version = initialize_record_mode(ser)
        print(f"Opened: {port} at {BAUDRATE} baud")
        print(f"Firmware: {version}")
        print("Point the remote at Irdroid and press one button once.")
        print("Capturing one RAW frame...")
        timings, end_reason = capture_one_frame(ser, args.lead_out_ticks)
        pronto = make_pronto(timings, divisor)
        args.output.write_text(pronto + "\n", encoding="ascii")
        print(f"Frame timings: {len(timings)}")
        print(f"Frame end: {end_reason}")
        print(f"Carrier divisor: {divisor:04X}")
        print(f"Saved: {args.output.resolve()}")
        return 0
    finally:
        try:
            ser.write(CMD_RESET)
            ser.flush()
        except Exception:
            pass
        ser.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, serial.SerialException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
