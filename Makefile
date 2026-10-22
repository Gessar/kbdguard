PLUGIN_DIR ?= $(HOME)/.config/noctalia/plugins
REPO       := $(shell pwd)

.PHONY: help install-backend install-plugin uninstall check preview

help:
	@echo "make install-backend  — демон + CLI (нужен sudo)"
	@echo "make install-plugin   — плагин в $(PLUGIN_DIR)/kbdguard"
	@echo "make uninstall        — удалить демон (конфиг остаётся)"
	@echo "make check            — проверка синтаксиса и JSON"
	@echo "make preview          — пересобрать kbdguard/preview.png"

install-backend:
	sudo bash backend/install.sh

install-plugin:
	mkdir -p "$(PLUGIN_DIR)"
	rm -rf "$(PLUGIN_DIR)/kbdguard"
	cp -r "$(REPO)/kbdguard" "$(PLUGIN_DIR)/kbdguard"
	@echo "плагин установлен: $(PLUGIN_DIR)/kbdguard"
	@echo "включите виджет в баре: Настройки → Bar → Widgets → Keyboard Guard"

uninstall:
	sudo bash backend/install.sh --uninstall

check:
	python3 scripts/check.py

preview:
	python3 scripts/make_preview.py
