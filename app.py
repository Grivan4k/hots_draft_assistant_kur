"""Main window — draft layout with manual data entry."""
from __future__ import annotations

import sys
from typing import List, Optional

import config
import overlay
from engine import DraftAssistant, scenario_1, scenario_2

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

# ── Palette ───────────────────────────────────────────────────────────────────
_DARK        = "#0D1117"
_PANEL       = "#161B22"
_ALLY_BG     = "#0A1F3A";  _ALLY_BORDER  = "#1A6DB5"
_ENEMY_BG    = "#2A0A12";  _ENEMY_BORDER = "#B51A2A"
_BAN_BG      = "#1A1A0A";  _BAN_BORDER   = "#886600"
_MAP_COLOR   = "#FFD700"
_OTP_COLOR   = "#FFD700"
_HERO_COLOR  = "#FFFFFF"
_TAG_COLOR   = "#8EA7CC"
_EMPTY_HERO  = "#3A4A5A"
_EMPTY_TAG   = "#1E2A38"
_ME_BORDER   = "#FFD700"
_REC_BAN_BG  = "#2A1010";  _REC_PICK_BG = "#0A1E32"


# ── Hero / player input dialog ────────────────────────────────────────────────
class SlotDialog(QDialog):
    """Enter player battletag and hero name for one draft slot."""

    def __init__(self, heroes: List[str], player: str = "", hero: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Игрок и герой")
        self.setMinimumWidth(340)

        layout = QtWidgets.QFormLayout(self)
        layout.setSpacing(10)

        self.player_edit = QLineEdit(player)
        self.player_edit.setPlaceholderText("battletag игрока")
        layout.addRow("Игрок:", self.player_edit)

        self.hero_combo = QComboBox()
        self.hero_combo.setEditable(True)
        self.hero_combo.addItem("")
        self.hero_combo.addItems(heroes)
        self.hero_combo.setCurrentText(hero)
        comp = QCompleter(heroes, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.hero_combo.setCompleter(comp)
        layout.addRow("Герой:", self.hero_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self._clear)
        btns.addButton(clear_btn, QDialogButtonBox.ResetRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        self.player_edit.returnPressed.connect(self.accept)

    def _clear(self):
        self.player_edit.clear()
        self.hero_combo.setCurrentText("")
        self.accept()

    def values(self):
        return self.player_edit.text().strip(), self.hero_combo.currentText().strip()


# ── Ban slot ──────────────────────────────────────────────────────────────────
class BanSlot(QFrame):
    """Clickable ban card — shows chosen hero or an empty placeholder."""
    changed = pyqtSignal()

    def __init__(self, heroes: List[str], parent=None):
        super().__init__(parent)
        self.heroes = heroes
        self.hero = ""
        self.setFixedSize(88, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Нажмите для выбора бана")
        self._refresh()

    def _refresh(self):
        if self.hero:
            self.setStyleSheet(
                f"QFrame {{ background:{_BAN_BG}; border:2px solid {_BAN_BORDER};"
                " border-radius:6px; }}"
            )
        else:
            self.setStyleSheet(
                "QFrame { background:#1A1A1A; border:2px dashed #333;"
                " border-radius:6px; }"
            )

        lay = self.layout()
        if lay:
            while lay.count():
                lay.takeAt(0).widget().deleteLater()
        else:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.setSpacing(1)

        icon = QLabel("⛔")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("color:#CC3300; font-size:14px; border:none;")

        name = QLabel(self.hero if self.hero else "—")
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color:{'#FFB347' if self.hero else '#444'}; "
            "font-size:9px; font-weight:bold; border:none;"
        )
        lay.addWidget(icon)
        lay.addWidget(name)

    def mousePressEvent(self, _event):
        dlg = SlotDialog(self.heroes, hero=self.hero, parent=self)
        # Hide the player row — bans only need a hero
        dlg.player_edit.hide()
        lbl = dlg.layout().labelForField(dlg.player_edit)
        if lbl:
            lbl.hide()
        if dlg.exec_() == QDialog.Accepted:
            _, hero = dlg.values()
            self.hero = hero
            self._refresh()
            self.changed.emit()

    def clear(self):
        self.hero = ""
        self._refresh()


# ── Player slot ───────────────────────────────────────────────────────────────
class PlayerSlot(QFrame):
    """One player's draft card — click to edit hero and battletag."""
    changed   = pyqtSignal()
    me_clicked = pyqtSignal(int)

    _GRADE_COLORS = {
        "S": "#FFD700", "A": "#A335EE", "B": "#0070DD",
        "C": "#1EFF00", "D": "#9D9D9D", "": "#555",
    }

    def __init__(self, slot_idx: int, team: str, heroes: List[str], parent=None):
        super().__init__(parent)
        self.slot_idx = slot_idx
        self.team     = team
        self.heroes   = heroes
        self.player   = ""
        self.hero     = ""
        self.grade    = ""
        self.is_otp   = False
        self.is_me    = False

        self._bg     = _ALLY_BG    if team == "ally" else _ENEMY_BG
        self._border = _ALLY_BORDER if team == "ally" else _ENEMY_BORDER

        self.setMinimumHeight(76)
        self.setMaximumHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._build()
        self._refresh()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 6)
        v.setSpacing(2)

        hero_row = QHBoxLayout()
        self.hero_lbl = QLabel("—")
        self.hero_lbl.setStyleSheet(
            f"color:{_EMPTY_HERO}; font-size:15px; font-weight:bold; border:none;"
        )
        self.otp_lbl = QLabel("★")
        self.otp_lbl.setStyleSheet(f"color:{_OTP_COLOR}; font-size:12px; border:none;")
        self.otp_lbl.setVisible(False)
        hero_row.addWidget(self.hero_lbl)
        hero_row.addStretch()
        hero_row.addWidget(self.otp_lbl)
        v.addLayout(hero_row)

        tag_row = QHBoxLayout()
        self.tag_lbl = QLabel("нажмите для ввода")
        self.tag_lbl.setStyleSheet(
            f"color:{_EMPTY_TAG}; font-size:10px; border:none;"
        )
        self.grade_lbl = QLabel()
        self.grade_lbl.setFixedSize(22, 22)
        self.grade_lbl.setAlignment(Qt.AlignCenter)
        tag_row.addWidget(self.tag_lbl)
        tag_row.addStretch()
        tag_row.addWidget(self.grade_lbl)
        v.addLayout(tag_row)

        if self.team == "ally":
            self.me_btn = QPushButton("Это я")
            self.me_btn.setFixedHeight(18)
            self.me_btn.setStyleSheet(
                "QPushButton{font-size:9px;border:1px solid #333;"
                "background:#1A2A3A;color:#6A8AAA;border-radius:3px;padding:0 4px;}"
                "QPushButton:hover{background:#223344;}"
            )
            self.me_btn.clicked.connect(lambda: self.me_clicked.emit(self.slot_idx))
            v.addWidget(self.me_btn, alignment=Qt.AlignRight)

    def _refresh(self):
        border = _ME_BORDER if self.is_me else self._border
        bw = "3px" if self.is_me else "2px"
        self.setStyleSheet(
            f"QFrame{{background:{self._bg};border:{bw} solid {border};"
            f"border-radius:8px;}}"
        )
        if self.hero:
            self.hero_lbl.setText(self.hero.upper())
            self.hero_lbl.setStyleSheet(
                f"color:{_HERO_COLOR};font-size:15px;font-weight:bold;border:none;"
            )
        else:
            self.hero_lbl.setText("—")
            self.hero_lbl.setStyleSheet(
                f"color:{_EMPTY_HERO};font-size:15px;font-weight:bold;border:none;"
            )

        if self.player:
            self.tag_lbl.setText(self.player)
            self.tag_lbl.setStyleSheet(f"color:{_TAG_COLOR};font-size:10px;border:none;")
        else:
            self.tag_lbl.setText("нажмите для ввода")
            self.tag_lbl.setStyleSheet(f"color:{_EMPTY_TAG};font-size:10px;border:none;")

        self.otp_lbl.setVisible(self.is_otp)

        gc = self._GRADE_COLORS.get(self.grade, "#555")
        if self.grade:
            self.grade_lbl.setText(self.grade)
            self.grade_lbl.setStyleSheet(
                f"background:{gc};color:#000;border-radius:11px;"
                "font-size:11px;font-weight:bold;border:none;"
            )
        else:
            self.grade_lbl.setText("")
            self.grade_lbl.setStyleSheet("border:none;background:transparent;")

        if self.team == "ally" and hasattr(self, "me_btn"):
            if self.is_me:
                self.me_btn.setStyleSheet(
                    "QPushButton{font-size:9px;border:1px solid #FFD700;"
                    "background:#2A3000;color:#FFD700;border-radius:3px;padding:0 4px;}"
                )
            else:
                self.me_btn.setStyleSheet(
                    "QPushButton{font-size:9px;border:1px solid #333;"
                    "background:#1A2A3A;color:#6A8AAA;border-radius:3px;padding:0 4px;}"
                    "QPushButton:hover{background:#223344;}"
                )

    def update_profile(self, grade: str, is_otp: bool):
        self.grade  = grade
        self.is_otp = is_otp
        self._refresh()

    def set_me(self, is_me: bool):
        self.is_me = is_me
        self._refresh()

    def mousePressEvent(self, _event):
        dlg = SlotDialog(self.heroes, self.player, self.hero, self)
        if dlg.exec_() == QDialog.Accepted:
            self.player, self.hero = dlg.values()
            self._refresh()
            self.changed.emit()


# ── Recommendation chip ───────────────────────────────────────────────────────
class RecoChip(QFrame):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        bg = _REC_BAN_BG if kind == "ban" else _REC_PICK_BG
        self.setStyleSheet(
            f"QFrame{{background:{bg};border:1px solid #333;border-radius:6px;}}"
            "QLabel{border:none;}"
        )
        self.setFixedWidth(148)
        self.setMinimumHeight(54)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 5, 8, 5)
        v.setSpacing(2)

        self.name_lbl   = QLabel("—")
        self.detail_lbl = QLabel()
        self.name_lbl.setStyleSheet("color:#DDD;font-size:12px;font-weight:bold;")
        self.detail_lbl.setStyleSheet("color:#888;font-size:9px;")
        self.name_lbl.setWordWrap(True)
        self.detail_lbl.setWordWrap(True)
        v.addWidget(self.name_lbl)
        v.addWidget(self.detail_lbl)

    def set_ban(self, hero: str, reason: str, is_otp: bool):
        prefix = "★ " if is_otp else "⛔ "
        self.name_lbl.setText(prefix + hero)
        self.name_lbl.setStyleSheet(
            f"color:{'#FFB347' if is_otp else '#FF7070'};"
            "font-size:12px;font-weight:bold;"
        )
        self.detail_lbl.setText(reason)

    def set_pick(self, hero: str, score: float, reason: str):
        self.name_lbl.setText("✓ " + hero)
        self.name_lbl.setStyleSheet("color:#7EC8E3;font-size:12px;font-weight:bold;")
        _MAP = {
            "OTP": "OTP-герой", "pool_main": "Основной пул",
            "pool_regular": "Регулярный", "counter": "Контрпик",
            "synergy": "Синергия", "meta": "Мета",
        }
        self.detail_lbl.setText(f"{score:.2f}  {_MAP.get(reason, reason)}")

    def clear(self):
        self.name_lbl.setText("—")
        self.name_lbl.setStyleSheet("color:#555;font-size:12px;font-weight:bold;")
        self.detail_lbl.setText("")


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    MAPS = [
        "", "Alterac Pass", "Battlefield of Eternity", "Blackheart's Bay",
        "Braxis Holdout", "Cursed Hollow", "Dragon Shire", "Garden of Terror",
        "Hanamura Temple", "Haunted Mines", "Infernal Shrines", "Sky Temple",
        "Tomb of the Spider Queen", "Towers of Doom", "Volskaya Foundry",
    ]

    def __init__(self):
        super().__init__()
        self.engine   = DraftAssistant()
        self.settings = overlay.load_settings()
        self.overlay_panel: Optional[overlay.ComparisonPanel] = None
        self.settings_window = None
        self.me_slot  = 0
        self._calc_timer = QtCore.QTimer(singleShot=True)
        self._calc_timer.timeout.connect(self._calculate)

        self.setWindowTitle("HotS Draft Assistant")
        self.resize(1020, 740)
        self._set_dark_palette()
        self._build_ui()

    # ── Theme ─────────────────────────────────────────────────────────────────
    def _set_dark_palette(self):
        p = QtGui.QPalette()
        p.setColor(QtGui.QPalette.Window,          QtGui.QColor(_DARK))
        p.setColor(QtGui.QPalette.WindowText,       QtGui.QColor("#C9D1D9"))
        p.setColor(QtGui.QPalette.Base,             QtGui.QColor(_PANEL))
        p.setColor(QtGui.QPalette.AlternateBase,    QtGui.QColor(_DARK))
        p.setColor(QtGui.QPalette.Text,             QtGui.QColor("#C9D1D9"))
        p.setColor(QtGui.QPalette.Button,           QtGui.QColor(_PANEL))
        p.setColor(QtGui.QPalette.ButtonText,       QtGui.QColor("#C9D1D9"))
        p.setColor(QtGui.QPalette.Highlight,        QtGui.QColor("#1A6DB5"))
        p.setColor(QtGui.QPalette.HighlightedText,  QtGui.QColor("#FFFFFF"))
        QApplication.setPalette(p)
        self.setStyleSheet(f"""
            QMainWindow,QWidget{{background:{_DARK};color:#C9D1D9;}}
            QGroupBox{{border:1px solid #2A3A4A;border-radius:6px;
                margin-top:8px;padding-top:8px;color:#8EA7CC;font-size:11px;}}
            QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}}
            QPushButton{{background:#21262D;border:1px solid #30363D;color:#C9D1D9;
                border-radius:5px;padding:5px 12px;font-size:11px;}}
            QPushButton:hover{{background:#2D333B;border-color:#58A6FF;}}
            QPushButton:pressed{{background:#1A6DB5;}}
            QPushButton:disabled{{color:#484F58;border-color:#21262D;}}
            QComboBox{{background:#21262D;border:1px solid #30363D;
                color:#C9D1D9;border-radius:4px;padding:4px 8px;}}
            QComboBox::drop-down{{border:none;}}
            QComboBox QAbstractItemView{{background:#161B22;color:#C9D1D9;
                border:1px solid #30363D;selection-background-color:#1A6DB5;}}
            QLineEdit{{background:#21262D;border:1px solid #30363D;
                color:#C9D1D9;border-radius:4px;padding:4px 8px;}}
            QProgressBar{{background:#21262D;border:1px solid #30363D;
                border-radius:5px;text-align:center;color:#FFFFFF;}}
            QProgressBar::chunk{{background:#1A6DB5;border-radius:5px;}}
            QPlainTextEdit{{background:#0D1117;border:1px solid #21262D;
                color:#8B949E;border-radius:4px;}}
        """)

    # ── UI build ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        heroes  = [h["hero_name"] for h in self.engine.db.get_all_heroes()]
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(10, 8, 10, 8)

        root.addLayout(self._build_header())
        root.addLayout(self._build_map_row())
        root.addLayout(self._build_draft_columns(heroes))
        root.addLayout(self._build_recs_panel())
        root.addWidget(self._build_log())

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        title = QLabel("HotS Draft Assistant")
        title.setStyleSheet(
            "font-size:15px;font-weight:bold;"
            f"color:{_MAP_COLOR};letter-spacing:2px;"
        )
        self.demo1_btn = QPushButton("🎬 Демо 1")
        self.demo2_btn = QPushButton("🎬 Демо 2")
        self.demo1_btn.setToolTip("2 игрока слева, 3 справа, по 3 бана")
        self.demo2_btn.setToolTip("По 2 бана с каждой стороны, 1 пик слева, 1 пик справа")
        self.import_btn = QPushButton("📥 Импорт статистики")
        self.import_btn.setToolTip("Загрузить статистику из JSON-файлов реплеев в базу данных")
        self.sett_btn = QPushButton("⚙ Настройки")
        self.ovrl_chk = QtWidgets.QCheckBox("Оверлей")
        self.ovrl_chk.setChecked(self.settings.get("overlay_enabled", True))
        self.demo1_btn.clicked.connect(lambda: self._run_demo(1))
        self.demo2_btn.clicked.connect(lambda: self._run_demo(2))
        self.import_btn.clicked.connect(self.import_stats)
        self.sett_btn.clicked.connect(self.open_settings)
        self.ovrl_chk.toggled.connect(self.toggle_overlay)
        h.addWidget(title)
        h.addStretch()
        for w in (self.demo1_btn, self.demo2_btn, self.import_btn,
                  self.sett_btn, self.ovrl_chk):
            h.addWidget(w)
        return h

    def _build_map_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch()
        lbl = QLabel("КАРТА")
        lbl.setStyleSheet(f"color:{_MAP_COLOR};font-size:11px;letter-spacing:2px;")
        self.map_combo = QComboBox()
        self.map_combo.addItems(self.MAPS)
        self.map_combo.setMinimumWidth(230)
        self.map_combo.currentTextChanged.connect(self._on_change)
        h.addWidget(lbl)
        h.addSpacing(8)
        h.addWidget(self.map_combo)
        h.addStretch()
        return h

    def _build_draft_columns(self, heroes: List[str]) -> QHBoxLayout:
        draft = QHBoxLayout()
        draft.setSpacing(10)

        # ── Ally column ───────────────────────────────────────────────────
        ally_v = QVBoxLayout()
        ally_v.setSpacing(4)
        ally_title = QLabel("◀  СВОЯ КОМАНДА")
        ally_title.setStyleSheet(
            f"color:{_ALLY_BORDER};font-size:11px;font-weight:bold;letter-spacing:1px;"
        )
        ally_title.setAlignment(Qt.AlignCenter)
        ally_v.addWidget(ally_title)

        ally_ban_h = QHBoxLayout()
        ally_ban_h.setSpacing(4)
        self.ally_bans: List[BanSlot] = []
        for _ in range(3):
            b = BanSlot(heroes)
            b.changed.connect(self._on_change)
            ally_ban_h.addWidget(b)
            self.ally_bans.append(b)
        ally_v.addLayout(ally_ban_h)

        self.ally_slots: List[PlayerSlot] = []
        for i in range(5):
            s = PlayerSlot(i, "ally", heroes)
            s.changed.connect(self._on_change)
            s.me_clicked.connect(self._set_me)
            ally_v.addWidget(s)
            self.ally_slots.append(s)
        self.ally_slots[0].set_me(True)

        # ── Centre panel ──────────────────────────────────────────────────
        ctr = QVBoxLayout()
        ctr.setSpacing(6)
        ctr.setAlignment(Qt.AlignTop)

        calc_btn = QPushButton("⚡ Рассчитать")
        calc_btn.setToolTip("Пересчитать прогноз и рекомендации")
        calc_btn.setStyleSheet(
            "QPushButton{background:#1A3A1A;border:1px solid #2A6A2A;"
            "color:#4ACA4A;font-size:12px;font-weight:bold;"
            "border-radius:5px;padding:8px 16px;}"
            "QPushButton:hover{background:#1E4A1E;}"
        )
        calc_btn.clicked.connect(self._calculate)

        reset_btn = QPushButton("↺ Сброс")
        reset_btn.clicked.connect(self._reset_all_confirm)

        finish_btn = QPushButton("🏁 Закончить игру")
        finish_btn.setToolTip("Сохранить текущий матч в базу данных")
        finish_btn.setStyleSheet(
            "QPushButton{background:#2A2A3A;border:1px solid #4A4A6A;"
            "color:#9A9ACA;font-size:11px;border-radius:5px;padding:6px 10px;}"
            "QPushButton:hover{background:#34344A;}"
        )
        finish_btn.clicked.connect(self._finish_game)

        self.ally_mmr_lbl = QLabel("—")
        self.ally_mmr_lbl.setAlignment(Qt.AlignCenter)
        self.ally_mmr_lbl.setStyleSheet(f"color:{_ALLY_BORDER};font-size:11px;")

        self.enemy_mmr_lbl = QLabel("—")
        self.enemy_mmr_lbl.setAlignment(Qt.AlignCenter)
        self.enemy_mmr_lbl.setStyleSheet(f"color:{_ENEMY_BORDER};font-size:11px;")

        vs_lbl = QLabel("VS")
        vs_lbl.setAlignment(Qt.AlignCenter)
        vs_lbl.setStyleSheet("color:#555;font-size:16px;font-weight:bold;")

        win_lbl = QLabel("вероятность победы")
        win_lbl.setAlignment(Qt.AlignCenter)
        win_lbl.setStyleSheet("color:#555;font-size:9px;")

        self.prob_bar = QtWidgets.QProgressBar()
        self.prob_bar.setRange(0, 100)
        self.prob_bar.setValue(50)
        self.prob_bar.setFormat("%p%")
        self.prob_bar.setFixedHeight(20)

        for w in (calc_btn, reset_btn, finish_btn):
            ctr.addWidget(w)
        ctr.addSpacing(16)
        for w in (self.ally_mmr_lbl, vs_lbl, self.enemy_mmr_lbl,
                  win_lbl, self.prob_bar):
            ctr.addWidget(w)
        ctr.addStretch()

        # ── Enemy column ──────────────────────────────────────────────────
        enemy_v = QVBoxLayout()
        enemy_v.setSpacing(4)
        enemy_title = QLabel("КОМАНДА ПРОТИВНИКА  ▶")
        enemy_title.setStyleSheet(
            f"color:{_ENEMY_BORDER};font-size:11px;font-weight:bold;letter-spacing:1px;"
        )
        enemy_title.setAlignment(Qt.AlignCenter)
        enemy_v.addWidget(enemy_title)

        enemy_ban_h = QHBoxLayout()
        enemy_ban_h.setSpacing(4)
        self.enemy_bans: List[BanSlot] = []
        for _ in range(3):
            b = BanSlot(heroes)
            b.changed.connect(self._on_change)
            enemy_ban_h.addWidget(b)
            self.enemy_bans.append(b)
        enemy_v.addLayout(enemy_ban_h)

        self.enemy_slots: List[PlayerSlot] = []
        for i in range(5):
            s = PlayerSlot(i, "enemy", heroes)
            s.changed.connect(self._on_change)
            enemy_v.addWidget(s)
            self.enemy_slots.append(s)

        draft.addLayout(ally_v,  40)
        draft.addLayout(ctr,     20)
        draft.addLayout(enemy_v, 40)
        return draft

    def _build_recs_panel(self) -> QHBoxLayout:
        outer = QHBoxLayout()
        outer.setSpacing(12)

        ban_box = QGroupBox("Рекомендации по банам")
        ban_h   = QHBoxLayout(ban_box)
        ban_h.setSpacing(6)
        self.ban_chips: List[RecoChip] = []
        for _ in range(config.N_BAN_RECOMMENDATIONS):
            c = RecoChip("ban")
            ban_h.addWidget(c)
            self.ban_chips.append(c)
        ban_h.addStretch()
        outer.addWidget(ban_box, 35)

        pick_box = QGroupBox("Рекомендации по пикам")
        pick_h   = QHBoxLayout(pick_box)
        pick_h.setSpacing(6)
        self.pick_chips: List[RecoChip] = []
        for _ in range(config.N_PICK_RECOMMENDATIONS):
            c = RecoChip("pick")
            pick_h.addWidget(c)
            self.pick_chips.append(c)
        pick_h.addStretch()
        outer.addWidget(pick_box, 65)

        return outer

    def _build_log(self) -> QPlainTextEdit:
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(66)
        return self.log

    # ── Slots & helpers ────────────────────────────────────────────────────────
    def _log(self, msg: str):
        self.log.appendPlainText(msg)

    def _on_change(self):
        self._calc_timer.start(400)

    def _set_me(self, idx: int):
        self.me_slot = idx
        for i, s in enumerate(self.ally_slots):
            s.set_me(i == idx)

    def _reset_all_confirm(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Подтверждение сброса")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Сбросить весь введённый состав матча?")
        yes = box.addButton("Сбросить", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Отмена", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec_()
        if box.clickedButton() is yes:
            self._reset_all()

    def _reset_all(self):
        for s in self.ally_slots + self.enemy_slots:
            s.player = ""; s.hero = ""; s.grade = ""; s.is_otp = False
            s._refresh()
        for b in self.ally_bans + self.enemy_bans:
            b.clear()
        for c in self.ban_chips + self.pick_chips:
            c.clear()
        self.prob_bar.setValue(50)
        self.ally_mmr_lbl.setText("—")
        self.enemy_mmr_lbl.setText("—")
        self._log("Сброс.")

    # ── Finish game → save match to DB ─────────────────────────────────────────
    def _finish_game(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Закончить игру")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Кто победил в этом матче?")
        ally = box.addButton("Моя команда", QtWidgets.QMessageBox.AcceptRole)
        enemy = box.addButton("Команда противника", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Отмена", QtWidgets.QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked not in (ally, enemy):
            return
        winner = "ally" if clicked is ally else "enemy"
        match = self._build_match(winner)
        if match is None:
            QtWidgets.QMessageBox.warning(
                self, "Закончить игру",
                "Не заполнены игроки и герои — матч не сохранён.")
            return
        res = self.engine.import_matches_dict([match])
        if res["errors"]:
            self._log(f"Матч не сохранён: {res['errors'][0][1]}")
            QtWidgets.QMessageBox.warning(self, "Закончить игру",
                                          "Не удалось сохранить матч.")
            return
        self._log(f"Матч сохранён ({'победа' if winner=='ally' else 'поражение'}), "
                  f"игроков: {len(match['players'])}.")
        QtWidgets.QMessageBox.information(
            self, "Закончить игру",
            f"Матч добавлен в базу данных.\nПобедитель: "
            f"{'моя команда' if winner=='ally' else 'команда противника'}.")
        self._calculate()

    def _build_match(self, winner: str):
        """Assemble a match document from the current draft state."""
        from datetime import datetime
        map_name = self.map_combo.currentText() or None
        players = []
        for team, slots in (("ally", self.ally_slots), ("enemy", self.enemy_slots)):
            for s in slots:
                if not s.player or not s.hero:
                    continue
                role = None
                row = self.engine.db.conn.execute(
                    "SELECT hero_role FROM Hero WHERE hero_name = ?", (s.hero,)).fetchone()
                if row:
                    role = row["hero_role"]
                players.append({
                    "battletag": s.player, "team": team, "hero": s.hero,
                    "role": role, "is_winner": (team == winner),
                    "kills": 0, "deaths": 0, "assists": 0,
                })
        if not players:
            return None
        bans = [b.hero for b in self.ally_bans + self.enemy_bans if b.hero]
        return {
            "match_id": "manual_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            "map_name": map_name, "game_mode": "manual",
            "players": players, "bans": bans,
        }

    # ── Calculate ──────────────────────────────────────────────────────────────
    def _calculate(self):
        map_name  = self.map_combo.currentText() or None
        all_ally  = [s.player or f"Ally{i+1}"  for i, s in enumerate(self.ally_slots)]
        all_enemy = [s.player or f"Enemy{i+1}" for i, s in enumerate(self.enemy_slots)]
        me_player = self.ally_slots[self.me_slot].player or all_ally[self.me_slot]

        try:
            self.engine.start_session(all_ally, all_enemy, map_name)
        except Exception as e:
            self._log(f"Ошибка: {e}"); return

        ally_picks  = [s.hero or None for s in self.ally_slots]
        enemy_picks = [s.hero or None for s in self.enemy_slots]
        all_bans    = [b.hero for b in self.ally_bans + self.enemy_bans if b.hero]
        self.engine.update_draft_state(all_bans, ally_picks, enemy_picks)

        for slot in self.ally_slots + self.enemy_slots:
            if slot.player:
                try:
                    p = self.engine.analyzer.build_profile(slot.player)
                    slot.update_profile(p.letter, p.is_otp)
                except Exception:
                    pass

        try:
            recs = self.engine.recommendations(me_player, map_name)
        except Exception as e:
            self._log(f"Ошибка рекомендаций: {e}"); return
        if not recs:
            return

        pred = recs["prediction"]
        self.prob_bar.setValue(int(pred["ally_win_probability"] * 100))
        self.ally_mmr_lbl.setText(f"MMR {pred['ally_mmr']}")
        self.enemy_mmr_lbl.setText(f"MMR {pred['enemy_mmr']}")

        for chip, ban in zip(self.ban_chips, recs["bans"]):
            chip.set_ban(ban.hero, ban.reason, ban.is_otp_ban)
        for chip, pick in zip(self.pick_chips, recs["picks"]):
            chip.set_pick(pick.hero, pick.score, pick.reason)

        if self.overlay_panel:
            self.overlay_panel.update_prediction(
                pred["ally_mmr"], pred["enemy_mmr"],
                pred["ally_win_probability"], pred["partial_data"])
            self.overlay_panel.update_bans(recs["bans"])
            self.overlay_panel.update_picks(recs["picks"])

        self._log(f"Готово. Прогноз победы: {int(pred['ally_win_probability']*100)}%")

    # ── Demo scenarios ─────────────────────────────────────────────────────────
    def _run_demo(self, number: int):
        self._reset_all()
        data = scenario_1(self.engine) if number == 1 else scenario_2(self.engine)
        self._load_scenario(data)
        self._log(f"Загружен сценарий {number}.")

    def _load_scenario(self, data: dict):
        for idx, player, hero in data["ally"]:
            self.ally_slots[idx].player = player
            self.ally_slots[idx].hero   = hero
            self.ally_slots[idx]._refresh()
        for idx, player, hero in data["enemy"]:
            self.enemy_slots[idx].player = player
            self.enemy_slots[idx].hero   = hero
            self.enemy_slots[idx]._refresh()
        for i, hero in enumerate(data.get("ally_bans", [])):
            self.ally_bans[i].hero = hero
            self.ally_bans[i]._refresh()
        for i, hero in enumerate(data.get("enemy_bans", [])):
            self.enemy_bans[i].hero = hero
            self.enemy_bans[i]._refresh()
        self.map_combo.setCurrentText(data.get("map", ""))
        self._set_me(data.get("me_slot", 0))
        self._calculate()

    # ── Overlay / Settings ─────────────────────────────────────────────────────
    # ── Data import ────────────────────────────────────────────────────────────
    def import_stats(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Выберите JSON-файлы статистики реплеев",
            "", "JSON (*.json);;Все файлы (*.*)")
        if not paths:
            return
        result = self.engine.import_matches(paths)
        msg = (f"Импортировано файлов: {result['files']}, "
               f"матчей: {result['matches']}.")
        if result["errors"]:
            msg += f"\nОшибок: {len(result['errors'])}"
        self._log(msg)
        for name, err in result["errors"]:
            self._log(f"  ! {name}: {err}")
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Импорт статистики")
        box.setText(msg)
        box.setIcon(QtWidgets.QMessageBox.Information
                    if not result["errors"] else QtWidgets.QMessageBox.Warning)
        box.exec_()
        # Recompute so freshly imported profiles are reflected immediately.
        self._calculate()

    def toggle_overlay(self, enabled: bool):
        self.settings["overlay_enabled"] = enabled
        overlay.save_settings(self.settings)
        if enabled:
            if self.overlay_panel is None:
                self.overlay_panel = overlay.ComparisonPanel(self.settings)
            self.overlay_panel.show()
        elif self.overlay_panel:
            self.overlay_panel.hide()

    def open_settings(self):
        self.settings_window = overlay.SettingsWindow(
            self.settings, on_save=self._on_settings_saved)
        self.settings_window.show()

    def _on_settings_saved(self, s):
        self.settings = s
        if self.overlay_panel:
            self.overlay_panel.setWindowOpacity(s["overlay_opacity"] / 100.0)
        self._log("Настройки сохранены.")

    def closeEvent(self, event):
        if self.overlay_panel:
            self.overlay_panel.close()
        self.engine.close()
        event.accept()


def run():
    app = QApplication(sys.argv)
    app.setFont(QtGui.QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run()
