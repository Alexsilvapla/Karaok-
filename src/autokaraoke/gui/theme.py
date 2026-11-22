"""Modern dark theme: palette, Qt style sheet and application-wide setup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).parent / "assets"

# Colour tokens (also used by the custom-painted widgets: timeline, preview).
TOKENS = {
    "BG": "#0f111a",
    "SURFACE": "#171a26",
    "SURFACE2": "#1f2333",
    "HOVER": "#272c42",
    "BORDER": "#2a2f45",
    "BORDER_HI": "#3a4060",
    "TEXT": "#e6e8f2",
    "MUTED": "#8b90a8",
    "MUTED_DIM": "#5b6079",
    "ACCENT": "#7c5cff",
    "ACCENT_HOVER": "#917aff",
    "ACCENT_SOFT": "rgba(124, 92, 255, 0.20)",
    "OK": "#3ecf8e",
    "WARN": "#f5a524",
    "DANGER": "#ef5b5b",
}


def color(name: str) -> QColor:
    return QColor(TOKENS[name])


def _icon(name: str) -> str:
    return (ASSETS / name).as_posix()


_QSS = """
* { outline: 0; }
QWidget { color: @TEXT; }
QMainWindow, QDialog, QMessageBox { background: @BG; }
QToolTip { background: @SURFACE2; color: @TEXT; border: 1px solid @BORDER_HI; padding: 6px 8px; }

/* ---- menus ---- */
QMenuBar { background: @SURFACE; border-bottom: 1px solid @BORDER; padding: 2px 6px; }
QMenuBar::item { background: transparent; padding: 5px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: @SURFACE2; }
QMenu { background: @SURFACE2; border: 1px solid @BORDER_HI; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: @ACCENT_SOFT; }
QMenu::item:disabled { color: @MUTED_DIM; }
QMenu::separator { height: 1px; background: @BORDER; margin: 6px 8px; }

/* ---- main toolbar ---- */
QToolBar { background: @SURFACE; border: 0; border-bottom: 1px solid @BORDER; padding: 8px 12px; spacing: 6px; }
QToolBar::separator { background: @BORDER; width: 1px; margin: 6px 8px; }
QToolBar QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 7px 12px; font-weight: 500; }
QToolBar QToolButton:hover { background: @SURFACE2; }
QToolBar QToolButton:pressed { background: @BORDER; }
QToolBar QToolButton:disabled { color: @MUTED_DIM; background: transparent; }
QToolBar QToolButton[primary="true"] { background: @ACCENT; color: white; font-weight: 600; padding: 7px 18px; }
QToolBar QToolButton[primary="true"]:hover { background: @ACCENT_HOVER; }
QToolBar QToolButton[primary="true"]:disabled { background: @SURFACE2; color: @MUTED_DIM; }
QToolBar QComboBox { min-width: 150px; }
QLabel#stepArrow { color: @MUTED_DIM; font-size: 16px; padding: 0 2px; }
QToolBar#linesBar { background: transparent; border: 0; padding: 0 6px 4px 6px; spacing: 2px; }
QToolBar#linesBar QToolButton { padding: 4px 8px; font-size: 12px; color: @MUTED; }
QToolBar#linesBar QToolButton:hover { color: @TEXT; }
QToolBar#linesBar QToolButton:disabled { color: @MUTED_DIM; }

/* ---- cards and panels ---- */
QFrame#card, QFrame#panel { background: @SURFACE; border: 1px solid @BORDER; border-radius: 12px; }
QLabel#panelTitle { font-size: 11px; font-weight: 700; color: @MUTED; padding: 10px 14px 4px 14px; }
QLabel#panelCount { font-size: 11px; color: @MUTED_DIM; padding: 10px 14px 4px 14px; }
QLabel#muted { color: @MUTED; }
QLabel#time { font-family: "Cascadia Mono", "JetBrains Mono", Consolas, "DejaVu Sans Mono", monospace;
    font-size: 20px; font-weight: 600; padding: 0 6px; }
QLabel#syllable { font-size: 14px; font-weight: 600; }
QLabel#hint { color: @MUTED; font-size: 12px; padding: 4px 6px; }

/* ---- buttons ---- */
QPushButton, QToolButton { background: @SURFACE2; border: 1px solid @BORDER; border-radius: 8px; padding: 6px 12px; }
QPushButton:hover, QToolButton:hover { background: @HOVER; border-color: @BORDER_HI; }
QPushButton:pressed, QToolButton:pressed { background: @BORDER; }
QPushButton:disabled, QToolButton:disabled { color: @MUTED_DIM; background: @SURFACE; }
QPushButton:default, QPushButton[primary="true"] { background: @ACCENT; border-color: @ACCENT; color: white; font-weight: 600; }
QPushButton:default:hover, QPushButton[primary="true"]:hover { background: @ACCENT_HOVER; border-color: @ACCENT_HOVER; }
QToolButton:checked { background: @ACCENT_SOFT; border-color: @ACCENT; }
QToolButton#playBtn { background: @ACCENT; border: 0; border-radius: 22px; padding: 0; font-size: 18px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; color: white; }
QToolButton#playBtn:hover { background: @ACCENT_HOVER; }
QToolButton#playBtn:disabled { background: @SURFACE2; color: @MUTED_DIM; }
QToolButton#zoomBtn { padding: 2px 0; min-width: 28px; max-width: 28px; font-size: 15px; }
QPushButton#bigPrimary, QPushButton#bigSecondary { padding: 12px 30px; font-size: 14px; border-radius: 10px; }
QPushButton#bigPrimary { background: @ACCENT; border-color: @ACCENT; color: white; font-weight: 600; }
QPushButton#bigPrimary:hover { background: @ACCENT_HOVER; border-color: @ACCENT_HOVER; }

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: @BG; border: 1px solid @BORDER; border-radius: 8px; padding: 6px 10px;
    selection-background-color: @ACCENT; selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QComboBox:on { border-color: @ACCENT; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: @MUTED_DIM; }
QComboBox::drop-down { border: 0; width: 26px; }
QComboBox::down-arrow { image: url(@CHEVRON_DOWN); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @SURFACE2; border: 1px solid @BORDER_HI; border-radius: 8px;
    padding: 4px; selection-background-color: @ACCENT_SOFT; selection-color: @TEXT; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { border: 0; background: transparent; width: 20px; }
QAbstractSpinBox::up-arrow { image: url(@CHEVRON_UP); width: 10px; height: 10px; }
QAbstractSpinBox::down-arrow { image: url(@CHEVRON_DOWN); width: 10px; height: 10px; }
QPlainTextEdit#log { background: transparent; border: 0; color: @MUTED; font-size: 12px;
    font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; }

/* ---- lists ---- */
QListWidget { background: transparent; border: 0; padding: 4px 6px; }
QListWidget::item { padding: 7px 10px; border-radius: 8px; margin: 1px 0; }
QListWidget::item:hover { background: @SURFACE2; }
QListWidget::item:selected { background: @ACCENT_SOFT; color: @TEXT; }
QListWidget#recent { background: @SURFACE; border: 1px solid @BORDER; border-radius: 12px; }

/* ---- sliders, checks, progress ---- */
QSlider::groove:horizontal { height: 4px; background: @BORDER_HI; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @ACCENT; border-radius: 2px; }
QSlider::handle:horizontal { background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: @ACCENT_HOVER; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid @BORDER_HI; background: @BG; }
QCheckBox::indicator:checked { background: @ACCENT; border-color: @ACCENT; image: url(@CHECK); }
QProgressBar { background: @SURFACE2; border: 0; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: @ACCENT; border-radius: 3px; }
QStatusBar { background: @SURFACE; border-top: 1px solid @BORDER; color: @MUTED; }
QStatusBar::item { border: 0; }
QGroupBox { border: 1px solid @BORDER; border-radius: 10px; margin-top: 14px; padding: 14px 10px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: @MUTED; }
QTabWidget::pane { border: 1px solid @BORDER; border-radius: 10px; top: -1px; }
QTabBar::tab { background: transparent; color: @MUTED; padding: 8px 16px; border-radius: 8px; margin-right: 2px; }
QTabBar::tab:selected { background: @SURFACE2; color: @TEXT; }

/* ---- scrollbars and splitters ---- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: @BORDER_HI; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:horizontal { background: @BORDER_HI; border-radius: 4px; min-width: 32px; }
QScrollBar::handle:hover { background: @MUTED_DIM; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 10px; }
QSplitter::handle:vertical { height: 10px; }
QSplitter::handle:hover { background: @ACCENT_SOFT; border-radius: 4px; }

/* ---- welcome screen ---- */
QLabel#welcomeTitle { font-size: 32px; font-weight: 700; }
QLabel#welcomeSub { color: @MUTED; font-size: 14px; }
"""


def stylesheet() -> str:
    qss = _QSS
    icons = {"CHEVRON_DOWN": _icon("chevron-down.svg"), "CHEVRON_UP": _icon("chevron-up.svg"),
             "CHECK": _icon("check.svg")}
    for key, value in sorted({**TOKENS, **icons}.items(), key=lambda kv: -len(kv[0])):
        qss = qss.replace("@" + key, value)  # longest names first: ACCENT_SOFT before ACCENT
    return qss


def apply(app: QApplication) -> None:
    """Dark Fusion palette (so native dialogs match too), font and style sheet."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, name in (
        (QPalette.ColorRole.Window, "BG"), (QPalette.ColorRole.WindowText, "TEXT"),
        (QPalette.ColorRole.Base, "BG"), (QPalette.ColorRole.AlternateBase, "SURFACE"),
        (QPalette.ColorRole.Text, "TEXT"), (QPalette.ColorRole.Button, "SURFACE2"),
        (QPalette.ColorRole.ButtonText, "TEXT"), (QPalette.ColorRole.ToolTipBase, "SURFACE2"),
        (QPalette.ColorRole.ToolTipText, "TEXT"), (QPalette.ColorRole.Highlight, "ACCENT"),
        (QPalette.ColorRole.HighlightedText, "TEXT"), (QPalette.ColorRole.PlaceholderText, "MUTED_DIM"),
        (QPalette.ColorRole.Link, "ACCENT_HOVER"),
    ):
        pal.setColor(role, color(name))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, color("MUTED_DIM"))
    app.setPalette(pal)
    font = QFont()
    font.setFamilies(["Inter", "Segoe UI", "SF Pro Text", "Noto Sans", "Ubuntu", "Sans Serif"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())
