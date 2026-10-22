#!/usr/bin/env bash
# Установка бэкенда kbdguard (демон + CLI).
#
#   sudo ./install.sh              установить
#   sudo ./install.sh --uninstall  удалить
#
# Плагин для Noctalia Shell ставится отдельно из корня репозитория: make install-plugin
set -euo pipefail

BIN=/usr/local/bin/kbdguard
CONF_DIR=/etc/kbdguard
STATE_DIR=/var/lib/kbdguard
UNIT=/etc/systemd/system/kbdguard.service
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "нужен root: sudo ./install.sh" >&2
  exit 1
fi

TARGET_USER="${SUDO_USER:-${KB_USER:-}}"
if [ -z "$TARGET_USER" ] && [ "$1" != "--uninstall" ]; then
  echo "не удалось определить пользователя сессии, задайте явно: sudo KB_USER=имя ./install.sh" >&2
  exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
  systemctl disable --now kbdguard 2>/dev/null || true
  rm -f "$UNIT" "$BIN"
  systemctl daemon-reload
  echo "удалено. Конфиг оставлен: $CONF_DIR, состояние: $STATE_DIR"
  exit 0
fi

echo "== зависимости =="
if ! python3 -c "import evdev" 2>/dev/null; then
  if command -v pacman >/dev/null; then
    pacman -S --needed --noconfirm python-evdev
  else
    echo "установите python-evdev средствами вашего дистрибутива" >&2
    exit 1
  fi
fi
python3 -c "import evdev; print('python-evdev', evdev.__version__ if hasattr(evdev, '__version__') else 'ok')"

echo
echo "== файлы =="
install -m 755 "$SRC_DIR/kbdguard.py" "$BIN"
mkdir -p "$CONF_DIR" "$STATE_DIR"
if [ -f "$CONF_DIR/config.toml" ]; then
  echo "конфиг уже есть, не трогаю: $CONF_DIR/config.toml"
else
  install -m 644 "$SRC_DIR/config.toml" "$CONF_DIR/config.toml"
  echo "конфиг: $CONF_DIR/config.toml"
fi
sed "s/__USER__/$TARGET_USER/" "$SRC_DIR/kbdguard.service" > "$UNIT"
chmod 644 "$UNIT"

echo
echo "== конфликт с keyd =="
if systemctl is-active --quiet keyd 2>/dev/null; then
  echo "keyd держит устройство эксклюзивно (EVIOCGRAB), останавливаю его"
  systemctl disable --now keyd
else
  echo "keyd не активен — ок"
fi

echo
echo "== запуск =="
systemctl daemon-reload
systemctl enable --now kbdguard
sleep 2
systemctl is-active kbdguard

echo
echo "== состояние =="
"$BIN" status || true

echo
echo "Готово."
echo "  CLI:        kbdguard status | toggle | on | off | devices | protect on|off"
echo "  Конфиг:     $CONF_DIR/config.toml (после правки: systemctl restart kbdguard)"
echo "  Плагин:     из корня репозитория: make install-plugin"
echo "  Удаление:   sudo $SRC_DIR/install.sh --uninstall"
