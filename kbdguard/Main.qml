import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Services.UI

Item {
  id: root

  property var pluginApi: null

  readonly property var cfg: pluginApi?.pluginSettings || ({})
  readonly property var defaults: pluginApi?.manifest?.metadata?.defaultSettings || ({})

  readonly property string cliPath: cfg.cliPath ?? defaults.cliPath ?? "kbdguard"
  readonly property int pollIntervalMs: cfg.pollIntervalMs ?? defaults.pollIntervalMs ?? 2000
  readonly property bool hideWhenUnavailable: cfg.hideWhenUnavailable ?? defaults.hideWhenUnavailable ?? false

  property bool available: false
  property bool muted: false
  property int unmutedTotal: 0
  property var keyboards: []
  property string gesture: "Ctrl + Alt"
  property bool protect: true
  property string lastError: ""
  property bool busy: false

  readonly property var mutableKeyboards: root.keyboards.filter(k => k.mutable === true)

  signal updated()

  // ===== API для BarWidget / Panel =====

  function refresh() {
    if (!statusProc.running)
      statusProc.running = true
  }

  function setAllEnabled(enabled) {
    runCommand([enabled ? "on" : "off"])
  }

  function toggle() {
    runCommand(["toggle"])
  }

  function setDeviceEnabled(path, enabled) {
    runCommand(["device", path, enabled ? "on" : "off"])
  }

  function setProtectEnabled(enabled) {
    runCommand(["protect", enabled ? "on" : "off"])
  }

  function runCommand(args) {
    root.busy = true
    actionProc.command = [root.cliPath].concat(args)
    actionProc.running = true
  }

  function parseStatus(text) {
    try {
      const data = JSON.parse(text)
      root.available = true
      root.muted = data.muted === true
      root.unmutedTotal = data.unmuted_total ?? 0
      root.keyboards = data.keyboards ?? []
      root.gesture = data.gesture ?? "Ctrl + Alt"
      root.protect = data.protect_last_keyboard === true
      root.lastError = ""
      root.updated()
    } catch (e) {
      root.available = false
      root.lastError = String(e)
      Logger.w("KbdGuard", "Не удалось разобрать status --json: " + e)
    }
  }

  function tooltip() {
    if (!root.available)
      return pluginApi?.tr("widget.tooltip.unavailable")
    return root.muted ? pluginApi?.tr("widget.tooltip.off") : pluginApi?.tr("widget.tooltip.on")
  }

  // ===== IPC: qs ipc call plugin:kbdguard <cmd> =====

  IpcHandler {
    target: "plugin:kbdguard"

    function toggle() {
      root.toggle()
    }

    function off() {
      root.setAllEnabled(false)
    }

    function on() {
      root.setAllEnabled(true)
    }

    function refreshStatus() {
      root.refresh()
    }
  }

  Process {
    id: statusProc
    command: [root.cliPath, "status", "--json"]
    running: false

    stdout: StdioCollector {
      onStreamFinished: root.parseStatus(String(this.text))
    }

    stderr: StdioCollector {
      onStreamFinished: {
        const msg = String(this.text).trim()
        if (msg.length > 0) {
          root.lastError = msg
          Logger.w("KbdGuard", msg)
        }
      }
    }

    onExited: exitCode => {
      if (exitCode !== 0)
        root.available = false
    }
  }

  Process {
    id: actionProc
    running: false

    stdout: StdioCollector {}

    stderr: StdioCollector {
      onStreamFinished: {
        const msg = String(this.text).trim()
        if (msg.length > 0) {
          ToastService.showError(pluginApi?.tr("notifications.failed"), msg)
          Logger.w("KbdGuard", msg)
        }
      }
    }

    onExited: exitCode => {
      root.busy = false
      if (exitCode === 0)
        ToastService.showNotice(pluginApi?.tr("notifications.title"), root.tooltip())
      refreshDelay.restart()
    }
  }

  Timer {
    id: pollTimer
    interval: root.pollIntervalMs
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  Timer {
    id: refreshDelay
    interval: 150
    repeat: false
    onTriggered: root.refresh()
  }

  Component.onCompleted: {
    root.refresh()
    Logger.i("KbdGuard", "Плагин загружен, CLI: " + root.cliPath)
  }
}
