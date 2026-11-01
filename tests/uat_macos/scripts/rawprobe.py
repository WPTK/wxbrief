"""A raw byte reader: turns mouse reporting on (SGR) and appends every byte the terminal sends to a file as hex.

Used by test_probe.py to separate "the terminal never sent it" from "the app ignored it". Usage: rawprobe.py LOGFILE [IDLE_SECONDS].
Press q to quit, or stop sending for IDLE_SECONDS after the first input.
"""

import os
import select
import sys
import termios
import time
import tty

log = sys.argv[1]
idle = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
seen = False
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
sys.stdout.write("\x1b[?1000h\x1b[?1006h" + "probe ready\r\n")
sys.stdout.flush()
try:
    while True:
        if idle and not select.select([fd], [], [], idle if seen else 90)[0]:
            break
        data = os.read(fd, 64)
        seen = True
        with open(log, "a") as f:
            f.write(f"{time.time():.3f} {data.hex()}\n")
        if data == b"q":
            break
finally:
    sys.stdout.write("\x1b[?1000l\x1b[?1006l")
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
