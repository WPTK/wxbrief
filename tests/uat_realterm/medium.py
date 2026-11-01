"""Start a process at Medium integrity from an elevated (High) process: a restricted token with a lowered integrity level.

A hosted runner's user is an administrator and its processes are already elevated, so a plain launch is High and tests
nothing about the UAC case. This builds the token a normal (non-elevated) user session has: the caller's own primary
token, Administrators set to deny-only, all privileges but ``SeChangeNotify`` removed (``DISABLE_MAX_PRIVILEGE``), and
``TokenIntegrityLevel`` set to Medium (S-1-16-8192). It is a restricted version of the caller's token, so
``CreateProcessAsUser`` needs no extra privilege. ``integrity_of(pid)`` in ``winterm`` proves what the result is.

    python medium.py probe OUTFILE        # launch cmd.exe /c "whoami /groups" at Medium and report its integrity
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
from pathlib import Path

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_ASSIGN_PRIMARY, TOKEN_DUPLICATE, TOKEN_QUERY, TOKEN_ADJUST_DEFAULT = 0x1, 0x2, 0x8, 0x80
DISABLE_MAX_PRIVILEGE = 0x1
TOKEN_USER, TOKEN_OWNER, TOKEN_INTEGRITY_LEVEL = 1, 4, 25
SE_GROUP_INTEGRITY = 0x20
CREATE_UNICODE_ENVIRONMENT, CREATE_NO_WINDOW, CREATE_NEW_CONSOLE = 0x400, 0x08000000, 0x10


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = (wt.HANDLE,)
kernel32.WaitForSingleObject.argtypes = (wt.HANDLE, wt.DWORD)
kernel32.GetExitCodeProcess.argtypes = (wt.HANDLE, ctypes.POINTER(wt.DWORD))
advapi32.OpenProcessToken.argtypes = (wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE))
advapi32.ConvertStringSidToSidW.argtypes = (wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
advapi32.GetLengthSid.argtypes = (ctypes.c_void_p,)
advapi32.GetLengthSid.restype = wt.DWORD
advapi32.GetTokenInformation.argtypes = (wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD))
advapi32.SetTokenInformation.argtypes = (wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD)
advapi32.CreateRestrictedToken.argtypes = (
    wt.HANDLE,
    wt.DWORD,
    wt.DWORD,
    ctypes.POINTER(SID_AND_ATTRIBUTES),
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wt.HANDLE),
)
advapi32.CreateProcessAsUserW.argtypes = (
    wt.HANDLE,
    wt.LPCWSTR,
    wt.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wt.BOOL,
    wt.DWORD,
    ctypes.c_void_p,
    wt.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
)


def _fail(what: str) -> OSError:
    return OSError(f"{what} failed: Win32 error {ctypes.get_last_error()}")


class MediumProcess:
    """The slice of ``subprocess.Popen`` the driver uses: ``pid``, ``poll()``, ``wait()``."""

    def __init__(self, handle: int, pid: int) -> None:
        self._h, self.pid = handle, pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is None and kernel32.WaitForSingleObject(self._h, 0) == 0:
            code = wt.DWORD()
            kernel32.GetExitCodeProcess(self._h, ctypes.byref(code))
            self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if kernel32.WaitForSingleObject(self._h, ms) != 0:
            raise subprocess.TimeoutExpired("medium process", timeout or 0)
        code = self.poll()
        assert code is not None
        return code


def medium_token() -> int:
    """A primary token: this process's, Administrators deny-only, privileges stripped, integrity Medium."""
    src = wt.HANDLE()
    want = TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), want, ctypes.byref(src)):
        raise _fail("OpenProcessToken")
    admins = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW("S-1-5-32-544", ctypes.byref(admins)):
        raise _fail("ConvertStringSidToSid(Administrators)")
    disable = (SID_AND_ATTRIBUTES * 1)(SID_AND_ATTRIBUTES(admins.value, 0))
    new = wt.HANDLE()
    if not advapi32.CreateRestrictedToken(src, DISABLE_MAX_PRIVILEGE, 1, disable, 0, None, 0, None, ctypes.byref(new)):
        raise _fail("CreateRestrictedToken")
    # The owner of new objects must be the user, not the (now deny-only) Administrators group.
    need = wt.DWORD()
    advapi32.GetTokenInformation(src, TOKEN_USER, None, 0, ctypes.byref(need))
    ubuf = ctypes.create_string_buffer(need.value)
    if advapi32.GetTokenInformation(src, TOKEN_USER, ubuf, need, ctypes.byref(need)):
        user_sid = ctypes.c_void_p.from_buffer(ubuf).value
        owner = ctypes.c_void_p(user_sid)
        advapi32.SetTokenInformation(new, TOKEN_OWNER, ctypes.byref(owner), ctypes.sizeof(owner))
    medium = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW("S-1-16-8192", ctypes.byref(medium)):
        raise _fail("ConvertStringSidToSid(Medium)")
    label = SID_AND_ATTRIBUTES(medium.value, SE_GROUP_INTEGRITY)
    size = ctypes.sizeof(label) + advapi32.GetLengthSid(medium)
    if not advapi32.SetTokenInformation(new, TOKEN_INTEGRITY_LEVEL, ctypes.byref(label), size):
        raise _fail("SetTokenInformation(TokenIntegrityLevel)")
    kernel32.CloseHandle(src)
    return int(new.value)


def _env_block(env: dict[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    return ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in items) + "\0")


def spawn_medium(
    argv: list[str] | str, *, env: dict[str, str] | None = None, cwd: str | None = None, hidden_console: bool = False
) -> MediumProcess:
    """CreateProcessAsUser on the interactive desktop (winsta0\\default) with a Medium token."""
    token = medium_token()
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = "winsta0\\default"
    pi = PROCESS_INFORMATION()
    cmdline = ctypes.create_unicode_buffer(argv if isinstance(argv, str) else subprocess.list2cmdline(argv))
    flags = CREATE_UNICODE_ENVIRONMENT | (CREATE_NO_WINDOW if hidden_console else 0)
    block = _env_block(dict(env if env is not None else os.environ))
    ok = advapi32.CreateProcessAsUserW(
        token,
        None,
        cmdline,
        None,
        None,
        False,
        flags,
        ctypes.cast(block, ctypes.c_void_p),
        cwd,
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    err = ctypes.get_last_error()
    kernel32.CloseHandle(token)
    if not ok:
        raise OSError(f"CreateProcessAsUser failed: Win32 error {err}")
    kernel32.CloseHandle(pi.hThread)
    return MediumProcess(int(pi.hProcess), int(pi.dwProcessId))


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import winterm as w

    if len(sys.argv) >= 3 and sys.argv[1] == "probe":
        out = Path(sys.argv[2])
        lines = [f"caller pid {os.getpid()}: {w.integrity_of(os.getpid())}"]
        cmd = os.environ.get("COMSPEC", "cmd.exe")
        inner = f'whoami /groups > "{out}.groups.txt" & whoami /priv > "{out}.priv.txt" & ping -n 6 127.0.0.1 > nul'
        try:
            proc = spawn_medium([cmd, "/c", inner], hidden_console=True)
        except OSError as exc:
            lines.append(f"spawn_medium FAILED: {exc}")
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("\n".join(lines))
            return 1
        import time

        time.sleep(1.5)
        lines.append(f"child pid {proc.pid}: {w.integrity_of(proc.pid)}")
        proc.wait(30)
        for ext in ("groups", "priv"):
            f = Path(f"{out}.{ext}.txt")
            if f.exists():
                lines.append(f"--- whoami {ext} (Medium child)")
                lines.append(f.read_text(encoding="utf-8", errors="replace"))
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0 if "Medium" in lines[1] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
