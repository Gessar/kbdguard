#!/usr/bin/env python3
"""kbdguard — переключатель встроенной клавиатуры для niri/Wayland.

niri не имеет системы плагинов и не умеет управлять input-устройствами
(`niri msg` не знает подкоманды `inputs`), поэтому переключение делается
внешним демоном на уровне evdev, а UI — иконкой SNI в трее и/или
niri-keybind'ом на CLI.

Компоненты в одном файле:
    kbdguard daemon   системный сервис (root): перехват устройств, жест, IPC
    kbdguard tray     иконка в трее (Ayatana AppIndicator / SNI)
    kbdguard on|off|toggle|status|devices|reload   CLI-клиент к демону

Механика перехвата: EVIOCGRAB держит выбранную клавиатуру эксклюзивно,
поэтому её события не доходят до композитора. Чтобы при переключении не
оставались «залипшие» модификаторы, отпускание уже нажатых клавиш
отправляется в композитор через отдельное uinput-устройство.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import pwd
import queue
import selectors
import socket
import struct
import subprocess
import sys
import threading
import time
import tomllib

SOCKET_PATH = "/run/kbdguard/control.sock"
SOCKET_GROUP = "wheel"
CONFIG_PATH = "/etc/kbdguard/config.toml"
OVERRIDES_PATH = "/var/lib/kbdguard/overrides.json"

DEFAULT_CONFIG = {
    "general": {
        "protect_last_keyboard": True,
        "start_disabled": False,
        "notify": True,
    },
    "gesture": {
        "group1": ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"],
        "group2": ["KEY_LEFTALT", "KEY_RIGHTALT"],
        "label": "Ctrl + Alt",
    },
    "devices": {
        "mutable": [],
        "exclude": [],
    },
}


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# --------------------------------------------------------------------------
# конфиг
# --------------------------------------------------------------------------
def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, val in extra.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(path: str = CONFIG_PATH) -> dict:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log(f"config: {path}: {exc}, использую дефолт")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return deep_merge(DEFAULT_CONFIG, data)


def load_overrides(path: str = OVERRIDES_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_overrides(data: dict, path: str = OVERRIDES_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        log(f"overrides: не сохранил ({exc})")


def notify_user(text: str, cfg: dict, user: str | None = None) -> None:
    """Уведомление в графическую сессию пользователя (демон работает от root)."""
    if not cfg.get("general", {}).get("notify", True):
        return
    user = user or os.environ.get("KB_USER") or ""
    if not user:
        return
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return
    runtime = f"/run/user/{uid}"
    try:
        subprocess.run(
            ["runuser", "-u", user, "--", "env",
             f"XDG_RUNTIME_DIR={runtime}",
             f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
             "notify-send", "-a", "kbdguard", "-t", "1500",
             "Клавиатура", text],
            timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# устройства
# --------------------------------------------------------------------------
def _evdev():
    import evdev  # локальный импорт: CLI-часть работает и без прав на /dev/input
    return evdev


def is_keyboard(dev) -> bool:
    ecodes = _evdev().ecodes
    caps = dev.capabilities(absinfo=False)
    keys = set(caps.get(ecodes.EV_KEY, []))
    return ecodes.KEY_A in keys and ecodes.KEY_Z in keys and ecodes.KEY_SPACE in keys


def is_internal(dev) -> bool:
    """Внутренняя (платформенная) клавиатура: i8042/ISA или характерное имя."""
    name = (dev.name or "").lower()
    if dev.info.bustype in (0x10, 0x11):  # BUS_ISA, BUS_I8042
        return True
    return any(mark in name for mark in ("at translated", "thinkpad", "ideapad", "internal"))


class Keyboard:
    def __init__(self, dev):
        self.dev = dev
        self.path = dev.path
        self.name = dev.name
        self.internal = is_internal(dev)
        self.muted = False
        self.held: set[int] = set()
        self.forwarded: set[int] = set()
        self.virtual = None      # uinput-двойник, через который идут события наружу
        self.grabbed = False
        self.armed = False

    def info(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "internal": self.internal,
            "muted": self.muted,
        }


# --------------------------------------------------------------------------
# демон
# --------------------------------------------------------------------------
class Daemon:
    def __init__(self, config_path: str = CONFIG_PATH):
        evdev = _evdev()
        self.ecodes = evdev.ecodes
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.overrides = load_overrides()
        if "protect_last_keyboard" in self.overrides:
            self.cfg["general"]["protect_last_keyboard"] = bool(self.overrides["protect_last_keyboard"])
        self.cmd_queue: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.keyboards: dict[str, Keyboard] = {}
        self.selector = selectors.DefaultSelector()
        self._refresh_gesture()

    def _refresh_gesture(self) -> None:
        def to_codes(names):
            codes = set()
            for name in names:
                code = getattr(self.ecodes, str(name).upper(), None)
                if isinstance(code, int):
                    codes.add(code)
            return codes

        self.group1 = to_codes(self.cfg["gesture"].get("group1", []))
        self.group2 = to_codes(self.cfg["gesture"].get("group2", []))
        self.pair = self.group1 | self.group2

    # -- инфраструктура ---------------------------------------------------
    def _make_virtuals(self) -> None:
        """Один раз захватить управляемые устройства и создать им uinput-двойники.

        Наружу события идут через двойник, поэтому нажатие и отпускание любого
        модификатора приходит в композитор с ОДНОГО устройства. Это устраняет
        «залипшие» Ctrl/Alt, из-за которых ломалась внешняя клавиатура.
        """
        evdev = _evdev()
        for kb in self._mutable():
            if kb.virtual is not None or kb.grabbed:
                continue
            caps = kb.dev.capabilities(absinfo=False)
            events = {self.ecodes.EV_KEY: caps.get(self.ecodes.EV_KEY, [])}
            msc = caps.get(self.ecodes.EV_MSC)
            if msc:
                events[self.ecodes.EV_MSC] = msc
            try:
                kb.virtual = evdev.UInput(
                    events=events,
                    name=f"kbdguard-forward {kb.name[:18]}",
                    version=1,
                )
            except OSError as exc:
                log(f"{kb.name}: не создал uinput-двойник ({exc})")
                continue
            try:
                kb.dev.grab()
                kb.grabbed = True
                log(f"{kb.name}: захвачено, события идут через uinput-двойник")
            except OSError as exc:
                log(f"{kb.name}: захват не удался ({exc}) — режим наблюдения")

    def detect(self) -> None:
        evdev = _evdev()
        self.keyboards = {}
        for path in evdev.list_devices():
            dev = None
            try:
                dev = evdev.InputDevice(path)
                if (dev.name or "").startswith("kbdguard"):
                    dev.close()          # свои же uinput-двойники не считаем
                    continue
                if not is_keyboard(dev):
                    dev.close()
                    continue
                kb = Keyboard(dev)
            except Exception:  # noqa: BLE001
                if dev is not None:
                    try:
                        dev.close()
                    except Exception:  # noqa: BLE001
                        pass
                continue
            self.keyboards[path] = kb

    def _mutable(self) -> list[Keyboard]:
        cfg_dev = self.cfg["devices"]
        explicit = [str(x).lower() for x in cfg_dev.get("mutable", [])]
        excluded = [str(x).lower() for x in cfg_dev.get("exclude", [])]
        out = []
        for kb in self.keyboards.values():
            low_name = (kb.name or "").lower()
            if any(x in low_name or x in kb.path.lower() for x in excluded):
                continue
            if explicit:
                if any(x in low_name or x in kb.path.lower() for x in explicit):
                    out.append(kb)
            elif kb.internal:
                out.append(kb)
        return out

    def _is_mutable(self, kb: Keyboard) -> bool:
        return any(kb is item for item in self._mutable())

    def _apply_start_state(self) -> None:
        if not self.cfg["general"].get("start_disabled", False):
            return
        for kb in self._mutable():
            self._mute(kb, mute=True, notify=False)

    # -- mute/unmute ------------------------------------------------------
    def _release_held(self, kb: Keyboard) -> None:
        """Отпустить в композиторе всё, что мы переслали как нажатое."""
        if kb.virtual is None:
            return
        for code in list(kb.forwarded):
            kb.virtual.write(self.ecodes.EV_KEY, code, 0)
        kb.virtual.syn()
        kb.forwarded.clear()

    def _unmuted_count(self) -> int:
        return sum(1 for kb in self.keyboards.values() if not kb.muted)

    def _protected(self, targets: list[Keyboard]) -> bool:
        if not self.cfg["general"].get("protect_last_keyboard", True):
            return False
        remaining = [kb for kb in self.keyboards.values() if not kb.muted and kb not in targets]
        return len(remaining) == 0

    def _mute(self, kb: Keyboard, mute: bool, notify: bool = True) -> tuple[bool, str]:
        if mute and kb.muted:
            return True, "уже отключена"
        if not mute and not kb.muted:
            return True, "уже включена"
        # глушить можно только управляемые устройства: внешнюю клавиатуру
        # не должен отключать ни жест, ни CLI, ни панель
        if mute and not self._is_mutable(kb):
            return False, f"{kb.name}: устройство не управляемое (см. [devices] mutable)"
        if mute and self._protected([kb]):
            return False, "защита: это последняя клавиатура в системе"
        if kb.virtual is not None and kb.grabbed:
            # штатный путь: устройство уже захвачено, наружу идёт через двойник
            kb.muted = mute
            self._release_held(kb)
        else:
            # режим наблюдения (захват не удался) — старый путь через grab
            try:
                if mute:
                    kb.dev.grab()
                    kb.grabbed = True
                    kb.muted = True
                    self._release_held(kb)
                else:
                    self._release_held(kb)
                    kb.dev.ungrab()
                    kb.grabbed = False
                    kb.muted = False
            except OSError as exc:
                code = exc.errno if exc.errno is not None else -1
                return False, f"{errno.errorcode.get(code, code)}: {exc.strerror or exc}"

        state = "выключена" if kb.muted else "включена"
        log(f"{kb.name}: {state}")
        if notify:
            notify_user(f"{kb.name}: {state}", self.cfg)
        return True, state

    # -- IPC --------------------------------------------------------------
    def _start_ipc(self) -> None:
        os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        try:
            gid = pwd.getpwnam("root").pw_gid
            for grp in __import__("grp").getgrall():
                if grp.gr_name == SOCKET_GROUP:
                    gid = grp.gr_gid
                    break
            os.chown(SOCKET_PATH, 0, gid)
            os.chmod(SOCKET_PATH, 0o660)
        except OSError as exc:
            # fail closed: без группы доступ только у root
            log(f"IPC: не смог выставить group={SOCKET_GROUP} ({exc}), оставляю 0660 root:root")
            os.chmod(SOCKET_PATH, 0o660)
        srv.listen(8)
        threading.Thread(target=self._ipc_loop, args=(srv,), daemon=True).start()

    def _peer_check(self, conn: socket.socket) -> tuple[bool, int, int]:
        """Авторизация клиента по SO_PEERCRED: root или пользователь сессии.

        Прав на файл сокета недостаточно (группа wheel фактически равна root),
        поэтому uid проверяется на каждом соединении.
        """
        try:
            creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                    struct.calcsize("3i"))
            pid, uid, _gid = struct.unpack("3i", creds)
        except OSError:
            return False, -1, -1
        if uid == 0:
            return True, pid, uid
        user = os.environ.get("KB_USER") or ""
        if user:
            try:
                if pwd.getpwnam(user).pw_uid == uid:
                    return True, pid, uid
            except KeyError:
                pass
        return False, pid, uid

    def _ipc_loop(self, srv: socket.socket) -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                raw = None
                try:
                    conn.settimeout(3)
                    raw = conn.makefile("rwb", buffering=0)
                    line = raw.readline()
                    if not line:
                        continue
                    req = json.loads(line.decode() or "{}")
                    allowed, pid, uid = self._peer_check(conn)
                    if not allowed:
                        log(f"IPC: доступ запрещён pid={pid} uid={uid} cmd={req.get('cmd')}")
                        raw.write((json.dumps({"ok": False, "error": "доступ запрещён"},
                                              ensure_ascii=False) + "\n").encode())
                        continue
                    if req.get("cmd") != "status":
                        log(f"IPC cmd={req.get('cmd')} от pid={pid} uid={uid}")
                    resp = self._dispatch(req)
                    raw.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
                except Exception as exc:  # noqa: BLE001
                    if raw is not None:
                        try:
                            raw.write((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
                        except Exception:  # noqa: BLE001
                            pass

    def _dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd", "")
        if cmd == "status":
            return {"ok": True, "state": self._status()}
        if cmd in ("toggle", "on", "off", "device", "reload", "protect", "shutdown"):
            self.cmd_queue.put(req)
            return {"ok": True, "queued": cmd}
        return {"ok": False, "error": f"неизвестная команда: {cmd}"}

    def _status(self) -> dict:
        mutable = self._mutable()
        return {
            "gesture": self.cfg["gesture"].get("label", "Ctrl + Alt"),
            "protect_last_keyboard": bool(self.cfg["general"].get("protect_last_keyboard", True)),
            "config_path": self.config_path,
            "socket": SOCKET_PATH,
            "keyboards": [kb.info() | {"mutable": kb in mutable} for kb in self.keyboards.values()],
            "muted": any(kb.muted for kb in mutable),
            "unmuted_total": self._unmuted_count(),
        }

    # -- обработка команд --------------------------------------------------
    def _handle_command(self, req: dict) -> None:
        cmd = req.get("cmd")
        mutable = self._mutable()

        if cmd == "toggle":
            target_mute = not any(kb.muted for kb in mutable)
            for kb in mutable:
                ok, msg = self._mute(kb, target_mute)
                if not ok:
                    log(f"{cmd}: {msg}")
                    notify_user(msg, self.cfg)
                    break
        elif cmd in ("on", "off"):
            for kb in mutable:
                ok, msg = self._mute(kb, cmd == "off")
                if not ok:
                    log(f"{cmd}: {msg}")
                    notify_user(msg, self.cfg)
                    break
        elif cmd == "device":
            path = req.get("path", "")
            kb = self.keyboards.get(path)
            if kb is None:
                log(f"device: нет такого устройства {path}")
                return
            ok, msg = self._mute(kb, bool(req.get("muted")))
            if not ok:
                notify_user(msg, self.cfg)
        elif cmd == "reload":
            self.cfg = load_config(self.config_path)
            self.overrides = load_overrides()
            if "protect_last_keyboard" in self.overrides:
                self.cfg["general"]["protect_last_keyboard"] = bool(
                    self.overrides["protect_last_keyboard"])
            self._refresh_gesture()
            log("конфиг перечитан")
        elif cmd == "protect":
            value = bool(req.get("value", True))
            self.cfg["general"]["protect_last_keyboard"] = value
            self.overrides["protect_last_keyboard"] = value
            save_overrides(self.overrides)
            log(f"защита последней клавиатуры: {'вкл' if value else 'выкл'}")
        elif cmd == "shutdown":
            log("получена команда shutdown")
            self.stop()

    # -- событийный цикл ---------------------------------------------------
    def _on_key(self, kb: Keyboard, code: int, value: int) -> None:
        if value == 2:
            return

        if value == 1:
            both_before = bool(kb.held & self.group1) and bool(kb.held & self.group2)
            kb.held.add(code)
            both_now = bool(kb.held & self.group1) and bool(kb.held & self.group2)
            if both_now and not both_before:
                if not self._is_mutable(kb):
                    kb.armed = False
                    log(f"{kb.name}: жест проигнорирован — устройство не управляемое")
                else:
                    kb.armed = True
                    log(f"{kb.name}: жест {self.cfg['gesture'].get('label')}")
            elif kb.armed and code not in self.pair:
                kb.armed = False
                log(f"{kb.name}: жест отменён третьей клавишей")
            return

        kb.held.discard(code)
        if kb.armed and code in self.pair:
            kb.armed = False
            self._mute(kb, not kb.muted)

    def run(self) -> None:
        self.detect()
        self._make_virtuals()
        self._apply_start_state()
        self._start_ipc()

        for kb in self.keyboards.values():
            try:
                self.selector.register(kb.dev.fd, selectors.EVENT_READ, kb)
            except (OSError, ValueError):
                continue

        names = ", ".join(f"{kb.name}{'[внутр]' if kb.internal else ''}"
                          for kb in self.keyboards.values())
        log(f"устройства: {names or 'нет'}")
        log(f"управляемые: {', '.join(kb.name for kb in self._mutable()) or 'нет'}")
        log(f"жест: {self.cfg['gesture'].get('label')}; защита последней: "
            f"{self.cfg['general'].get('protect_last_keyboard')}")
        log(f"IPC: {SOCKET_PATH}")

        while True:
            while True:
                try:
                    req = self.cmd_queue.get_nowait()
                except queue.Empty:
                    break
                self._handle_command(req)

            for key, _ in self.selector.select(timeout=0.2):
                kb: Keyboard = key.data
                try:
                    for ev in kb.dev.read():
                        if ev.type == self.ecodes.EV_KEY:
                            self._on_key(kb, ev.code, ev.value)
                        if kb.virtual is not None and kb.grabbed and not kb.muted:
                            if ev.type == self.ecodes.EV_KEY:
                                if ev.value == 1:
                                    kb.forwarded.add(ev.code)
                                elif ev.value == 0:
                                    kb.forwarded.discard(ev.code)
                            kb.virtual.write_event(ev)
                except OSError as exc:
                    log(f"{kb.name}: ошибка чтения ({exc}), пересканирую")
                    try:
                        self.selector.unregister(kb.dev.fd)
                    except (KeyError, ValueError):
                        pass
                    self.detect()
                    self._make_virtuals()
                    for fresh in self.keyboards.values():
                        try:
                            self.selector.register(fresh.dev.fd, selectors.EVENT_READ, fresh)
                        except (OSError, ValueError):
                            pass

    def stop(self) -> None:
        for kb in self.keyboards.values():
            if kb.muted:
                self._release_held(kb)
                kb.muted = False
            if kb.grabbed:
                try:
                    kb.dev.ungrab()
                except OSError:
                    pass
                kb.grabbed = False
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
        sys.exit(0)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def rpc(req: dict, timeout: float = 3.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect(SOCKET_PATH)
        except (FileNotFoundError, ConnectionRefusedError):
            return {"ok": False, "error": "демон kbdguard не запущен"}
        sock.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    try:
        return json.loads(data.decode())
    except json.JSONDecodeError:
        return {"ok": False, "error": f"некорректный ответ демона: {data[:200]!r}"}


def cmd_status(as_json: bool) -> int:
    resp = rpc({"cmd": "status"})
    if not resp.get("ok"):
        print(f"ошибка: {resp.get('error')}", file=sys.stderr)
        return 1
    state = resp["state"]
    if as_json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    mutable = [kb for kb in state["keyboards"] if kb["mutable"]]
    overall = "ВЫКЛЮЧЕНА" if state["muted"] else "включена"
    print(f"Состояние:    {overall}")
    print(f"Сочетание:    {state['gesture']}")
    print(f"Защита:       {'да (не отключать последнюю)' if state['protect_last_keyboard'] else 'нет'}")
    print(f"Клавиатур:    {len(state['keyboards'])}, из них управляемых {len(mutable)}, "
          f"включённых всего {state['unmuted_total']}")
    print(f"Конфиг:       {state['config_path']}")
    print()
    for kb in state["keyboards"]:
        tags = []
        tags.append("внутренняя" if kb["internal"] else "внешняя")
        if kb["mutable"]:
            tags.append("управляемая")
        state_txt = "ВЫКЛ" if kb["muted"] else "вкл"
        print(f"  [{state_txt:4s}] {kb['name']}  ({', '.join(tags)})")
        print(f"          {kb['path']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kbdguard", description="Переключатель встроенной клавиатуры")
    sub = parser.add_subparsers(dest="cmd")

    p_daemon = sub.add_parser("daemon", help="запустить демон (root)")
    p_daemon.add_argument("--config", default=CONFIG_PATH)

    sub.add_parser("on", help="включить управляемые клавиатуры")
    sub.add_parser("off", help="выключить управляемые клавиатуры")
    sub.add_parser("toggle", help="переключить состояние")
    sub.add_parser("reload", help="перечитать конфиг")
    sub.add_parser("shutdown", help="остановить демон (снять захват)")

    p_dev = sub.add_parser("device", help="включить/выключить конкретное устройство")
    p_dev.add_argument("path", help="путь /dev/input/eventN")
    p_dev.add_argument("state", choices=["on", "off"])

    p_protect = sub.add_parser("protect", help="защита: не отключать последнюю клавиатуру")
    p_protect.add_argument("state", choices=["on", "off"])

    p_status = sub.add_parser("status", help="показать состояние")
    p_status.add_argument("--json", action="store_true")

    sub.add_parser("devices", help="список клавиатур")
    sub.add_parser("tray", help="иконка в трее (сессия пользователя)")

    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 2

    if args.cmd == "daemon":
        Daemon(args.config).run()
        return 0
    if args.cmd == "tray":
        return run_tray()
    if args.cmd in ("on", "off", "toggle", "reload", "shutdown"):
        resp = rpc({"cmd": args.cmd})
        if not resp.get("ok"):
            print(f"ошибка: {resp.get('error')}", file=sys.stderr)
            return 1
        if args.cmd == "shutdown":
            return 0
        time.sleep(0.4)
        return cmd_status(False)
    if args.cmd == "device":
        resp = rpc({"cmd": "device", "path": args.path, "muted": args.state == "off"})
        if not resp.get("ok"):
            print(f"ошибка: {resp.get('error')}", file=sys.stderr)
            return 1
        time.sleep(0.4)
        return cmd_status(False)
    if args.cmd == "protect":
        resp = rpc({"cmd": "protect", "value": args.state == "on"})
        if not resp.get("ok"):
            print(f"ошибка: {resp.get('error')}", file=sys.stderr)
            return 1
        time.sleep(0.2)
        return cmd_status(False)
    if args.cmd == "status":
        return cmd_status(args.json)
    if args.cmd == "devices":
        return cmd_status(True)
    return 2


# --------------------------------------------------------------------------
# трей (SNI через Ayatana AppIndicator)
# --------------------------------------------------------------------------
def run_tray() -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
    except (ValueError, ImportError):
        from gi.repository import AppIndicator3 as AppIndicator  # type: ignore
    from gi.repository import GLib, Gtk

    state: dict = {"data": None, "error": None}

    def fetch() -> dict | None:
        resp = rpc({"cmd": "status"}, timeout=1.5)
        if resp.get("ok"):
            state["data"] = resp["state"]
            state["error"] = None
            return resp["state"]
        state["error"] = resp.get("error")
        return None

    indicator = AppIndicator.Indicator.new(
        "kbdguard", "kbdguard-on", AppIndicator.IndicatorCategory.HARDWARE
    )
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    menu = Gtk.Menu()
    item_head = Gtk.MenuItem(label="kbdguard")
    item_head.set_sensitive(False)
    menu.append(item_head)

    item_toggle = Gtk.MenuItem(label="Отключить")
    menu.append(item_toggle)

    sep1 = Gtk.SeparatorMenuItem()
    menu.append(sep1)

    sub_devices = Gtk.MenuItem(label="Устройства")
    menu_devices = Gtk.Menu()
    sub_devices.set_submenu(menu_devices)
    menu.append(sub_devices)

    sep2 = Gtk.SeparatorMenuItem()
    menu.append(sep2)

    item_gesture = Gtk.MenuItem(label="Сочетание: Ctrl + Alt")
    item_gesture.set_sensitive(False)
    menu.append(item_gesture)

    item_protect = Gtk.CheckMenuItem(label="Защита: не отключать последнюю клавиатуру")
    menu.append(item_protect)

    item_config = Gtk.MenuItem(label="Конфиг: /etc/kbdguard/config.toml")
    item_config.set_sensitive(False)
    menu.append(item_config)

    sep3 = Gtk.SeparatorMenuItem()
    menu.append(sep3)

    item_quit = Gtk.MenuItem(label="Выход")
    menu.append(item_quit)

    menu.show_all()
    indicator.set_menu(menu)

    def notify(text: str) -> None:
        try:
            Gtk.init([])
        except Exception:  # noqa: BLE001
            pass
        subprocess.Popen(["notify-send", "-a", "kbdguard", "Клавиатура", text])

    def rebuild_devices(data: dict) -> None:
        for child in list(menu_devices.get_children()):
            menu_devices.remove(child)
        mutable = [kb for kb in data["keyboards"] if kb["mutable"]]
        if not mutable:
            empty = Gtk.MenuItem(label="нет управляемых клавиатур")
            empty.set_sensitive(False)
            menu_devices.append(empty)
        for kb in mutable:
            label = kb["name"] + (" (внутренняя)" if kb["internal"] else " (внешняя)")
            item = Gtk.CheckMenuItem(label=label)
            item.set_active(not kb["muted"])

            def on_toggle(widget, path=kb["path"]):
                resp = rpc({"cmd": "device", "path": path, "muted": not widget.get_active()})
                if not resp.get("ok"):
                    notify(resp.get("error", "ошибка"))
                GLib.timeout_add(150, refresh)
                return False

            item.connect("toggled", on_toggle)
            menu_devices.append(item)
        menu_devices.show_all()

    def on_toggle_all(_widget) -> None:
        resp = rpc({"cmd": "toggle"})
        if not resp.get("ok"):
            notify(resp.get("error", "ошибка"))
        GLib.timeout_add(150, refresh)

    def on_protect(widget) -> None:
        resp = rpc({"cmd": "reload"})
        if not resp.get("ok"):
            notify("защита меняется в /etc/kbdguard/config.toml")
        notify("защита последней клавиатуры: настраивается в конфиге")

    def on_quit(_widget) -> None:
        Gtk.main_quit()

    item_toggle.connect("activate", on_toggle_all)
    item_protect.connect("toggled", on_protect)
    item_quit.connect("activate", on_quit)

    def refresh() -> bool:
        data = fetch()
        if data is None:
            indicator.set_icon_full("kbdguard-off", "нет связи с демоном")
            item_head.set_label("kbdguard: демон не запущен")
            item_toggle.set_sensitive(False)
            return True

        item_toggle.set_sensitive(True)
        item_head.set_label("Встроенная клавиатура: ВЫКЛЮЧЕНА" if data["muted"]
                            else "Встроенная клавиатура: включена")
        item_toggle.set_label("Включить" if data["muted"] else "Отключить")
        item_gesture.set_label(f"Сочетание: {data['gesture']}")
        item_config.set_label(f"Конфиг: {data['config_path']}")
        indicator.set_icon_full("kbdguard-off" if data["muted"] else "kbdguard-on",
                                "клавиатура выключена" if data["muted"] else "клавиатура включена")
        rebuild_devices(data)
        return True

    refresh()
    GLib.timeout_add_seconds(2, refresh)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
