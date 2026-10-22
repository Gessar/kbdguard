import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Services.UI
import qs.Widgets

ColumnLayout {
  id: root

  property var pluginApi: null

  property var cfg: pluginApi?.pluginSettings || ({})
  property var defaults: pluginApi?.manifest?.metadata?.defaultSettings || ({})

  property string editCliPath: cfg.cliPath ?? defaults.cliPath ?? "kbdguard"
  property int editPollInterval: cfg.pollIntervalMs ?? defaults.pollIntervalMs ?? 2000
  property bool editHideWhenUnavailable: cfg.hideWhenUnavailable ?? defaults.hideWhenUnavailable ?? false

  spacing: Style.marginL

  NTextInput {
    Layout.fillWidth: true
    label: pluginApi?.tr("settings.cli.label")
    description: pluginApi?.tr("settings.cli.description")
    text: root.editCliPath
    onTextChanged: root.editCliPath = text
  }

  NComboBox {
    Layout.fillWidth: true
    label: pluginApi?.tr("settings.poll.label")
    description: pluginApi?.tr("settings.poll.description")
    defaultValue: String(root.defaults.pollIntervalMs ?? 2000)
    model: [
      {
        "key": "1000",
        "name": pluginApi?.tr("settings.poll.1s")
      },
      {
        "key": "2000",
        "name": pluginApi?.tr("settings.poll.2s")
      },
      {
        "key": "5000",
        "name": pluginApi?.tr("settings.poll.5s")
      }
    ]
    currentKey: String(root.editPollInterval)
    onSelected: key => root.editPollInterval = parseInt(key)
  }

  NToggle {
    Layout.fillWidth: true
    label: pluginApi?.tr("settings.hide.label")
    description: pluginApi?.tr("settings.hide.description")
    checked: root.editHideWhenUnavailable
    onToggled: checked => root.editHideWhenUnavailable = checked
  }

  NDivider {
    Layout.fillWidth: true
  }

  NLabel {
    Layout.fillWidth: true
    label: pluginApi?.tr("settings.backend.hint")
  }

  function saveSettings() {
    if (!pluginApi)
      return

    pluginApi.pluginSettings.cliPath = root.editCliPath
    pluginApi.pluginSettings.pollIntervalMs = root.editPollInterval
    pluginApi.pluginSettings.hideWhenUnavailable = root.editHideWhenUnavailable
    pluginApi.saveSettings()

    if (pluginApi.mainInstance)
      pluginApi.mainInstance.refresh()

    ToastService.showNotice(pluginApi?.tr("settings.saved"))
  }
}
