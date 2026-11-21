import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.ui import UIApp

have = {m for m, _ in inspect.getmembers(UIApp, inspect.isfunction)}

pat = re.compile(r"self\.ui\.(\w+)\s*\(")
src = open("health_guard/controller.py", encoding="utf-8").read()
missing = []
names = set()

for line, ln in enumerate(src.splitlines(), 1):
    for name in pat.findall(ln):
        names.add(name)
        if name not in have:
            missing.append(f"controller.py:{line}  self.ui.{name}()")

print(f"checked {len(names)} distinct UIApp call names from controller")
if missing:
    print("MISSING:")
    for m in missing:
        print("  ", m)
    sys.exit(1)
print("OK: every self.ui.X() in controller resolves")

# same for tray.py / ui files calling self.controller methods
pat2 = re.compile(r"self\.controller\.(\w+)\s*\(")
from health_guard.controller import Controller as C

havec = {m for m, _ in inspect.getmembers(C, inspect.isfunction)}
init_src = inspect.getsource(C.__init__)
dyn = set(re.findall(r"self\.(\w+)\s*=", init_src))
miss2 = []
for fn in sorted(os.listdir("health_guard")):
    if not fn.endswith(".py"):
        continue
    t = open(os.path.join("health_guard", fn), encoding="utf-8").read()
    for line, ln in enumerate(t.splitlines(), 1):
        for n in pat2.findall(ln):
            if n not in havec and n not in dyn:
                miss2.append(f"health_guard/{fn}:{line}  self.controller.{n}()")

print(f"checked controller attr access in {sum(1 for _ in os.listdir('health_guard') if _.endswith('.py'))} files")
if miss2:
    print("MISSING:")
    for m in miss2:
        print("  ", m)
    sys.exit(1)
print("OK: no UI file references a missing Controller attribute")
