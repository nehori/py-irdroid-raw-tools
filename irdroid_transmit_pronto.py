# -*- coding: utf-8 -*-
"""Transmit Pronto Hex from a text file through Irdroid."""

import argparse
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

BAUDRATE = 115200
TIMEOUT = 2
PID = 0xFD08
BUFFER_SIZE = 62
IRTOY_TICK_S = 21.333333e-6
DEFAULT_FILE = "learned_pronto.txt"
DEFAULT_FRAMES = 3

CMD_RESET = b"\x00\x00\x00\x00\x00"
CMD_VERSION = b"v"
CMD_SAMPLE_MODE = b"s"
CMD_TRANSMIT_MODE = b"n"
CMD_TRANSMIT = b"\x03"
CMD_BYTE_COUNT_REPORT = b"\x24"
CMD_NOTIFY_ON_COMPLETE = b"\x25"
CMD_HANDSHAKE = b"\x26"
END_MARKER = b"\xFF\xFF"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Transmit a Pronto Hex text file through Irdroid."
    )
    parser.add_argument(
        "file", nargs="?", type=Path, default=Path(DEFAULT_FILE),
        help=f"Pronto Hex text file. Default: {DEFAULT_FILE}."
    )
    parser.add_argument(
        "--port", help="Serial port, for example COM4 or /dev/ttyACM0."
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"Number of frames sent in one transmission. Default: {DEFAULT_FRAMES}."
    )
    return parser.parse_args()


def find_port(explicit_port):
    if explicit_port:
        return explicit_port
    matches = [p.device for p in serial.tools.list_ports.comports() if p.pid == PID]
    if not matches:
        raise RuntimeError("No Irdroid device found. Specify the port with --port.")
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple Irdroid devices found: {}. Specify one with --port.".format(
                ", ".join(matches)
            )
        )
    return matches[0]


def read_exact(ser, size, label):
    data = bytearray()
    deadline = time.monotonic() + TIMEOUT
    while len(data) < size and time.monotonic() < deadline:
        chunk = ser.read(size - len(data))
        if chunk:
            data.extend(chunk)
    if len(data) != size:
        raise RuntimeError(
            f"Timeout reading {label}: expected {size}, got {len(data)}."
        )
    return bytes(data)


def load_pronto(path):
    if not path.is_file():
        raise FileNotFoundError(f"Pronto file not found: {path}")

    tokens = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tokens.extend(line.split())

    try:
        words = [int(token, 16) for token in tokens]
    except ValueError as exc:
        raise ValueError("Pronto file contains a non-hexadecimal word.") from exc

    if len(words) < 4:
        raise ValueError("Pronto data is shorter than its header.")

    format_word, divisor, intro_pairs, repeat_pairs = words[:4]
    if format_word != 0x0000:
        raise ValueError("Only learned Pronto format 0000 is supported.")
    if divisor == 0:
        raise ValueError("Pronto carrier divisor cannot be zero.")

    expected = 4 + 2 * (intro_pairs + repeat_pairs)
    if len(words) != expected:
        raise ValueError(
            f"Pronto length mismatch: expected {expected} words, got {len(words)}."
        )

    timings = words[4:]
    frame = timings[intro_pairs * 2:] if repeat_pairs else timings[:intro_pairs * 2]
    if not frame:
        raise ValueError("Pronto data contains no timing frame.")
    return divisor, frame


def pronto_to_raw(divisor, frame, frame_count):
    pronto_tick_s = divisor / 4_145_146.0
    raw_frame = bytearray()
    for value in frame:
        if value <= 0:
            raise ValueError("Pronto timing values must be positive.")
        ticks = round(value * pronto_tick_s / IRTOY_TICK_S)
        ticks = max(1, min(ticks, 0xFFFE))
        raw_frame.extend(ticks.to_bytes(2, "big"))
    return bytes(raw_frame) * frame_count + END_MARKER, len(raw_frame)


def initialize_transmit_mode(ser):
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(CMD_RESET)
    ser.flush()
    time.sleep(0.15)

    ser.reset_input_buffer()
    ser.write(CMD_VERSION)
    ser.flush()
    version = read_exact(ser, 4, "firmware version").decode(
        "ascii", errors="replace"
    )
    if not version.startswith("V"):
        raise RuntimeError(f"Unexpected firmware response: {version!r}")

    separate_mode = version[1:].isdigit() and int(version[1:]) > 224
    ser.write(CMD_TRANSMIT_MODE if separate_mode else CMD_SAMPLE_MODE)
    ser.flush()
    mode = read_exact(ser, 3, "transmit mode")
    if mode != b"S01":
        raise RuntimeError(f"Expected S01 after mode command, got {mode!r}.")

    ser.write(CMD_BYTE_COUNT_REPORT)
    ser.flush()
    time.sleep(0.02)
    ser.write(CMD_NOTIFY_ON_COMPLETE)
    ser.flush()
    time.sleep(0.02)
    ser.write(CMD_HANDSHAKE)
    ser.flush()
    time.sleep(0.02)
    return version


def transmit(ser, payload):
    ser.reset_input_buffer()
    ser.write(CMD_TRANSMIT)
    ser.flush()

    if read_exact(ser, 1, "initial handshake") != bytes([BUFFER_SIZE]):
        raise RuntimeError("Irdroid did not return the initial 0x3E handshake.")

    for start in range(0, len(payload), BUFFER_SIZE):
        ser.write(payload[start:start + BUFFER_SIZE])
        ser.flush()
        if read_exact(ser, 1, "chunk handshake") != bytes([BUFFER_SIZE]):
            raise RuntimeError("Irdroid did not return the 0x3E chunk handshake.")

    count_reply = read_exact(ser, 3, "transmit count")
    if count_reply[:1] != b"t":
        raise RuntimeError(f"Unexpected transmit-count reply: {count_reply!r}")

    reported = int.from_bytes(count_reply[1:], "big")
    if reported != len(payload):
        raise RuntimeError(
            f"Transmit length mismatch: sent {len(payload)}, device reported {reported}."
        )

    if read_exact(ser, 1, "completion") != b"C":
        raise RuntimeError("Irdroid did not return completion notification C.")


def main():
    args = parse_args()
    if args.frames < 1:
        raise ValueError("--frames must be 1 or greater.")

    divisor, frame = load_pronto(args.file)
    payload, frame_bytes = pronto_to_raw(divisor, frame, args.frames)
    port = find_port(args.port)

    ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT, write_timeout=TIMEOUT)
    try:
        version = initialize_transmit_mode(ser)
        print(f"Pronto file: {args.file}")
        print(f"COM port: {port}")
        print(f"Firmware: {version}")
        print(f"Frame bytes: {frame_bytes}")
        print(f"Frames per transmission: {args.frames}")
        print(f"Payload: {len(payload)} byte(s)")
        transmit(ser, payload)
        print("Transmission completed successfully.")
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
