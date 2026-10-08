# Irdroid RAW IR Learner and Transmitter

Python scripts for capturing an infrared signal with Irdroid and replaying the saved RAW signal.

This repository uses the same simple workflow for receiving and transmitting:

1. Capture one remote-control command.
2. Save the RAW signal to `learned_raw.json`.
3. Replay `learned_raw.json`, or specify another capture file.

## Features

- Captures long RAW infrared signals.
- Saves the complete capture as hexadecimal timing data in JSON.
- Replays the saved RAW signal without Pronto conversion.
- Supports multi-line and long commands through a file-based workflow.
- Automatically detects one connected Irdroid device by USB PID.
- Allows an explicit COM port when multiple devices are connected.
- Works without a device-specific DLL.

## Requirements

- Python 3.9 or later
- Irdroid USB Infrared Transceiver
- `pyserial`

Install the Python dependency:

```bash
python -m pip install pyserial
```

The Irdroid device must appear as a serial port such as `COM4` on Windows or `/dev/ttyACM0` on Linux.

## Files

```text
irdroid-raw-tools/
├── README.md
├── irdroid_receive.py
└── irdroid_transmit.py
```

## Receive and Save a Signal

Run without a port argument to auto-detect one connected Irdroid device:

```bash
python -u irdroid_receive.py
```

The default output file is:

```text
learned_raw.json
```

During capture, aim the remote control at Irdroid and press and hold one button. Do not release and press the button repeatedly.

Specify the COM port when auto-detection is unavailable or multiple devices are connected:

```bash
python -u irdroid_receive.py COM4
```

Specify another output file:

```bash
python -u irdroid_receive.py COM4 --output command_1.json
```

Linux example:

```bash
python -u irdroid_receive.py /dev/ttyACM0 --output command_1.json
```

## Transmit a Saved Signal

By default, the transmitter reads `learned_raw.json`:

```bash
python -u irdroid_transmit.py
```

Specify a different capture file only when required:

```bash
python -u irdroid_transmit.py command_1.json
```

Specify a COM port:

```bash
python -u irdroid_transmit.py command_1.json --port COM4
```

Repeat the complete transmission:

```bash
python -u irdroid_transmit.py command_1.json --repeat 3
```

Linux example:

```bash
python -u irdroid_transmit.py command_1.json --port /dev/ttyACM0
```

## Capture File Format

The receiver creates a JSON file containing metadata and the exact captured byte stream:

```json
{
  "format": "irdroid-raw-v1",
  "port": "COM4",
  "firmware": "V225",
  "captured_at_utc": "2026-10-08T00:00:00+00:00",
  "byte_count": 100,
  "raw_hex": "ff ff 00 01 ..."
}
```

The transmitter uses the `raw_hex` field. No CSV or Pronto conversion is performed.

## Notes

- Keep one learned command in each JSON file.
- Use descriptive file names when saving multiple commands.
- When several Irdroid devices are connected, specify the serial port explicitly.
- The scripts validate firmware responses, handshakes, byte counts, and completion notifications.

## License

MIT License
