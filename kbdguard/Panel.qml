import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Services.UI
import qs.Widgets

Item {
  id: root

  property var pluginApi: null

  readonly property var geometryPlaceholder: panelContainer
  property real contentPreferredWidth: 380 * Style.uiScaleRatio
  property real contentPreferredHeight: (root.available ? 470 : 220) * Style.uiScaleRatio
  readonly property bool allowAttach: true
  anchors.fill: parent

  readonly property var mainInstance: pluginApi?.mainInstance
  readonly property bool available: mainInstance?.available ?? false
  readonly property bool muted: mainInstance?.muted ?? false
  readonly property bool protect: mainInstance?.protect ?? true
  readonly property var mutableKeyboards: mainInstance?.mutableKeyboards ?? []
  readonly property string gesture: mainInstance?.gesture ?? "Ctrl + Alt"

  Component.onCompleted: mainInstance?.refresh()

  Rectangle {
    id: panelContainer
    anchors.fill: parent
    color: "transparent"

    ColumnLayout {
      anchors.fill: parent
      anchors.margins: Style.marginL
      spacing: Style.marginM

      // ===== заголовок =====
      RowLayout {
        spacing: Style.marginM

        NIcon {
          icon: root.muted ? "keyboard-off" : "keyboard"
          pointSize: Style.fontSizeXL
          color: root.muted ? Color.mError : Color.mPrimary
        }

        NText {
          text: pluginApi?.tr("panel.title")
          font.pointSize: Style.fontSizeL
          font.weight: Font.Medium
          color: Color.mOnSurface
          Layout.fillWidth: true
        }

        NIconButton {
          icon: "refresh"
          baseSize: Style.baseWidgetSize * 0.8
          tooltipText: pluginApi?.tr("panel.refresh")
          onClicked: mainInstance?.refresh()
        }
      }

      // ===== нет связи с демоном =====
      NBox {
        visible: !root.available
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.marginM
          spacing: Style.marginM

          NText {
            Layout.fillWidth: true
            text: pluginApi?.tr("panel.daemon.missing")
            wrapMode: Text.WordWrap
            color: Color.mError
          }

          NLabel {
            Layout.fillWidth: true
            label: pluginApi?.tr("panel.daemon.hint")
          }

          Item { Layout.fillHeight: true }

          NButton {
            text: pluginApi?.tr("panel.daemon.retry")
            onClicked: mainInstance?.refresh()
          }
        }
      }

      // ===== основное =====
      NBox {
        visible: root.available
        Layout.fillWidth: true

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.marginM
          spacing: Style.marginS

          NToggle {
            Layout.fillWidth: true
            label: root.muted
              ? pluginApi?.tr("panel.state.off")
              : pluginApi?.tr("panel.state.on")
            description: pluginApi?.tr("panel.state.description")
            checked: !root.muted
            onToggled: checked => {
              if (mainInstance)
                mainInstance.setAllEnabled(checked)
            }
          }
        }
      }

      // ===== устройства =====
      NBox {
        visible: root.available
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.marginM
          spacing: Style.marginS

          RowLayout {
            spacing: Style.marginS

            NText {
              text: pluginApi?.tr("panel.devices.title")
              font.pointSize: Style.fontSizeM
              font.weight: Font.Medium
              color: Color.mOnSurface
              Layout.fillWidth: true
            }

            NText {
              text: root.mutableKeyboards.length
              font.pointSize: Style.fontSizeS
              color: Color.mOnSurfaceVariant
            }
          }

          NText {
            visible: root.mutableKeyboards.length === 0
            Layout.fillWidth: true
            text: pluginApi?.tr("panel.devices.empty")
            wrapMode: Text.WordWrap
            color: Color.mOnSurfaceVariant
          }

          Flickable {
            visible: root.mutableKeyboards.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: deviceColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
              id: deviceColumn
              width: parent.width
              spacing: Style.marginS

              Repeater {
                model: root.mutableKeyboards

                delegate: RowLayout {
                  required property var modelData

                  Layout.fillWidth: true
                  spacing: Style.marginS

                  ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    NText {
                      Layout.fillWidth: true
                      text: modelData.name
                      elide: Text.ElideRight
                      color: Color.mOnSurface
                    }

                    NText {
                      Layout.fillWidth: true
                      text: modelData.internal
                        ? pluginApi?.tr("panel.devices.internal")
                        : pluginApi?.tr("panel.devices.external")
                      font.pointSize: Style.fontSizeXS
                      color: Color.mOnSurfaceVariant
                      elide: Text.ElideRight
                    }
                  }

                  NToggle {
                    checked: !modelData.muted
                    onToggled: checked => {
                      if (mainInstance)
                        mainInstance.setDeviceEnabled(modelData.path, checked)
                    }
                  }
                }
              }
            }
          }
        }
      }

      // ===== защита =====
      NBox {
        visible: root.available
        Layout.fillWidth: true

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.marginM
          spacing: Style.marginS

          NToggle {
            Layout.fillWidth: true
            icon: "shield-check"
            label: pluginApi?.tr("panel.protect.label")
            description: pluginApi?.tr("panel.protect.description")
            checked: root.protect
            onToggled: checked => {
              if (mainInstance)
                mainInstance.setProtectEnabled(checked)
            }
          }
        }
      }

      // ===== сочетание / подсказка =====
      NBox {
        visible: root.available
        Layout.fillWidth: true

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.marginM
          spacing: Style.marginXS

          RowLayout {
            spacing: Style.marginS

            NIcon {
              icon: "keyboard"
              pointSize: Style.fontSizeM
              color: Color.mOnSurfaceVariant
            }

            NText {
              Layout.fillWidth: true
              text: pluginApi?.tr("panel.gesture.label", { "gesture": root.gesture })
              font.pointSize: Style.fontSizeS
              color: Color.mOnSurfaceVariant
              elide: Text.ElideRight
            }
          }

          NText {
            Layout.fillWidth: true
            text: pluginApi?.tr("panel.gesture.hint")
            font.pointSize: Style.fontSizeXXS
            color: Color.mOnSurfaceVariant
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }
}
