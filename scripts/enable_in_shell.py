#!/usr/bin/env python3
"""Включает плагин kbdguard и добавляет его виджет в правую секцию бара Noctalia.

Идемпотентно: повторный запуск ничего не дублирует. Бэкапы уже сняты в /tmp.
"""
import json
from pathlib import Path

SETTINGS = Path.home() / ".config/noctalia/settings.json"
PLUGINS = Path.home() / ".config/noctalia/plugins.json"

WIDGET_ID = "plugin:kbdguard"
WIDGET_ENTRY = {
    "id": WIDGET_ID,
    "defaultSettings": {
        "cliPath": "kbdguard",
        "hideWhenUnavailable": False,
        "iconColor": "none",
        "pollIntervalMs": 2000,
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4, sort_keys=True) + "\n",
                    encoding="utf-8")


def enable_plugin() -> str:
    data = load(PLUGINS)
    states = data.setdefault("states", {})
    states["kbdguard"] = {"enabled": True, "sourceUrl": ""}
    dump(PLUGINS, data)
    return f"plugins.json: states.kbdguard.enabled = true ({len(states)} плагинов в states)"


def add_widget() -> str:
    data = load(SETTINGS)
    bar = data.get("bar", {})
    widgets = bar.get("widgets", {})
    right = widgets.get("right")
    if right is None:
        widgets["right"] = right = []

    for entry in right:
        if isinstance(entry, dict) and entry.get("id") == WIDGET_ID:
            return "settings.json: виджет уже в правой секции бара"

    insert_at = len(right)
    for idx, entry in enumerate(right):
        if isinstance(entry, dict) and entry.get("id") == "Tray":
            insert_at = idx + 1
            break

    right.insert(insert_at, WIDGET_ENTRY)
    dump(SETTINGS, data)
    return f"settings.json: виджет вставлен в right[{insert_at}] (всего {len(right)} виджетов)"


def main() -> None:
    print(enable_plugin())
    print(add_widget())


if __name__ == "__main__":
    main()
