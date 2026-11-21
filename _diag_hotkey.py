import ctypes
import sys
import time

from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
VK_U = 0x55
VK_X = 0x58
WM_HOTKEY = 0x0312

mods = MOD_CONTROL | MOD_ALT | MOD_SHIFT


def try_reg(hwnd_desc, hwnd, vk, hid):
    err_before = ctypes.get_last_error()
    ok = user32.RegisterHotKey(wintypes.HWND(hwnd), hid, mods, vk)
    err = ctypes.get_last_error()
    print(f"  hwnd={hwnd_desc:16s} vk=0x{vk:02x} -> ok={bool(ok)} "
          f"error={err if not ok else '(none)'}")
    return bool(ok)


print("--- A: hWnd=NULL on a fresh (non-pumping) main thread ---")
a1 = try_reg("NULL", None, VK_U, 1)

print("--- B: hWnd=NULL right after a Tk window is created ---")
import tkinter as tk

root = tk.Tk()
root.withdraw()
b1 = try_reg("NULL", None, VK_U, 1)
try_reg("NULL", None, VK_X, 2)
try_reg("NULL", None, VK_H, 3)
root.destroy()

print("--- C: hWnd=real window handle ---")
root = tk.Tk()
hwnd_val = ctypes.windll.user32.GetParent(
    int(root.winfo_id(), 16)
)
print("  window handle =", hwnd_val)
c1 = try_reg(f"HWND({hwnd_val})", hwnd_val, VK_U, 10)

print("--- D: duplicate registration (same keys, NULL hwnd) ---")
d1 = try_reg("NULL", None, VK_U, 20)

print("--- E: thread WITHOUT a message queue (daemon thread) ---")
import threading

results = {}


def in_thread():
    results["ok"] = user32.RegisterHotKey(None, 30, mods, VK_S)
    results["err"] = ctypes.get_last_error()


t = threading.Thread(target=in_thread, daemon=True)
t.start()
t.join()
print(f"  ok={results.get('ok')} error={results.get('err')}")

print()
print("error code reference:")
print("  0 = success, 1409 = ERROR_HOTKEY_ALREADY_REGISTERED,")
print("  1410 = ERROR_NOT_FOUND (key not registered),")
print("  1411 = ERROR_ACCESS_DENIED")
print()
print("SUMMARY:")
print(f"  A (NULL, no Tk):       {a1}")
print(f"  B (NULL, with Tk):     {b1}")
print(f"  C (real HWND):         {c1}")
print(f"  D (duplicate NULL):    {d1}")
print(f"  E (no msg queue thread): {bool(results.get('ok'))}")
