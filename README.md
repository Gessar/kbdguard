# kbdguard

Выключение встроенной клавиатуры ноутбука одним жестом — иконка в баре
[Noctalia Shell](https://github.com/noctalia-dev/noctalia-shell), панель с выбором
устройств и защитой от «остаться без клавиатуры».

Жест: **зажать Ctrl и нажать Alt** на встроенной клавиатуре (годится любая Alt,
порядок и интервал между нажатиями не важны). Третья клавиша жест отменяет, поэтому
`Ctrl+Alt+T` и подобные комбинации работают как обычно.

Когда встроенная выключена, её события не доходят до композитора вообще:
не работают ни буквы, ни Fn-медиа, ни brightness. Внешняя клавиатура при этом
не затрагивается — она вообще не попадает под управление демоном.

```
┌─ бар ────────────────────────────────────────────┐
│  ...  ⌨(off)                                     │
└──────────────────────────────────────────────────┘
        │ клик — переключить, правый клик — меню, панель
        ▼
   панель: состояние, список устройств, защита, сочетание
```

## Почему это не «плагин niri»

В niri нет системы плагинов и нет управления input-устройствами: в официальной
документации (niri-wm.github.io/niri) слово *plugin* встречается один раз — про
VST-плагины в wine, а `niri msg` не знает подкоманды `inputs`. Поэтому отключение
клавиатуры делается внешним демоном на уровне evdev, а UI живёт в баре Noctalia.
Для niri есть только официальный путь интеграции — keybind, который дергает CLI
(см. ниже).

## Состав

| Часть | Что делает |
| --- | --- |
| `backend/kbdguard.py` | демон + CLI. Перехват устройств (EVIOCGRAB), распознавание жеста, IPC по unix-сокету |
| `kbdguard/` | плагин Noctalia: `Main.qml` (состояние), `BarWidget.qml`, `Panel.qml`, `Settings.qml`, `i18n/` |
| `registry.json` | индекс для подключения репозитория как custom source |

## Установка

Нужны: Python 3.11+ (`tomllib`), `python-evdev`, Noctalia Shell 4.x.

```bash
git clone https://github.com/Gessar/kbdguard.git
cd kbdguard

make install-backend     # sudo: демон + CLI + systemd-юнит
make install-plugin      # копирует плагин в ~/.config/noctalia/plugins/kbdguard

kbdguard status          # проверка
```

Затем в Noctalia: **Настройки → Bar → Widgets → Keyboard Guard** (добавить виджет).
Если плагин не появился в списке — перезапустите оболочку (`qs -c noctalia-shell`)
или пересканируйте плагины в её настройках.

Если установлен `keyd` и он держит ту же клавиатуру — `install.sh` остановит его:
два демона не могут держать одно устройство, `EVIOCGRAB` эксклюзивен.

## CLI

```bash
kbdguard status            # человекочитаемо
kbdguard status --json     # для плагина/скриптов
kbdguard toggle
kbdguard off | on
kbdguard devices           # JSON со списком клавиатур
kbdguard device /dev/input/event3 off
kbdguard protect on|off    # защита последней клавиатуры
kbdguard reload            # перечитать конфиг без рестарта
```

## Интеграция с niri

Официальный способ — биндинг на CLI (работает и с внешней клавиатуры):

```kdl
// ~/.config/niri/cfg/keybinds.kdl
binds {
    Mod+Shift+K { spawn "kbdguard" "toggle"; }
    Mod+Shift+Ctrl+K { spawn "kbdguard" "off"; }
}
```

IPC Noctalia (если хочется дергать виджет, а не CLI):

```bash
qs ipc call plugin:kbdguard toggle
qs ipc call plugin:kbdguard off
qs ipc call plugin:kbdguard refreshStatus
```

## Конфиг

`/etc/kbdguard/config.toml`

```toml
[general]
protect_last_keyboard = true   # запретить отключение, если клавиатура останется одна
start_disabled = false
notify = true

[gesture]
group1 = ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"]   # зажать любую из
group2 = ["KEY_LEFTALT", "KEY_RIGHTALT"]     # нажать любую из
label = "Ctrl + Alt"                         # подпись в панели

[devices]
mutable = []                  # пусто = все внутренние (i8042/ISA)
exclude = []                  # что не трогать никогда
```

После правки: `sudo systemctl restart kbdguard` (не `reload` — перечитывание
конфига есть в CLI, но рестарт надёжнее и сбрасывает состояние в «включено»).

## Как это работает

1. Демон перечисляет клавиатуры через evdev и отбирает «внутренние» (шина i8042/ISA).
2. Управляемое устройство захватывается **один раз при старте** (`EVIOCGRAB`), а наружу
   его события идут через собственный uinput-двойник `kbdguard-forward …`. Поэтому
   нажатие и отпускание любого модификатора приходит в композитор с одного и того же
   устройства — «залипших» Ctrl/Alt (из-за которых ломается вторая клавиатура) не бывает.
3. Жест `Ctrl + Alt` распознаётся по потоку самого устройства; третья клавиша отменяет жест,
   поэтому `Ctrl+Alt+T` и подобные комбинации не переключают ничего.
4. «Выключено» = перестать пересылать события + отпустить в композиторе всё, что мы
   переслали как нажатое. Захват при этом не снимается, так что повторный жест
   (и жест на выключенной клавиатуре) продолжает работать.
5. Жест действует только на управляемые устройства. Внешнюю клавиатуру нельзя
   заглушить ни жестом, ни CLI, ни панелью — в `_mute()` стоит отдельный запрет.

## Безопасность

- Демон работает от root (нужен доступ к `/dev/input/*` и `/dev/uinput`), но умеет
  ровно две вещи: перехватывать выбранные клавиатуры и пересылать их события. Сети,
  загрузки файлов и выполнения внешних команд в нём нет.
- Сокет управления `/run/kbdguard/control.sock` — `root:wheel`, режим `0660`. Если группу
  выставить не удалось, права остаются `0660 root:root` (fail closed), а не `0666`.
- Поверх прав файла каждый клиент проверяется по `SO_PEERCRED`: команды принимаются
  только от `uid 0` и от пользователя графической сессии (`KB_USER` в юните).
  В журнал пишется источник команды: `IPC cmd=toggle от pid=… uid=…`.
- Защита `protect_last_keyboard` не даёт оставить систему без клавиатуры: если после
  отключения не останется ни одной включённой, операция отклоняется.
- Остановка сервиса (`systemctl stop kbdguard`) снимает захват автоматически при
  закрытии устройства — клавиатура сразу возвращается в обычный режим.
- В репозитории нет секретов, токенов, персональных путей, e-mail и серийных номеров
  устройств; телеметрии и обращений в сеть нет. Проверяется `scripts/check.py`
  и обычным `grep` по перечисленным шаблонам.

## Защита от «остаться без клавиатуры»

`protect_last_keyboard = true` (по умолчанию, дублируется галочкой в панели):
если после отключения в системе не останется ни одной включённой клавиатуры,
демон откажет и вернёт ошибку — её видно тостом в Noctalia. Значение галочки
сохраняется в `/var/lib/kbdguard/overrides.json`, не меняя `/etc`.

## Отладка

```bash
systemctl status kbdguard
journalctl -u kbdguard -f          # лог жестов: "жест Ctrl+Alt", "жест отменён"
kbdguard status --json | jq
qs log -c noctalia-shell | grep -i kbdguard     # лог QML-части
```

Типовые причины:

| Симптом | Причина |
| --- | --- |
| `демон kbdguard не запущен` | `sudo systemctl start kbdguard`; проверить `journalctl -u kbdguard` |
| Жест не срабатывает | в `group2` клавиша, которой нет на клавиатуре (например, правый Ctrl на ноутбуках часто отсутствует) — проверьте коды через `wev` |
| Пустой список устройств | клавиатура не определяется как внутренняя: впишите её имя в `[devices] mutable` |
| Ничего не отключается, в логе «защита» | включена защита, а включённая клавиатура одна — подключите внешнюю |

## Удаление

```bash
sudo bash backend/install.sh --uninstall
rm -rf ~/.config/noctalia/plugins/kbdguard
```

## Ограничения

- Wayland/X11 не важно — перехват на уровне ядра, но UI требует Noctalia Shell.
- Демон работает от root: `/dev/input/*` и `/dev/uinput` доступны только root.
- Сокет управления `/run/kbdguard/control.sock` — `root:wheel 0660` + проверка uid.
- Гибернация/перезагрузка возвращают клавиатуру включённой (`start_disabled = false`).
- LED-состояние (CapsLock/NumLock) через uinput-двойник не пересылается: сама клавиша
  может не загораться, при этом в системе раскладка CapsLock работает как обычно.
- Внешние клавиатуры демон не перехватывает вообще — только читает их для распознавания
  жеста, и жест на них игнорируется.

## English

Noctalia Shell plugin + small root daemon that turns the laptop's internal keyboard
off with a **Ctrl+Alt** gesture (hold Ctrl, press Alt — any Alt, any timing; a third
key cancels the gesture). Bar widget, panel with per-device switches, and protection
against disabling the last remaining keyboard. External keyboards are never touched.
niri has no plugin system and no input-device IPC, so the switching happens in an
evdev daemon and the UI lives in the Noctalia bar.

## Лицензия

MIT — см. [LICENSE](LICENSE).
