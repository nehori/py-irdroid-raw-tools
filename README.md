# py-irdroid-raw-tools

Standalone Python samples for receiving an IR command with Irdroid, saving it as Pronto Hex, and transmitting it again.

The scripts require only `pyserial`. They do not require `irdroid.py` or a device-specific DLL.

## Files

```text
irdroid_receive_pronto.py
irdroid_transmit_pronto.py
README.md
```

## Install

```bash
python -m pip install pyserial
```

## Receive

```bash
python -u irdroid_receive_pronto.py
```

The default output is:

```text
learned_pronto.txt
```

Examples:

```bash
python -u irdroid_receive_pronto.py --port COM4
python -u irdroid_receive_pronto.py --carrier-hz 38000
python -u irdroid_receive_pronto.py --divisor 0067
python -u irdroid_receive_pronto.py --output command_1.txt
```

The receive stream contains pulse and space durations but does not directly provide the received carrier frequency. The default carrier assumption is 40000 Hz. Specify another carrier frequency or Pronto divisor when required.

## Transmit

```bash
python -u irdroid_transmit_pronto.py
```

With no filename, the transmitter reads `learned_pronto.txt`.

The default transmission count is **3 frames**. This is a general reliability default and is not restricted to one device brand. Some devices accept one frame, while others require repeated frames to recognize the command reliably.

Examples:

```bash
python -u irdroid_transmit_pronto.py command_1.txt
python -u irdroid_transmit_pronto.py command_1.txt --port COM4
python -u irdroid_transmit_pronto.py command_1.txt --frames 1
python -u irdroid_transmit_pronto.py command_1.txt --frames 5
```

## Windows example

```bash
/c/Python314/python.exe -u irdroid_receive_pronto.py
/c/Python314/python.exe -u irdroid_transmit_pronto.py
```

## Linux example

```bash
python3 -u irdroid_receive_pronto.py --port /dev/ttyACM0
python3 -u irdroid_transmit_pronto.py --port /dev/ttyACM0
```

The user may need permission to access the serial device.

## Notes

- The saved format is learned Pronto Hex beginning with `0000`.
- The receive default carrier frequency is 40000 Hz.
- `--divisor` overrides `--carrier-hz` during reception.
- The transmit default is 3 frames.
- `--frames` overrides the default frame count.
- If automatic USB PID detection does not find Irdroid, specify `--port` explicitly.
