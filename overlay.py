"""In-game overlay panel and settings window (PyQt5)."""
from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional

import config

try:
    from PyQt5 import QtCore, QtWidgets
    _QT = True
except ImportError:
    _QT = False


def load_settings() -> Dict:
    if os.path.exists(config.CONFIG_JSON):
        try:
            with open(config.CONFIG_JSON, encoding="utf-8") as f:
                d = json.load(f)
            merged = dict(config.DEFAULT_SETTINGS)
            merged.update(d)
            return merged
        except Exception:
            pass
    return dict(config.DEFAULT_SETTINGS)


def save_settings(settings: Dict) -> None:
    with open(config.CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


if _QT:
    class ComparisonPanel(QtWidgets.QWidget):
        """Frameless always-on-top panel shown over the game window."""

        def __init__(self, settings: Dict, parent=None):
            super().__init__(parent)
            self.settings = settings
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint
                | QtCore.Qt.WindowStaysOnTopHint
                | QtCore.Qt.Tool
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            self.setWindowOpacity(settings["overlay_opacity"] / 100.0)
            self.move(settings["panel_x"], settings["panel_y"])
            self._build()

        def _build(self):
            c = QtWidgets.QFrame()
            c.setStyleSheet(
                "QFrame{background:rgba(15,20,34,235);border-radius:8px;}"
                "QLabel{color:#E6E9F0;}"
            )
            outer = QtWidgets.QVBoxLayout(self)
            outer.addWidget(c)
            v = QtWidgets.QVBoxLayout(c)
            v.setContentsMargins(12, 12, 12, 12)
            v.setSpacing(4)

            t = QtWidgets.QLabel("HotS Draft Assistant")
            t.setStyleSheet("font-weight:bold;font-size:14px;")
            v.addWidget(t)

            self.mmr_lbl  = QtWidgets.QLabel("MMR: —")
            self.prob_bar = QtWidgets.QProgressBar()
            self.prob_bar.setRange(0, 100)
            self.prob_bar.setFormat("Победа: %p%")
            self.ban_box  = QtWidgets.QLabel("Баны: —")
            self.pick_box = QtWidgets.QLabel("Пики: —")
            self.ban_box.setWordWrap(True)
            self.pick_box.setWordWrap(True)
            for w in (self.mmr_lbl, self.prob_bar, self.ban_box, self.pick_box):
                v.addWidget(w)
            self.resize(320, 270)

        def update_prediction(self, ally_mmr, enemy_mmr, prob, partial):
            mark = " (частично)" if partial else ""
            self.mmr_lbl.setText(f"Своя: {ally_mmr}   Враг: {enemy_mmr}{mark}")
            self.prob_bar.setValue(int(prob * 100))

        def update_bans(self, bans: List):
            if self.settings.get("show_ban_recommendations") and bans:
                self.ban_box.setText("Баны:\n" + "\n".join(
                    f"{'★' if b.is_otp_ban else '⛔'} {b.hero}" for b in bans))
            else:
                self.ban_box.setText("Баны: —")

        def update_picks(self, picks: List):
            if self.settings.get("show_pick_recommendations") and picks:
                self.pick_box.setText("Пики:\n" + "\n".join(
                    f"✓ {p.hero} ({p.score:.2f})" for p in picks))
            else:
                self.pick_box.setText("Пики: —")

    class SettingsWindow(QtWidgets.QWidget):
        """Overlay appearance settings."""

        def __init__(self, settings: Dict,
                     on_save: Optional[Callable] = None, parent=None):
            super().__init__(parent)
            self.settings = settings
            self.on_save  = on_save
            self.setWindowTitle("Настройки — HotS Draft Assistant")
            self.setMinimumWidth(360)
            self._build()

        def _build(self):
            lay = QtWidgets.QFormLayout(self)
            lay.setSpacing(10)

            self.cb_enabled = QtWidgets.QCheckBox()
            self.cb_enabled.setChecked(self.settings["overlay_enabled"])
            lay.addRow("Включить оверлей:", self.cb_enabled)

            row = QtWidgets.QHBoxLayout()
            self.sl_opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.sl_opacity.setRange(0, 100)
            self.sl_opacity.setValue(self.settings["overlay_opacity"])
            self.lbl_op = QtWidgets.QLabel(f"{self.settings['overlay_opacity']}%")
            self.sl_opacity.valueChanged.connect(lambda v: self.lbl_op.setText(f"{v}%"))
            row.addWidget(self.sl_opacity); row.addWidget(self.lbl_op)
            lay.addRow("Прозрачность:", row)

            self.cb_bans = QtWidgets.QCheckBox()
            self.cb_bans.setChecked(self.settings["show_ban_recommendations"])
            lay.addRow("Показывать баны:", self.cb_bans)

            self.cb_picks = QtWidgets.QCheckBox()
            self.cb_picks.setChecked(self.settings["show_pick_recommendations"])
            lay.addRow("Показывать пики:", self.cb_picks)

            btn_row = QtWidgets.QHBoxLayout()
            ok  = QtWidgets.QPushButton("Сохранить")
            can = QtWidgets.QPushButton("Отмена")
            ok.clicked.connect(self._save); can.clicked.connect(self.close)
            btn_row.addStretch(); btn_row.addWidget(ok); btn_row.addWidget(can)
            lay.addRow(btn_row)

        def _save(self):
            self.settings["overlay_enabled"]          = self.cb_enabled.isChecked()
            self.settings["overlay_opacity"]           = self.sl_opacity.value()
            self.settings["show_ban_recommendations"]  = self.cb_bans.isChecked()
            self.settings["show_pick_recommendations"] = self.cb_picks.isChecked()
            save_settings(self.settings)
            if self.on_save:
                self.on_save(self.settings)
            self.close()


def gui_available() -> bool:
    return _QT
