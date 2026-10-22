#!/usr/bin/env python3
"""Проверки репозитория: python-синтаксис, JSON, bash -n."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERRORS = []


def check_python() -> None:
    src = ROOT / "backend" / "kbdguard.py"
    result = subprocess.run([sys.executable, "-m", "py_compile", str(src)])
    if result.returncode != 0:
        ERRORS.append(f"python: {src}")
    else:
        print(f"ok  python   {src.relative_to(ROOT)}")


def check_json() -> None:
    for rel in ("kbdguard/manifest.json", "registry.json",
                "kbdguard/i18n/en.json", "kbdguard/i18n/ru.json"):
        path = ROOT / rel
        try:
            json.loads(path.read_text(encoding="utf-8"))
            print(f"ok  json     {rel}")
        except (OSError, json.JSONDecodeError) as exc:
            ERRORS.append(f"json: {rel}: {exc}")


def check_bash() -> None:
    path = ROOT / "backend" / "install.sh"
    result = subprocess.run(["bash", "-n", str(path)])
    if result.returncode != 0:
        ERRORS.append(f"bash: {path.name}")
    else:
        print(f"ok  bash     {path.relative_to(ROOT)}")


def check_i18n_keys() -> None:
    en = json.loads((ROOT / "kbdguard" / "i18n" / "en.json").read_text(encoding="utf-8"))
    ru = json.loads((ROOT / "kbdguard" / "i18n" / "ru.json").read_text(encoding="utf-8"))

    def flat(node, prefix=""):
        out = {}
        for key, val in node.items():
            full = f"{prefix}{key}"
            if isinstance(val, dict):
                out.update(flat(val, full + "."))
            else:
                out[full] = val
        return out

    en_keys, ru_keys = set(flat(en)), set(flat(ru))
    missing_ru = en_keys - ru_keys
    missing_en = ru_keys - en_keys
    if missing_ru:
        ERRORS.append(f"i18n: нет в ru.json: {sorted(missing_ru)}")
    if missing_en:
        ERRORS.append(f"i18n: нет в en.json: {sorted(missing_en)}")
    if not missing_ru and not missing_en:
        print(f"ok  i18n     {len(en_keys)} ключей совпадают")


def check_manifest_id() -> None:
    manifest = json.loads((ROOT / "kbdguard" / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("id") != "kbdguard":
        ERRORS.append("manifest: id должен совпадать с именем папки (kbdguard)")
    entry_points = manifest.get("entryPoints", {})
    for kind, filename in entry_points.items():
        path = ROOT / "kbdguard" / filename
        if not path.exists():
            ERRORS.append(f"manifest: entryPoints.{kind} → нет файла {filename}")
    defaults = manifest.get("metadata", {}).get("defaultSettings", {})
    if "cliPath" not in defaults:
        ERRORS.append("manifest: нет defaultSettings.cliPath")
    print(f"ok  manifest entryPoints={len(entry_points)}")


def main() -> int:
    check_python()
    check_json()
    check_bash()
    check_i18n_keys()
    check_manifest_id()

    if ERRORS:
        print("\nОШИБКИ:")
        for err in ERRORS:
            print("  -", err)
        return 1
    print("\nвсё чисто")
    return 0


if __name__ == "__main__":
    sys.exit(main())
