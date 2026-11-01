"""A raw byte reader: turns mouse reporting on (SGR) and appends every byte the terminal sends to a file as hex.

Used by test_probe.py to separate "the terminal never sent it" from "the app ignored it". Usage: rawprobe.py LOGFILE.
Press q to quit.
"""

import os
import sys
import termios
import time
import tty

log = sys.argv[1]
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
sys.stdout.write("\x1b[?1000h\x1b[?1006h" + "probe ready\r\n")
sys.stdout.flush()
try:
    while True:
        data = os.read(fd, 64)
        with open(log, "a") as f:
            f.write(f"{time.time():.3f} {data.hex()}\n")
        if data == b"q":
            break
finally:
    sys.stdout.write("\x1b[?1000l\x1b[?1006l")
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
