# py-irdroid-raw-tools

Small, standalone Python tools for receiving an infrared command with an Irdroid USB transceiver, saving it as learned Pronto Hex, and transmitting it again.

The tools communicate with Irdroid through a serial port. They do not require a device-specific DLL or an additional local library module.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## Requirements

- Python 3.9 or later
- Irdroid USB transceiver
- `pyserial`

Install the dependency:

```bash
python -m pip install pyserial
```

## Files

```text
irdroid_receive_pronto.py
irdroid_transmit_pronto.py
README.md
LICENSE
```

## Receive an IR command

```bash
python irdroid_receive_pronto.py
```

By default, the received command is saved to:

```text
learned_pronto.txt
```

Examples:

```bash
python irdroid_receive_pronto.py --port COM4
python irdroid_receive_pronto.py --port /dev/ttyACM0
python irdroid_receive_pronto.py --output command.txt
python irdroid_receive_pronto.py --carrier-hz 38000
python irdroid_receive_pronto.py --divisor 0067
```

The Irdroid receive stream provides pulse and space timings but does not directly provide the received carrier frequency. The receiver therefore uses a default carrier-frequency assumption of 40000 Hz. Use `--carrier-hz` or `--divisor` when a different value is required.

## Transmit a Pronto Hex command

```bash
python irdroid_transmit_pronto.py
```

When no input filename is supplied, the transmitter reads:

```text
learned_pronto.txt
```

The default transmission count is three frames. Repeating a frame is a general infrared reliability technique and is not specific to one device manufacturer. The required count can vary by command and target device.

Examples:

```bash
python irdroid_transmit_pronto.py command.txt
python irdroid_transmit_pronto.py command.txt --port COM4
python irdroid_transmit_pronto.py command.txt --port /dev/ttyACM0
python irdroid_transmit_pronto.py command.txt --frames 1
python irdroid_transmit_pronto.py command.txt --frames 5
```

## Notes

- The saved format is learned Pronto Hex beginning with `0000`.
- The default receive carrier frequency is 40000 Hz.
- `--divisor` overrides `--carrier-hz` during reception.
- The default transmit frame count is 3.
- `--frames` overrides the default transmit frame count.
- If automatic device detection does not find Irdroid, specify the serial port with `--port`.
