import QtQuick
import Quickshell
import qs.Commons
import qs.Services.UI
import qs.Widgets

NIconButton {
  id: root

  // ===== свойства, которые передаёт шелл =====
  property var pluginApi: null
  property ShellScreen screen
  property string widgetId: ""
  property string section: ""
  property int sectionWidgetIndex: -1
  property int sectionWidgetsCount: 0

  readonly property var mainInstance: pluginApi?.mainInstance
  readonly property bool muted: mainInstance?.muted ?? false
  readonly property bool available: mainInstance?.available ?? false
  readonly property string gesture: mainInstance?.gesture ?? "Ctrl + Alt"

  property var cfg: pluginApi?.pluginSettings || ({})
  property var defaults: pluginApi?.manifest?.metadata?.defaultSettings || ({})
  readonly property string iconColorKey: cfg.iconColor ?? defaults.iconColor ?? "none"
  readonly property color customIconColor: Color.resolveColorKey(iconColorKey)

  visible: root.available || !(mainInstance?.hideWhenUnavailable ?? false)

  // ===== вид =====
  icon: root.muted ? "keyboard-off" : "keyboard"
  tooltipText: mainInstance?.tooltip() ?? pluginApi?.tr("widget.tooltip.unavailable")
  tooltipDirection: BarService.getTooltipDirection(screen?.name)
  baseSize: Style.getCapsuleHeightForScreen(screen?.name)
  applyUiScale: false
  customRadius: Style.radiusL

  colorBg: root.muted ? Color.mError : Style.capsuleColor
  colorFg: root.muted ? Color.mOnSurface : (root.customIconColor !== "transparent" ? root.customIconColor : Color.mOnSurface)
  colorBgHover: Color.mHover
  colorFgHover: Color.mOnHover
  colorBorder: "transparent"
  colorBorderHover: "transparent"

  border.color: Style.capsuleBorderColor
  border.width: Style.capsuleBorderWidth

  // ===== действия =====
  onClicked: {
    if (!root.available)
      mainInstance?.refresh()
    else
      mainInstance?.toggle()
  }

  onRightClicked: {
    mainInstance?.refresh()
    PanelService.showContextMenu(contextMenu, root, screen)
  }

  NPopupContextMenu {
    id: contextMenu

    model: [
      {
        "label": root.muted ? pluginApi?.tr("menu.enable") : pluginApi?.tr("menu.disable"),
        "action": "toggle",
        "icon": root.muted ? "keyboard" : "keyboard-off"
      },
      {
        "label": pluginApi?.tr("menu.panel"),
        "action": "panel",
        "icon": "devices"
      },
      {
        "label": pluginApi?.tr("menu.refresh"),
        "action": "refresh",
        "icon": "refresh"
      },
      {
        "label": pluginApi?.tr("menu.settings"),
        "action": "settings",
        "icon": "settings"
      }
    ]

    onTriggered: action => {
      contextMenu.close()
      PanelService.closeContextMenu(screen)

      if (action === "toggle") {
        mainInstance?.toggle()
      } else if (action === "panel") {
        if (pluginApi)
          pluginApi.togglePanel(root.screen, root)
      } else if (action === "refresh") {
        mainInstance?.refresh()
      } else if (action === "settings") {
        if (pluginApi)
          BarService.openPluginSettings(screen, pluginApi.manifest)
      }
    }
  }
}
