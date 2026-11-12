"""Read-only process liveness for ownership recovery; uncertainty means alive."""
import os


def process_is_alive(pid: int) -> bool:
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        handle = open_process(0x1000, 0, pid)  # QUERY_LIMITED_INFORMATION only
        if not handle:
            # INVALID_PARAMETER is the documented nonexistent PID result.
            # Access denied and all other uncertainty must not settle a call.
            return ctypes.get_last_error() != 87
        try:
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            get_exit_code.restype = ctypes.c_int
            exit_code = ctypes.c_uint32()
            queried = bool(get_exit_code(handle, ctypes.byref(exit_code)))
            return not queried or exit_code.value == 259
        finally:
            close_handle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True
