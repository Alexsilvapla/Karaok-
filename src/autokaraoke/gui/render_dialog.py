"""Render settings: font, colours, layout, ball, background, with a live preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from autokaraoke.export.ass import AssStyle, save_default_style
from autokaraoke.gui.lyrics_panel import fmt_time
from autokaraoke.gui.preview import KaraokePreview
from autokaraoke.project import Project

COLORS = (
    ("sung_color", "Cantado"),
    ("unsung_color", "A cantar"),
    ("next_color", "Próxima linha"),
    ("backing_color", "Vozes de apoio"),
    ("outline_color", "Contorno"),
    ("background_color", "Fundo"),
    ("ball_color", "Bolinha"),
)
RESOLUTIONS = (("1080p (1920×1080)", 1920, 1080), ("720p (1280×720)", 1280, 720))


class ColorButton(QPushButton):
    def __init__(self, color: str, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self.setFixedWidth(90)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.color = QColor(color).name().upper()
        c = QColor(self.color)
        text = "#000" if 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140 else "#fff"
        self.setText(self.color)
        self.setStyleSheet(f"background: {self.color}; color: {text}; border: 1px solid rgba(255,255,255,60); "
                           "border-radius: 8px; padding: 6px 10px; font-weight: 600")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self, "Escolher cor")
        if c.isValid():
            self.set_color(c.name())
            self._on_change()


class RenderDialog(QDialog):
    def __init__(self, project: Project, style: AssStyle, output: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gerar vídeo")
        self.project = project
        self._style = AssStyle.from_dict(style.to_dict())
        st = self._style
        v = QVBoxLayout(self)

        self.preview = KaraokePreview()
        self.preview.setMinimumHeight(200)
        self.preview.set_project(project)
        v.addWidget(self.preview, 1)
        self.time = QSlider(Qt.Orientation.Horizontal)
        self.time.setRange(0, int(max(project.duration, 1.0) * 10))
        first = next((sp[0] for ln in project.lines if (sp := ln.span())), 0.0)
        self.time.setValue(int((first + 1.0) * 10))
        self.time_label = QLabel()
        row = QHBoxLayout()
        row.addWidget(QLabel("Pré-visualizar em"))
        row.addWidget(self.time, 1)
        row.addWidget(self.time_label)
        v.addLayout(row)

        cols = QHBoxLayout()
        text_box = QGroupBox("Texto")
        form = QFormLayout(text_box)
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(st.font))
        self.size = QSpinBox()
        self.size.setRange(30, 160)
        self.size.setValue(st.size)
        self.size.setSuffix(" px")
        self.size.setToolTip("Tamanho da fonte em 1080p")
        self.bold = QCheckBox("Negrito")
        self.bold.setChecked(st.bold)
        self.outline = QSpinBox()
        self.outline.setRange(0, 12)
        self.outline.setValue(round(st.outline))
        self.outline.setSuffix(" px")
        self.layout_ = QComboBox()
        self.layout_.addItem("Duas linhas alternadas", "alternate")
        self.layout_.addItem("Linha atual em cima, próxima embaixo", "scroll")
        self.layout_.setCurrentIndex(max(0, self.layout_.findData(st.layout)))
        self.layout_.setToolTip("Alternadas: a linha de cima é cantada, depois a de baixo, enquanto a de cima é trocada pela linha seguinte; assim o texto está sempre na tela")
        self.ball = QCheckBox("Bolinha pulando sobre as sílabas")
        self.ball.setChecked(st.ball)
        self.countdown = QCheckBox("Pontos de contagem regressiva após pausas longas")
        self.countdown.setChecked(st.countdown)
        form.addRow("Fonte", self.font)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size)
        size_row.addWidget(self.bold)
        size_row.addWidget(QLabel("Contorno"))
        size_row.addWidget(self.outline)
        form.addRow("Tamanho", size_row)
        form.addRow("Disposição", self.layout_)
        form.addRow(self.ball)
        form.addRow(self.countdown)
        cols.addWidget(text_box, 3)

        color_box = QGroupBox("Cores")
        grid = QGridLayout(color_box)
        self.colors: dict[str, ColorButton] = {}
        for k, (key, label) in enumerate(COLORS):
            btn = ColorButton(getattr(st, key), self._changed)
            self.colors[key] = btn
            grid.addWidget(QLabel(label), k % 4, (k // 4) * 2)
            grid.addWidget(btn, k % 4, (k // 4) * 2 + 1)
        cols.addWidget(color_box, 2)
        v.addLayout(cols)

        out_box = QGroupBox("Vídeo")
        form = QFormLayout(out_box)
        self.background = QLineEdit(st.background_image)
        self.background.setPlaceholderText("nenhuma: cor de fundo lisa")
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.background, 1)
        browse = QPushButton("Procurar…")
        browse.clicked.connect(self._browse_background)
        bg_row.addWidget(browse)
        form.addRow("Imagem de fundo", bg_row)
        self.resolution = QComboBox()
        for label, w, h in RESOLUTIONS:
            self.resolution.addItem(label, (w, h))
        self.resolution.setCurrentIndex(0 if st.height >= 1080 else 1)
        form.addRow("Resolução", self.resolution)
        self.output = QLineEdit(str(output))
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        browse = QPushButton("Procurar…")
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(browse)
        form.addRow("Arquivo de saída", out_row)
        v.addWidget(out_box)

        buttons = QDialogButtonBox()
        self.btn_default = buttons.addButton("Salvar como padrão", QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_default.setToolTip("Usar este estilo em novos projetos (e em projetos sem estilo próprio)")
        self.btn_default.clicked.connect(self._save_default)
        self.btn_save = buttons.addButton("Salvar estilo", QDialogButtonBox.ButtonRole.ApplyRole)
        self.btn_save.setToolTip("Guardar este estilo no projeto sem gerar o vídeo")
        self.btn_save.clicked.connect(lambda: self.done(2))
        buttons.addButton("Gerar", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        self.font.currentFontChanged.connect(self._changed)
        for w in (self.size, self.outline):
            w.valueChanged.connect(self._changed)
        for w in (self.bold, self.ball, self.countdown):
            w.toggled.connect(self._changed)
        self.layout_.currentIndexChanged.connect(self._changed)
        self.time.valueChanged.connect(self._time_changed)
        self._changed()
        self._time_changed()
        self.resize(900, 720)

    # ---- values -----------------------------------------------------------

    def style(self) -> AssStyle:
        st = AssStyle.from_dict(self._style.to_dict())
        st.font = self.font.currentFont().family()
        st.size = self.size.value()
        st.bold = self.bold.isChecked()
        st.outline = float(self.outline.value())
        st.shadow = min(st.shadow, st.outline) if st.outline else 0.0
        st.layout = self.layout_.currentData()
        st.ball = self.ball.isChecked()
        st.countdown = self.countdown.isChecked()
        for key, btn in self.colors.items():
            setattr(st, key, btn.color)
        st.background_image = self.background.text().strip()
        st.width, st.height = self.resolution.currentData()
        return st

    def output_path(self) -> Path:
        return Path(self.output.text().strip())

    # ---- slots ------------------------------------------------------------

    def _changed(self, *_args) -> None:
        self.preview.set_style(self.style())

    def _time_changed(self) -> None:
        t = self.time.value() / 10
        self.time_label.setText(fmt_time(t))
        self.preview.set_time(t)

    def _browse_background(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Imagem de fundo", self.background.text(),
                                           "Imagens (*.png *.jpg *.jpeg *.webp)")
        if f:
            self.background.setText(f)

    def _browse_output(self) -> None:
        f, _ = QFileDialog.getSaveFileName(self, "Gerar vídeo", self.output.text(), "Vídeo (*.mkv *.mp4)")
        if f:
            self.output.setText(f)

    def _save_default(self) -> None:
        st = self.style()
        st.background_image = ""  # specific to a song
        path = save_default_style(st)
        self.btn_default.setText("Salvo como padrão ✓")
        self.btn_default.setToolTip(str(path))
