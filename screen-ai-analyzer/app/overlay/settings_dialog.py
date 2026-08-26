"""Settings dialog.

API keys are read from ``.env`` first; a key that comes from the environment is
shown as read-only here, because editing it would have no effect.  Keys typed
here are stored in ``~/.config/screen-ai-analyzer/config.json`` (mode 0600).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    KEY_ENV_VARS,
    OUTPUT_MODES,
    POSITION_BOTTOM,
    POSITION_TOP,
    PROVIDERS,
    AppConfig,
)

log = logging.getLogger(__name__)

LANGUAGES = ["auto", "English", "Russian", "Turkmen", "German", "French", "Spanish", "Turkish"]


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, hotkey_manager=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self.hotkey_manager = hotkey_manager
        self.setWindowTitle("Screen AI Analyzer — Settings")
        self.setMinimumWidth(520)
        self._key_edits: Dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._providers_tab(), "Providers")
        tabs.addTab(self._overlay_tab(), "Output")
        tabs.addTab(self._hotkey_tab(), "Hotkey")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- tabs -------------------------------------------------------------
    def _providers_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)

        keys_box = QGroupBox("API keys", page)
        keys_form = QFormLayout(keys_box)
        for provider, env_var in KEY_ENV_VARS.items():
            edit = QLineEdit(keys_box)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            if os.environ.get(env_var, "").strip():
                edit.setText("")
                edit.setPlaceholderText(f"provided by {env_var} (.env)")
                edit.setReadOnly(True)
            else:
                edit.setText(str(getattr(self.config, f"{provider}_api_key", "")))
                edit.setPlaceholderText(f"unset — preferred: {env_var} in .env")
            self._key_edits[provider] = edit
            keys_form.addRow(f"{provider.capitalize()}:", edit)
        outer.addWidget(keys_box)

        models_box = QGroupBox("Models", page)
        form = QFormLayout(models_box)
        self.provider_combo = QComboBox(models_box)
        self.provider_combo.addItems(list(PROVIDERS))
        self.provider_combo.setCurrentText(self.config.preferred_provider)
        form.addRow("Preferred provider:", self.provider_combo)

        self.gemini_model_edit = QLineEdit(self.config.gemini_model, models_box)
        form.addRow("Gemini model:", self.gemini_model_edit)

        self.openrouter_models_edit = QLineEdit(self.config.openrouter_models, models_box)
        self.openrouter_models_edit.setToolTip(
            "Comma separated, tried in order. A vision model first "
            "(e.g. google/gemini-2.5-flash), then a text model for the OCR fallback."
        )
        form.addRow("OpenRouter models:", self.openrouter_models_edit)

        self.openai_model_edit = QLineEdit(self.config.openai_model, models_box)
        form.addRow("OpenAI model:", self.openai_model_edit)

        self.deepseek_model_edit = QLineEdit(self.config.deepseek_model, models_box)
        form.addRow("DeepSeek model:", self.deepseek_model_edit)

        self.custom_model_edit = QLineEdit(self.config.custom_model, models_box)
        form.addRow("Custom model:", self.custom_model_edit)
        self.custom_base_edit = QLineEdit(self.config.custom_base_url, models_box)
        self.custom_base_edit.setPlaceholderText("https://host:port/v1 (OpenAI-compatible)")
        form.addRow("Custom base URL:", self.custom_base_edit)

        self.language_combo = QComboBox(models_box)
        self.language_combo.setEditable(True)
        self.language_combo.addItems(LANGUAGES)
        self.language_combo.setCurrentText(self.config.language)
        form.addRow("Answer language:", self.language_combo)
        outer.addWidget(models_box)

        note = QLabel(
            "Text-only models (deepseek-chat) never receive the screenshot: the "
            "image is OCR'd locally first.",
            page,
        )
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addStretch(1)
        return page

    def _overlay_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self.output_combo = QComboBox(page)
        self.output_combo.addItems(list(OUTPUT_MODES))
        self.output_combo.setCurrentText(self.config.output_mode)
        self.output_combo.setToolTip(
            "notification: nothing is drawn on screen — the answer is copied to "
            "the clipboard and a desktop notification says it is ready.\n"
            "overlay: the small always-on-top answer window."
        )
        form.addRow("Output:", self.output_combo)

        self.position_combo = QComboBox(page)
        self.position_combo.addItems([POSITION_TOP, POSITION_BOTTOM])
        self.position_combo.setCurrentText(self.config.overlay_position)
        form.addRow("Position:", self.position_combo)

        self.font_spin = QSpinBox(page)
        self.font_spin.setRange(7, 32)
        self.font_spin.setValue(self.config.font_size)
        form.addRow("Font size (pt):", self.font_spin)

        self.opacity_spin = QDoubleSpinBox(page)
        self.opacity_spin.setRange(0.30, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(self.config.opacity)
        form.addRow("Opacity:", self.opacity_spin)

        self.width_spin = QDoubleSpinBox(page)
        self.width_spin.setRange(0.20, 0.60)
        self.width_spin.setSingleStep(0.01)
        self.width_spin.setValue(self.config.overlay_width_ratio)
        form.addRow("Width (screen fraction):", self.width_spin)

        self.timeout_spin = QSpinBox(page)
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(self.config.request_timeout)
        form.addRow("Request timeout (s):", self.timeout_spin)
        return page

    def _hotkey_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        form = QFormLayout()
        self.hotkey_edit = QLineEdit(self.config.hotkey, page)
        self.hotkey_edit.setPlaceholderText("F8")
        form.addRow("Hotkey:", self.hotkey_edit)
        outer.addLayout(form)

        self.hotkey_status = QLabel("", page)
        self.hotkey_status.setWordWrap(True)
        if self.hotkey_manager is not None:
            self.hotkey_status.setText(self.hotkey_manager.status.message)
        outer.addWidget(self.hotkey_status)

        row = QHBoxLayout()
        register = QPushButton("Register desktop shortcut", page)
        register.clicked.connect(self._register_shortcut)
        remove = QPushButton("Remove shortcut", page)
        remove.clicked.connect(self._remove_shortcut)
        row.addWidget(register)
        row.addWidget(remove)
        row.addStretch(1)
        outer.addLayout(row)

        hint = QLabel(
            "On GNOME (Wayland or X11) the hotkey is a GNOME custom shortcut — "
            "registering it writes a normal entry in Settings ▸ Keyboard that you "
            "can inspect or delete at any time. On other desktops, bind this "
            "command yourself:",
            page,
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        from app.utils.hotkey import trigger_command

        command = QLineEdit(trigger_command(), page)
        command.setReadOnly(True)
        outer.addWidget(command)
        outer.addStretch(1)
        return page

    # -- actions ----------------------------------------------------------
    def _register_shortcut(self) -> None:
        if self.hotkey_manager is None:
            return
        self.hotkey_manager.hotkey = self.hotkey_edit.text().strip() or "F8"
        ok = self.hotkey_manager.install_desktop_shortcut()
        self.hotkey_status.setText(
            self.hotkey_manager.status.message
            if ok
            else "Could not register the shortcut (GNOME/gsettings not available)."
        )

    def _remove_shortcut(self) -> None:
        if self.hotkey_manager is None:
            return
        ok = self.hotkey_manager.remove_desktop_shortcut()
        self.hotkey_status.setText(
            "Shortcut removed." if ok else "No shortcut to remove."
        )

    # -- result -----------------------------------------------------------
    def apply_to_config(self) -> AppConfig:
        cfg = self.config
        cfg.preferred_provider = self.provider_combo.currentText()
        cfg.gemini_model = self.gemini_model_edit.text().strip() or cfg.gemini_model
        cfg.openrouter_models = self.openrouter_models_edit.text().strip()
        cfg.openai_model = self.openai_model_edit.text().strip() or cfg.openai_model
        cfg.deepseek_model = self.deepseek_model_edit.text().strip() or cfg.deepseek_model
        cfg.custom_model = self.custom_model_edit.text().strip()
        cfg.custom_base_url = self.custom_base_edit.text().strip()
        cfg.language = self.language_combo.currentText().strip() or "auto"

        cfg.output_mode = self.output_combo.currentText()
        cfg.overlay_position = self.position_combo.currentText()
        cfg.font_size = self.font_spin.value()
        cfg.opacity = self.opacity_spin.value()
        cfg.overlay_width_ratio = self.width_spin.value()
        cfg.request_timeout = self.timeout_spin.value()
        cfg.hotkey = self.hotkey_edit.text().strip() or "F8"

        for provider, edit in self._key_edits.items():
            if edit.isReadOnly():  # value comes from the environment
                continue
            setattr(self.config, f"{provider}_api_key", edit.text().strip())

        cfg.normalise()
        return cfg
