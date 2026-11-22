"""Main editor window."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from autokaraoke import components, config, steps
from autokaraoke.gui.dialogs import HelpDialog, LineEditDialog, ProposalDialog, SettingsDialog
from autokaraoke.gui.jobs import Job
from autokaraoke.gui.lyrics_panel import LyricsPanel, fmt_time
from autokaraoke.gui.player import Player
from autokaraoke.gui.preview import KaraokePreview, current_line_index
from autokaraoke.gui.timeline import HINTS, Timeline, spectrogram_image
from autokaraoke.project import Project
from autokaraoke.text import edit as text_edit
from autokaraoke.text.edit import to_notation

UNDO_LIMIT = 100
MIN_DUR = 0.04
MIX_TRACK = "mix"  # track combo data for the generated karaoke mix
NUDGE = 0.01
ICON = Path(__file__).parent / "assets" / "icon.png"
AUDIO_EXT = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".mp4", ".mkv"}


class NewProjectDialog(QDialog):
    def __init__(self, parent=None, preset: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Novo projeto de karaokê")
        form = QFormLayout(self)
        row = QHBoxLayout()
        self.source = QLineEdit()
        placeholder = "Arquivo de áudio"
        if config.download_enabled():
            placeholder += " ou link do YouTube / YT Music"
        self.source.setPlaceholderText(placeholder)
        browse = QPushButton("Procurar…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.source)
        row.addWidget(browse)
        form.addRow("Origem", row)
        self.artist = QLineEdit()
        self.title = QLineEdit()
        self.lang = QLineEdit()
        self.artist.setPlaceholderText("deduzido do nome do arquivo (Artista - Título)")
        self.title.setPlaceholderText("deduzido do nome do arquivo (Artista - Título)")
        self.lang.setPlaceholderText("automático (ex.: pt, en, es)")
        form.addRow("Artista", self.artist)
        form.addRow("Título", self.title)
        form.addRow("Idioma", self.lang)
        self.out = QLineEdit(str(config.PROJECTS_DIR.resolve()))
        form.addRow("Pasta dos projetos", self.out)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(560, 0)
        if preset:
            self._set_source(preset)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher áudio", "", "Áudio (*.mp3 *.flac *.wav *.m4a *.ogg *.opus *.aac *.mp4 *.mkv)"
        )
        if path:
            self._set_source(path)

    def _set_source(self, path: str) -> None:
        self.source.setText(path)
        stem = Path(path).stem
        if " - " in stem and not self.artist.text() and not self.title.text():
            a, t = stem.split(" - ", 1)
            self.artist.setText(a.strip())
            self.title.setText(t.strip())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self.dirty = False
        self.undo_stack: list[list] = []
        self.redo_stack: list[list] = []
        self.job: Job | None = None
        self.tap_index = -1
        self.tap_prev = -1  # index of the last tapped syllable (Tap mode)
        self.tap_pressed = False
        # (start, end, loop): stop or loop playback at ``end``.
        self.play_range: tuple[float, float, bool] | None = None
        # Audio analysis per file path: (peaks, spectrogram image, onsets).
        self.analysis: dict[str, tuple] = {}
        self.bg_jobs: set[Job] = set()
        self.mix_spans: list | None = None  # backing spans the current karaoke mix was built with
        self.mix_timer = QTimer(self)  # rebuild the mix shortly after backing timings change
        self.mix_timer.setSingleShot(True)
        self.mix_timer.setInterval(600)
        self.mix_timer.timeout.connect(self._build_mix)
        self.settings = QSettings("AutoKaraoke", "AutoKaraoke")
        self._preset_source: str | None = None
        self.setAcceptDrops(True)

        self.player = Player(self)
        self.timeline = Timeline()
        self.canvas = self.timeline.canvas
        self.preview = KaraokePreview()
        self.lyrics = LyricsPanel()
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)

        self._build_actions()
        self._build_layout()
        self._connect()
        self._restore_settings()

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        QApplication.instance().installEventFilter(self)
        self._update_title()
        self._set_enabled()
        if components.packaged() and components.state() != "ok":
            QTimer.singleShot(400, lambda: self._ensure_ai(None))

    # ---- UI construction --------------------------------------------------

    def _action(self, text, slot, shortcut=None, tip=None) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        return a

    def _build_actions(self) -> None:
        self.act_new = self._action("Novo…", self.new_project, "Ctrl+N", "Criar um projeto a partir de um arquivo de áudio")
        self.act_open = self._action("Abrir…", self.open_dialog, "Ctrl+O")
        self.act_save = self._action("Salvar", self.save, "Ctrl+S")
        self.act_undo = self._action("Desfazer", self.undo, "Ctrl+Z")
        self.act_redo = self._action("Refazer", self.redo, "Ctrl+Shift+Z")
        self.act_lyrics = self._action("Letra", self.fetch_lyrics,
                                       tip="Buscar a letra no LRCLIB ou carregar um arquivo .lrc/.txt")
        self.act_fix = self._action("Corrigir letra (experimental)…", self.fix_lyrics,
                                    tip="Experimental: compara a letra com o que é cantado (reconhecimento de fala + LLM). Ative em Arquivo → Configurações")
        self.act_fix.setVisible(config.experimental_llm())
        self.act_settings = self._action("Configurações…", self.show_settings)
        self.act_separate = self._action("Separar", self.separate, tip="Separar voz e instrumental")
        self.act_align = self._action("Sincronizar", self.align, tip="Alinhamento automático das sílabas")
        self.act_render = self._action("Gerar vídeo…", self.render, "Ctrl+R")
        self.act_export = self._action("Exportar letra…", self.export, "Ctrl+E",
                                       "Salva a letra sincronizada como legenda ASS ou LRC aprimorado (sem vídeo: para isso use Gerar vídeo)")

        # Line actions work on the lines selected in the lyrics list (shortcuts active there).
        self.act_line_edit = self._action("Editar linha…", lambda: self.edit_line(self.lyrics.currentRow()),
                                          "Return", "Edita o texto e as sílabas; novas linhas dividem a linha")
        self.act_line_insert = self._action("Inserir linha abaixo…", self.insert_line, "Insert")
        self.act_line_delete = self._action("Excluir linhas", self.delete_lines, "Delete")
        self.act_line_merge = self._action("Juntar com a próxima linha", self.merge_lines, "Ctrl+J",
                                           "Junta as linhas selecionadas (ou a linha e a próxima)")
        self.act_line_backing = self._action(
            "Vozes de apoio liga/desliga", self.toggle_backing, "B",
            "Linhas de apoio (coro, vocalizes…) ficam no áudio do karaokê e aparecem como apoio")
        self.line_actions = [self.act_line_edit, self.act_line_insert, self.act_line_delete,
                             self.act_line_merge, self.act_line_backing]
        for a in self.line_actions:
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.lyrics.addAction(a)

        tb = self.addToolBar("Principal")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        def arrow() -> QLabel:
            lb = QLabel("›")
            lb.setObjectName("stepArrow")
            return lb

        for a in (self.act_new, self.act_open, self.act_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()
        # The pipeline, in the order you work through it.
        tb.addAction(self.act_lyrics)
        tb.addWidget(arrow())
        tb.addAction(self.act_separate)
        tb.addWidget(arrow())
        tb.addAction(self.act_align)
        self.engine = QComboBox()
        self.engine.addItem("Qwen + verificação MMS", "qwen")
        self.engine.addItem("MMS (qualquer idioma)", "mms")
        self.engine.addItem("Distribuição uniforme (linhas do LRC)", "naive")
        self.engine.setToolTip("Motor de alinhamento da sincronização")
        tb.addWidget(self.engine)
        tb.addAction(self.act_fix)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.act_export)
        tb.addAction(self.act_render)
        self.act_render.setToolTip("Gerar o vídeo de karaokê (Ctrl+R)")
        btn = tb.widgetForAction(self.act_render)
        if btn is not None:
            btn.setProperty("primary", True)

        file_menu = self.menuBar().addMenu("&Arquivo")
        for a in (self.act_new, self.act_open, self.act_save, self.act_export, self.act_render):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(self.act_settings)
        edit_menu = self.menuBar().addMenu("&Editar")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        lines_menu = self.menuBar().addMenu("&Linhas")
        for a in self.line_actions:
            lines_menu.addAction(a)
        help_menu = self.menuBar().addMenu("&Ajuda")
        help_menu.addAction(self._action("Atalhos de teclado", self.show_help, "F1"))

    # ---- layout helpers ---------------------------------------------------

    @staticmethod
    def _card() -> tuple[QFrame, QHBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)
        return card, h

    @staticmethod
    def _muted(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("muted")
        return lb

    @staticmethod
    def _panel(title: str, body: QWidget, extra: QWidget | None = None, margin: int = 0) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        v = QVBoxLayout(frame)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        t = QLabel(title.upper())
        t.setObjectName("panelTitle")
        head.addWidget(t)
        head.addStretch()
        if extra is not None:
            head.addWidget(extra)
        v.addLayout(head)
        if margin:
            holder = QWidget()
            hv = QVBoxLayout(holder)
            hv.setContentsMargins(margin, 0, margin, margin)
            hv.addWidget(body)
            body = holder
        v.addWidget(body, 1)
        return frame

    def _build_layout(self) -> None:
        # Card 1: playback.
        transport, h = self._card()
        self.btn_play = QToolButton()
        self.btn_play.setObjectName("playBtn")
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("Tocar / pausar (Espaço)")
        self.time_label = QLabel("00:00.00")
        self.time_label.setObjectName("time")
        self.time_label.setMinimumWidth(110)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(5, 30)  # × 5 %
        self.speed.setValue(20)
        self.speed.setPageStep(1)
        self.speed.setFixedWidth(140)
        self.speed.setToolTip("Velocidade de reprodução, 25–150 % (o tom é mantido)")
        self.speed_label = QToolButton()
        self.speed_label.setText("100%")
        self.speed_label.setToolTip("Voltar para 100 %")
        self.speed_label.setMinimumWidth(56)
        self.track = QComboBox()
        self.track.setToolTip("Áudio a tocar e a mostrar na linha do tempo")
        self.track.setMinimumWidth(150)
        self.view = QComboBox()
        self.view.addItem("Forma de onda", "wave")
        self.view.addItem("Espectrograma", "spec")
        self.view.addItem("Espectrograma + onda", "both")
        self.view.setToolTip("Exibição da linha do tempo. No espectrograma, as consoantes (t, k, s, p…) aparecem como listras verticais brilhantes: bons inícios de sílaba")
        zoom_in, zoom_out = QToolButton(), QToolButton()
        for btn, text in ((zoom_in, "+"), (zoom_out, "−")):
            btn.setText(text)
            btn.setObjectName("zoomBtn")
        zoom_in.setToolTip("Aproximar (Ctrl+roda do mouse)")
        zoom_out.setToolTip("Afastar (Ctrl+roda do mouse)")
        zoom_in.clicked.connect(lambda: self.canvas.zoom(1.4))
        zoom_out.clicked.connect(lambda: self.canvas.zoom(1 / 1.4))
        h.addWidget(self.btn_play)
        h.addWidget(self.time_label)
        h.addSpacing(12)
        for wdg in (self._muted("Velocidade"), self.speed, self.speed_label):
            h.addWidget(wdg)
        h.addSpacing(12)
        for wdg in (self._muted("Áudio"), self.track, self._muted("Exibição"), self.view):
            h.addWidget(wdg)
        h.addStretch()
        h.addWidget(self._muted("Zoom"))
        h.addWidget(zoom_out)
        h.addWidget(zoom_in)

        # Card 2: selected syllable and tap sync.
        inspector, h = self._card()
        self.syl_label = QLabel("Nenhuma sílaba selecionada")
        self.syl_label.setObjectName("syllable")
        self.syl_label.setMinimumWidth(190)
        self.syl_start = QDoubleSpinBox()
        self.syl_end = QDoubleSpinBox()
        for spin, tip in ((self.syl_start, "Início da sílaba selecionada (s)"),
                          (self.syl_end, "Fim da sílaba selecionada (s)")):
            spin.setDecimals(2)
            spin.setSingleStep(0.01)
            spin.setRange(0, 24 * 3600)
            spin.setKeyboardTracking(False)
            spin.setToolTip(tip + "; as setas mudam de 10 em 10 ms")
        self.btn_set_start = QToolButton()
        self.btn_set_start.setText("[ Início aqui")
        self.btn_set_start.setToolTip("Define o início na posição do cursor ([)")
        self.btn_set_end = QToolButton()
        self.btn_set_end.setText("Fim aqui ]")
        self.btn_set_end.setToolTip("Define o fim na posição do cursor (])")
        self.btn_play_syl = QToolButton()
        self.btn_play_syl.setText("▶ Sílaba")
        self.btn_play_syl.setToolTip("Tocar a sílaba selecionada (P)")
        self.btn_play_line = QToolButton()
        self.btn_play_line.setText("▶ Linha")
        self.btn_play_line.setToolTip("Tocar a linha da sílaba selecionada")
        self.btn_loop = QToolButton()
        self.btn_loop.setText("⟲ Repetir linha")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setToolTip("Repetir a linha da sílaba selecionada (L)")
        self.tap_mode = QComboBox()
        self.tap_mode.addItem("Desligado", "")
        self.tap_mode.addItem("Segurar: apertar = início, soltar = fim", "hold")
        self.tap_mode.addItem("Toque: cada toque inicia uma sílaba", "tap")
        self.tap_mode.setToolTip("Sincronia por toques com a barra de espaço, a partir da sílaba selecionada")
        self.latency = QSpinBox()
        self.latency.setRange(-300, 500)
        self.latency.setSuffix(" ms")
        self.latency.setValue(60)
        self.latency.setToolTip("Compensação do tempo de reação, descontada dos toques")
        h.addWidget(self.syl_label)
        for wdg in (self._muted("Início"), self.syl_start, self._muted("Fim"), self.syl_end,
                    self.btn_set_start, self.btn_set_end):
            h.addWidget(wdg)
        h.addSpacing(8)
        for wdg in (self.btn_play_syl, self.btn_play_line, self.btn_loop):
            h.addWidget(wdg)
        h.addStretch()
        for wdg in (self._muted("Sincronia por toques"), self.tap_mode, self.latency):
            h.addWidget(wdg)

        self.hint = QLabel()
        self.hint.setObjectName("hint")

        # Left: lyrics.
        lyrics_box = QWidget()
        v = QVBoxLayout(lyrics_box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        lines_bar = QToolBar()
        lines_bar.setObjectName("linesBar")
        lines_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        for a in self.line_actions:
            lines_bar.addAction(a)
        v.addWidget(lines_bar)
        v.addWidget(self.lyrics, 1)
        self.lines_count = QLabel("")
        self.lines_count.setObjectName("panelCount")

        # Right: preview and activity log.
        self.top_split = QSplitter(Qt.Orientation.Horizontal)
        self.top_split.setChildrenCollapsible(False)
        self.top_split.addWidget(self._panel("Letra", lyrics_box, self.lines_count))
        self.right_split = QSplitter(Qt.Orientation.Vertical)
        self.right_split.setChildrenCollapsible(False)
        self.right_split.addWidget(self._panel("Pré-visualização", self.preview, margin=10))
        self.right_split.addWidget(self._panel("Atividade", self.log_view))
        self.right_split.setSizes([260, 100])
        self.top_split.addWidget(self.right_split)
        self.top_split.setSizes([460, 700])

        # Bottom: transport, inspector and timeline.
        self.main_split = QSplitter(Qt.Orientation.Vertical)
        self.main_split.setChildrenCollapsible(False)
        self.main_split.addWidget(self.top_split)
        bottom = QWidget()
        v = QVBoxLayout(bottom)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(transport)
        v.addWidget(inspector)
        v.addWidget(self._panel("Linha do tempo", self.timeline, margin=8), 1)
        v.addWidget(self.hint)
        self.main_split.addWidget(bottom)
        self.main_split.setStretchFactor(0, 1)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setSizes([420, 380])

        editor = QWidget()
        ev = QVBoxLayout(editor)
        ev.setContentsMargins(12, 10, 12, 4)
        ev.addWidget(self.main_split)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome())  # 0: no project yet
        self.stack.addWidget(editor)  # 1: editor
        self.setCentralWidget(self.stack)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)  # indeterminate
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(160)
        self.busy_bar.hide()
        self.statusBar().addPermanentWidget(self.busy_bar)
        self.resize(1280, 860)

    def _build_welcome(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addStretch(2)
        holder = QWidget()
        holder.setFixedWidth(480)
        v = QVBoxLayout(holder)
        v.setSpacing(10)
        centre = Qt.AlignmentFlag.AlignHCenter
        icon = QLabel()
        if ICON.exists():
            icon.setPixmap(QPixmap(str(ICON)).scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        title = QLabel("AutoKaraoke")
        title.setObjectName("welcomeTitle")
        sub = QLabel("Transforme uma música sua em um vídeo de karaokê,\ncom as sílabas sincronizadas.")
        sub.setObjectName("welcomeSub")
        for lb in (icon, title, sub):
            lb.setAlignment(centre)
            v.addWidget(lb)
        v.addSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(12)
        new_btn = QPushButton("＋  Novo projeto")
        new_btn.setObjectName("bigPrimary")
        new_btn.setDefault(True)
        open_btn = QPushButton("Abrir projeto…")
        open_btn.setObjectName("bigSecondary")
        new_btn.clicked.connect(self.act_new.trigger)
        open_btn.clicked.connect(self.act_open.trigger)
        row.addStretch()
        row.addWidget(new_btn)
        row.addWidget(open_btn)
        row.addStretch()
        v.addLayout(row)
        tip = self._muted("ou arraste um arquivo de áudio para qualquer lugar desta janela")
        tip.setAlignment(centre)
        v.addWidget(tip)
        v.addSpacing(18)
        self.recent_title = QLabel("PROJETOS RECENTES")
        self.recent_title.setObjectName("panelTitle")
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recent")
        self.recent_list.itemClicked.connect(lambda it: self._open_recent(it.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(self.recent_title)
        v.addWidget(self.recent_list)
        outer.addWidget(holder, 0, centre)
        outer.addStretch(3)
        self._refresh_recent()
        return page

    # ---- recent projects, drag & drop --------------------------------------

    def _recent(self) -> list[str]:
        try:
            items = self.settings.value("recent", [], type=list) or []
        except Exception:
            items = []
        if isinstance(items, str):
            items = [items]
        return [p for p in items if Path(p).exists()]

    def _add_recent(self, path) -> None:
        items = [p for p in self._recent() if p != str(path)]
        self.settings.setValue("recent", [str(path)] + items[:7])
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        self.recent_list.clear()
        paths = self._recent()[:5]
        for p in paths:
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.recent_list.addItem(item)
        self.recent_title.setVisible(bool(paths))
        self.recent_list.setVisible(bool(paths))
        self.recent_list.setFixedHeight(min(len(paths), 5) * 38 + 12)

    def _open_recent(self, path: str) -> None:
        if self.job is not None and self.job.isRunning():
            return
        if self._maybe_save():
            self.open_project(Path(path))

    def dragEnterEvent(self, e) -> None:
        for u in e.mimeData().urls():
            f = Path(u.toLocalFile())
            if f.suffix.lower() in AUDIO_EXT or f.name.endswith(".akp.json"):
                e.acceptProposedAction()
                return

    def dropEvent(self, e) -> None:
        if self.job is not None and self.job.isRunning():
            return
        for u in e.mimeData().urls():
            f = Path(u.toLocalFile())
            if f.name.endswith(".akp.json"):
                QTimer.singleShot(0, lambda f=f: self._open_recent(str(f)))
                return
            if f.suffix.lower() in AUDIO_EXT:
                self._preset_source = str(f)
                QTimer.singleShot(0, self.new_project)
                return

    def _connect(self) -> None:
        self.btn_play.clicked.connect(self.player.toggle)
        self.player.stateChanged.connect(lambda playing: self.btn_play.setText("⏸" if playing else "▶"))
        self.speed.valueChanged.connect(self._speed_changed)
        self.speed_label.clicked.connect(lambda: self.speed.setValue(20))
        self.track.currentIndexChanged.connect(self._load_track)
        self.view.currentIndexChanged.connect(lambda: self.canvas.set_view_mode(self.view.currentData()))
        self.tap_mode.currentIndexChanged.connect(self._tap_mode_changed)
        self.canvas.seekRequested.connect(self._seek)
        self.canvas.playFromRequested.connect(self._play_from)
        self.canvas.aboutToEdit.connect(self.push_undo)
        self.canvas.edited.connect(self._after_edit)
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.canvas.hintChanged.connect(self.hint.setText)
        self.canvas.contextRequested.connect(self._syllable_menu)
        self.syl_start.valueChanged.connect(lambda v: self._edge_edited("start", v))
        self.syl_end.valueChanged.connect(lambda v: self._edge_edited("end", v))
        self.btn_set_start.clicked.connect(lambda: self._set_boundary_at_playhead(True))
        self.btn_set_end.clicked.connect(lambda: self._set_boundary_at_playhead(False))
        self.btn_play_syl.clicked.connect(self.play_syllable)
        self.btn_play_line.clicked.connect(lambda: self.play_line(loop=False))
        self.btn_loop.toggled.connect(self._loop_toggled)
        self.lyrics.lineActivated.connect(self._goto_line)
        self.lyrics.editRequested.connect(self.edit_line)

    def _restore_settings(self) -> None:
        s = self.settings
        if s.value("window/geometry") is not None:
            self.restoreGeometry(s.value("window/geometry"))
        for key, split in (("split/main", self.main_split), ("split/top", self.top_split),
                           ("split/right", self.right_split)):
            if s.value(key) is not None:
                split.restoreState(s.value(key))
        self.canvas.syl_h = int(s.value("timeline/syl_h", self.canvas.syl_h))
        self.view.setCurrentIndex(max(0, self.view.findData(s.value("timeline/view", "wave"))))
        self.latency.setValue(int(s.value("tap/latency", 60)))
        self.hint.setText(HINTS[""])

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("split/main", self.main_split.saveState())
        s.setValue("split/top", self.top_split.saveState())
        s.setValue("split/right", self.right_split.saveState())
        s.setValue("timeline/syl_h", self.canvas.syl_h)
        s.setValue("timeline/view", self.view.currentData())
        s.setValue("tap/latency", self.latency.value())

    # ---- project ----------------------------------------------------------

    def open_dialog(self) -> None:
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir projeto", str(config.PROJECTS_DIR), "Projeto AutoKaraoke (*.akp.json)"
        )
        if path:
            self.open_project(Path(path))

    def open_project(self, path: Path) -> None:
        try:
            proj = Project.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Falha ao abrir", str(e))
            return
        self.player.reset()  # another song: start from the beginning, paused
        self._set_project(proj)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.log(f"Aberto: {proj.path}")

    def _set_project(self, proj: Project | None) -> None:
        self.project = proj
        self.dirty = False
        self.stack.setCurrentIndex(1 if proj else 0)
        if proj is not None and proj.path:
            self._add_recent(proj.path)
        self.tap_mode.setCurrentIndex(0)
        self.play_range = None
        self.btn_loop.setChecked(False)
        self.analysis.clear()
        self.canvas.set_project(proj, None)
        self.preview.set_project(proj)
        self.lyrics.set_project(proj)
        self.timeline._sync_scrollbar()
        self._refresh_tracks(keep=False)
        if proj and proj.audio_vocals and proj.abspath(proj.audio_vocals).exists():
            self._analyse(str(proj.abspath(proj.audio_vocals)))  # its attacks are always shown
        self._update_title()
        self._set_enabled()
        self._update_status()
        self._update_inspector()

    def _refresh_tracks(self, keep: bool = True) -> None:
        """Fill the audio combo; the karaoke mix is offered once some line is marked as backing."""
        proj = self.project
        current = self.track.currentData() if keep else None
        self.track.blockSignals(True)
        self.track.clear()
        if proj:
            for label, rel in (("Original", proj.audio_full), ("Voz", proj.audio_vocals),
                               ("Instrumental", proj.audio_instrumental)):
                if rel and (proj.path / rel).exists():
                    self.track.addItem(label, str(proj.path / rel))
            if proj.audio_vocals and proj.audio_instrumental and any(ln.backing for ln in proj.lines):
                self.track.addItem("Karaokê (instrumental + apoio)", MIX_TRACK)
        idx = self.track.findData(current) if current is not None else -1
        self.track.setCurrentIndex(max(idx, 0))
        self.track.blockSignals(False)
        if not keep or idx < 0:
            self._load_track()

    def _analyse(self, path: str) -> None:
        """Waveform, spectrogram and attacks of an audio file, computed in the background."""
        if path in self.analysis or any(j.title == path for j in self.bg_jobs):
            self._apply_analysis()
            return
        from autokaraoke.spectrum import load_analysis

        job = Job(path, lambda log: load_analysis(path), self)
        job.succeeded.connect(lambda a, p=path: self._analysis_ready(p, a))
        job.failed.connect(lambda err: self.log(f"Falha na análise do áudio: {err}"))
        job.finished.connect(lambda j=job: self.bg_jobs.discard(j))
        self.bg_jobs.add(job)
        job.start()

    def _analysis_ready(self, path: str, a) -> None:
        if self.project is None or not path.startswith(str(self.project.path)):
            return  # finished after another project was opened
        self.analysis[path] = (a.peaks, spectrogram_image(a.spec), a.onsets)
        self._apply_analysis()

    def _current_audio(self) -> str | None:
        data = self.track.currentData()
        if data == MIX_TRACK and self.project:
            return str(self.project.path / "karaoke_mix.flac")
        return data

    def _apply_analysis(self) -> None:
        proj = self.project
        cur = self.analysis.get(self._current_audio() or "")
        voc = self.analysis.get(str(proj.abspath(proj.audio_vocals))) if proj and proj.audio_vocals else None
        onsets = (voc or cur or (None, None, None))[2]
        if cur:
            self.canvas.set_signal(cur[0], cur[1], onsets)
        else:
            self.canvas.set_signal(None, None, onsets)

    def _load_track(self) -> None:
        data = self.track.currentData()
        if data == MIX_TRACK:
            self._build_mix()
            return
        self.player.load(Path(data) if data else None)
        if data:
            self._analyse(data)
        else:
            self._apply_analysis()

    def _build_mix(self) -> None:
        """(Re)write the karaoke mix with the current backing lines, then play it."""
        if not self.project:
            return
        from autokaraoke.mix import backing_spans, karaoke_mix

        proj = copy.copy(self.project)
        proj.lines = copy.deepcopy(self.project.lines)
        self.mix_spans = backing_spans(proj)

        def done(path) -> None:
            if path is None or self.track.currentData() != MIX_TRACK:
                return
            self.analysis.pop(str(path), None)
            self.player.load(Path(path), reload=True)
            self._analyse(str(path))

        job = Job("mix", lambda log: karaoke_mix(proj), self)
        job.succeeded.connect(done)
        job.failed.connect(lambda err: self.log(f"Falha na mixagem do karaokê: {err}"))
        job.finished.connect(lambda j=job: self.bg_jobs.discard(j))
        self.bg_jobs.add(job)
        job.start()

    def save(self) -> bool:
        if not self.project:
            return False
        self.project.save()
        self.dirty = False
        self._update_title()
        self.log("Salvo")
        return True

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(
            self, "Alterações não salvas", "Salvar as alterações do projeto atual?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            self.save()
        return True

    def closeEvent(self, e) -> None:
        if self.job and self.job.isRunning():
            QMessageBox.information(self, "Ocupado", "Aguarde a tarefa atual terminar.")
            e.ignore()
            return
        if not self._maybe_save():
            e.ignore()
            return
        self._save_settings()
        for job in list(self.bg_jobs):
            job.wait()
        e.accept()

    def _update_title(self) -> None:
        name = f"{self.project.artist} - {self.project.title}" if self.project else "Nenhum projeto"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} - AutoKaraoke")

    def _set_enabled(self) -> None:
        busy = self.job is not None and self.job.isRunning()
        has = self.project is not None
        for a in (self.act_lyrics, self.act_separate, self.act_fix, self.act_align, self.act_render,
                  self.act_export, *self.line_actions):
            a.setEnabled(has and not busy)
        for a in (self.act_new, self.act_open):
            a.setEnabled(not busy)
        self.act_save.setEnabled(has)
        self.busy_bar.setVisible(busy)

    def log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)
        self.statusBar().showMessage(msg, 5000)

    # ---- undo -------------------------------------------------------------

    def _snapshot(self) -> list:
        return copy.deepcopy(self.project.lines) if self.project else []

    def push_undo(self) -> None:
        if not self.project:
            return
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def _restore(self, lines: list) -> None:
        backing = [ln.backing for ln in self.project.lines]
        self.project.lines = lines
        self._lines_changed(backing_changed=backing != [ln.backing for ln in lines])

    def undo(self) -> None:
        if self.project and self.undo_stack:
            self.redo_stack.append(self._snapshot())
            self._restore(self.undo_stack.pop())

    def redo(self) -> None:
        if self.project and self.redo_stack:
            self.undo_stack.append(self._snapshot())
            self._restore(self.redo_stack.pop())

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()
        self._update_status()

    def _after_edit(self) -> None:
        self.lyrics.refresh()
        self.preview.update()
        self._update_inspector()
        self._mark_dirty()
        if self.track.currentData() == MIX_TRACK:
            from autokaraoke.mix import backing_spans

            if backing_spans(self.project) != self.mix_spans:
                self.mix_timer.start()  # hear the new fades without reselecting the track

    def _lines_changed(self, backing_changed: bool = False) -> None:
        """After lines were added, removed, split or re-flagged."""
        self.canvas.refresh()
        self._after_edit()
        if backing_changed:
            self._refresh_tracks()
            if self.track.currentData() == MIX_TRACK:
                self.mix_timer.stop()
                self._build_mix()

    # ---- navigation -------------------------------------------------------

    def _tick(self) -> None:
        t = self.player.position()
        if self.play_range and self.player.is_playing():
            start, end, loop = self.play_range
            if t >= end:
                if loop:
                    self.player.seek(start)
                    t = start
                else:
                    self.player.pause()
                    self.play_range = None
        self.time_label.setText(fmt_time(t))
        self.canvas.set_playhead(t, follow=self.player.is_playing())
        self.preview.set_time(t)
        if self.project and self.player.is_playing():
            self.lyrics.highlight(current_line_index(self.project, t))

    def _seek(self, t: float) -> None:
        if self.play_range and not self.play_range[2]:
            self.play_range = None
        self.player.seek(t)

    def _play_from(self, t: float) -> None:
        self.player.seek(t)
        self.player.play()

    def _speed_changed(self, value: int) -> None:
        self.speed_label.setText(f"{value * 5}%")
        self.player.set_rate(value * 5 / 100)

    def _goto_line(self, row: int) -> None:
        if not self.project:
            return
        first = sum(len(ln.syllables()) for ln in self.project.lines[:row])
        line = self.project.lines[row]
        if line.syllables():
            self.canvas.select(first)
            span = line.span()
            if span is not None:
                self.player.seek(max(0.0, span[0] - 0.5))

    def _selection_changed(self, index: int) -> None:
        if index >= 0 and self.project:
            self.lyrics.highlight(self.canvas.syl_line[index])
        self._update_status()
        self._update_inspector()

    def _update_inspector(self) -> None:
        i = self.canvas.selected
        ok = self.project is not None and 0 <= i < len(self.canvas.sylls)
        for w in (self.syl_start, self.syl_end, self.btn_set_start, self.btn_set_end,
                  self.btn_play_syl, self.btn_play_line, self.btn_loop):
            w.setEnabled(ok)
        if not ok:
            self.syl_label.setText("Nenhuma sílaba selecionada")
            return
        s = self.canvas.sylls[i]
        line = self.canvas.syl_line[i]
        self.syl_label.setText(f"Sílaba “{s.text}” · linha {line + 1}")
        for spin, value in ((self.syl_start, s.start), (self.syl_end, s.end)):
            spin.blockSignals(True)
            spin.setValue(value if value is not None else 0.0)
            spin.setSpecialValueText("--" if value is None else "")
            spin.blockSignals(False)

    def _edge_edited(self, mode: str, value: float) -> None:
        i = self.canvas.selected
        if not self.project or not 0 <= i < len(self.canvas.sylls):
            return
        self.push_undo()
        self.canvas.set_edge(i, mode, value)
        self._after_edit()

    def _syllable_range(self, i: int) -> tuple[float, float] | None:
        s = self.canvas.sylls[i]
        return (s.start, s.end) if s.start is not None and s.end is not None else None

    def play_syllable(self) -> None:
        i = self.canvas.selected
        if not 0 <= i < len(self.canvas.sylls) or not (r := self._syllable_range(i)):
            return
        self.btn_loop.setChecked(False)
        self.play_range = (max(0.0, r[0] - 0.3), r[1] + 0.15, False)
        self._play_from(self.play_range[0])

    def play_line(self, loop: bool) -> None:
        i = self.canvas.selected
        if not self.project or not 0 <= i < len(self.canvas.sylls):
            return
        span = self.project.lines[self.canvas.syl_line[i]].span()
        if span is None:
            return
        self.play_range = (max(0.0, span[0] - 0.3), span[1] + 0.2, loop)
        self._play_from(self.play_range[0])

    def _loop_toggled(self, on: bool) -> None:
        if on:
            self.play_line(loop=True)
            if self.play_range is None:
                self.btn_loop.setChecked(False)
        elif self.play_range and self.play_range[2]:
            self.play_range = None
            self.player.pause()

    def _update_status(self) -> None:
        if not self.project:
            self.lines_count.setText("")
            return
        flagged = sum(1 for s in self.canvas.sylls if s.confidence < 0.5)
        n_lines = len(self.project.lines)
        self.lines_count.setText(f"{n_lines} linhas · {flagged} para revisar" if flagged else f"{n_lines} linhas")
        msg = f"{len(self.project.lines)} linhas · {len(self.canvas.sylls)} sílabas · {flagged} para revisar"
        if self.tap_mode.currentData() and 0 <= self.tap_index < len(self.canvas.sylls):
            msg += f" · TOQUE a seguir: “{self.canvas.sylls[self.tap_index].text}” (Espaço)"
        self.statusBar().showMessage(msg)

    # ---- keyboard ---------------------------------------------------------

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if QApplication.activeModalWidget() is not None or not self.isActiveWindow():
            return False
        if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit)) and \
                QApplication.focusWidget() is not self.log_view:
            return False
        key = e.key()
        press = e.type() == QEvent.Type.KeyPress
        mods = e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        arrows = (Qt.Key.Key_Left, Qt.Key.Key_Right)
        if e.isAutoRepeat() and not (ctrl and key in arrows):
            return key == Qt.Key.Key_Space
        if key == Qt.Key.Key_Space:
            if self.tap_mode.currentData():
                self._tap(press)
            elif press:
                self.player.toggle()
            return True
        if not press or not self.project:
            return False
        if key == Qt.Key.Key_Escape:
            if self.tap_mode.currentData():
                self.tap_mode.setCurrentIndex(0)
                return True
            if self.play_range:
                self.btn_loop.setChecked(False)
                self.play_range = None
                return True
            return False
        if isinstance(QApplication.focusWidget(), LyricsPanel):
            return False  # arrows, Enter, Delete... belong to the list there
        n = len(self.canvas.sylls)
        sel = self.canvas.selected
        if key in arrows and ctrl:
            if 0 <= sel < n:
                step = NUDGE * (5 if mods & Qt.KeyboardModifier.ShiftModifier else 1)
                self.canvas.nudge(sel, -step if key == Qt.Key.Key_Left else step)
            return True
        if key in arrows:
            if n:
                self.canvas.select(min(max(sel + (-1 if key == Qt.Key.Key_Left else 1), 0), n - 1))
            return True
        if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight) and sel >= 0:
            self._set_boundary_at_playhead(start=key == Qt.Key.Key_BracketLeft)
            return True
        if key == Qt.Key.Key_P and not ctrl:
            self.play_syllable()
            return True
        if key == Qt.Key.Key_L and not ctrl:
            self.btn_loop.toggle()
            return True
        return False

    def _set_boundary_at_playhead(self, start: bool) -> None:
        """'[' / ']' set the selected syllable's start / end to the playhead."""
        i = self.canvas.selected
        if not 0 <= i < len(self.canvas.sylls):
            return
        self.push_undo()
        self.canvas.set_edge(i, "start" if start else "end", self.player.position())
        self._after_edit()

    def _fix_lines(self) -> None:
        for line in self.project.lines:
            if span := line.span():
                line.start, line.end = span

    def _locate(self, i: int) -> tuple[int, int, int]:
        """Flat syllable index -> (line, word, syllable) indices."""
        li = self.canvas.syl_line[i]
        k = i - self.canvas.syl_line.index(li)
        for wi, word in enumerate(self.project.lines[li].words):
            if k < len(word.syllables):
                return li, wi, k
            k -= len(word.syllables)
        raise IndexError(i)

    def _syllable_menu(self, i: int, pos) -> None:
        li, wi, si = self._locate(i)
        word = self.project.lines[li].words[wi]
        s = self.canvas.sylls[i]
        menu = QMenu(self)
        menu.addAction("Início no cursor  [", lambda: self._set_boundary_at_playhead(True))
        menu.addAction("Fim no cursor  ]", lambda: self._set_boundary_at_playhead(False))
        menu.addAction("Tocar sílaba  P", self.play_syllable)
        menu.addSeparator()
        split = menu.addAction("Dividir sílaba…", lambda: self.split_syllable(i))
        split.setEnabled(len(s.text) > 1)
        merge = menu.addAction("Juntar com a próxima sílaba", lambda: self.merge_syllable(i))
        merge.setEnabled(si + 1 < len(word.syllables))
        menu.addSeparator()
        menu.addAction("Editar linha…", lambda: self.edit_line(li))
        backing = menu.addAction("Vozes de apoio", lambda: self._set_backing([li], not self.project.lines[li].backing))
        backing.setCheckable(True)
        backing.setChecked(self.project.lines[li].backing)
        menu.exec(pos)

    def split_syllable(self, i: int) -> None:
        li, wi, si = self._locate(i)
        word = self.project.lines[li].words[wi]
        text = word.syllables[si].text
        mid = (len(text) + 1) // 2
        notation, ok = QInputDialog.getText(
            self, "Dividir sílaba", "Coloque um '|' onde a sílaba deve ser dividida:",
            QLineEdit.EchoMode.Normal, f"{text[:mid]}|{text[mid:]}")
        if not ok or notation.count("|") != 1 or notation.replace("|", "") != text:
            return
        pos = notation.index("|")
        if not 0 < pos < len(text):
            return
        self.push_undo()
        text_edit.split_syllable(word, si, pos)
        self._lines_changed()
        self.canvas.select(i)

    def merge_syllable(self, i: int) -> None:
        li, wi, si = self._locate(i)
        word = self.project.lines[li].words[wi]
        if si + 1 >= len(word.syllables):
            return
        self.push_undo()
        text_edit.merge_syllable_with_next(word, si)
        self._lines_changed()
        self.canvas.select(i)

    # ---- tap sync ---------------------------------------------------------

    def _tap_mode_changed(self) -> None:
        if not self.tap_mode.currentData():
            if self.tap_index >= 0:
                self.log("Sincronia por toques parada")
            self.tap_index = -1
            self.tap_prev = -1
            self.tap_pressed = False
            self._update_status()
            return
        if not self.project or not self.canvas.sylls:
            self.tap_mode.setCurrentIndex(0)
            return
        self.tap_index = max(self.canvas.selected, 0)
        self.tap_prev = -1
        self.tap_pressed = False
        self.play_range = None
        self.btn_loop.setChecked(False)
        self.push_undo()
        s = self.canvas.sylls[self.tap_index]
        if not self.player.is_playing():
            if s.start is not None:
                self.player.seek(max(0.0, s.start - 2.0))
            self.player.play()
        self.canvas.setFocus()
        self.log("Sincronia por toques: aperte Espaço em cada sílaba, Esc para parar")
        self._update_status()

    def _tap(self, press: bool) -> None:
        sylls = self.canvas.sylls
        if not (0 <= self.tap_index < len(sylls)) and press:
            self.tap_mode.setCurrentIndex(0)
            return
        t = max(0.0, self.player.position() - self.latency.value() / 1000)
        mode = self.tap_mode.currentData()
        if mode == "hold":
            if press:
                s = sylls[self.tap_index]
                # Keep the old end while the key is held so the block stays visible.
                s.start = t
                s.end = max(s.end or 0.0, t + MIN_DUR)
                s.confidence = 1.0
                self.tap_pressed = True
            elif self.tap_pressed:
                s = sylls[self.tap_index]
                s.end = max(t, s.start + MIN_DUR)
                self.tap_pressed = False
                self._tap_advance()
        elif press:  # tap mode
            s = sylls[self.tap_index]
            if 0 <= self.tap_prev < len(sylls):
                prev = sylls[self.tap_prev]
                same_line = self.canvas.syl_line[self.tap_prev] == self.canvas.syl_line[self.tap_index]
                old = max((prev.end or prev.start) - prev.start, 0.2)
                prev.end = t if same_line else min(prev.start + old, t)
                prev.end = max(prev.end, prev.start + MIN_DUR)
            old_dur = (s.end - s.start) if s.end is not None and s.start is not None else 0.3
            s.start, s.end, s.confidence = t, t + max(old_dur, MIN_DUR), 1.0
            self.tap_prev = self.tap_index
            self._tap_advance()
        self._fix_lines()
        self.canvas.update()

    def _tap_advance(self) -> None:
        self.tap_index += 1
        self.dirty = True
        self._update_title()
        if self.tap_index < len(self.canvas.sylls):
            self.canvas.select(self.tap_index, scroll=False)
        else:
            self.log("Sincronia por toques: chegou à última sílaba")
            self.tap_mode.setCurrentIndex(0)
        self.lyrics.refresh()
        self._update_status()

    # ---- line editing -----------------------------------------------------

    def edit_line(self, row: int) -> None:
        if not self.project or not 0 <= row < len(self.project.lines):
            return
        line = self.project.lines[row]
        dlg = LineEditDialog("Editar linha", to_notation(line), line.note, self, line.auto_split,
                             self.project.language)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.text()
        if text == to_notation(line) and dlg.auto_split() == line.auto_split:
            if line.note:
                self.push_undo()
                line.note = ""  # confirmed as is: dismiss the review hint
                self._after_edit()
            return
        self.push_undo()
        if not text:
            del self.project.lines[row]
        else:
            line.auto_split = dlg.auto_split()
            new = text_edit.split_into_lines(line, text, self.project.language)
            for ln in new:
                ln.note = ""
            self.project.lines[row : row + 1] = new
        self._lines_changed(backing_changed=line.backing)
        self.lyrics.setCurrentRow(min(row, len(self.project.lines) - 1))

    def insert_line(self) -> None:
        if not self.project:
            return
        rows = self.lyrics.selected_rows()
        row = rows[-1] if rows else len(self.project.lines) - 1
        dlg = LineEditDialog("Inserir linha abaixo", "", parent=self, lang=self.project.language)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.text():
            return
        lines = self.project.lines
        prev = lines[row] if 0 <= row < len(lines) else None
        nxt = lines[row + 1] if row + 1 < len(lines) else None
        # Time all the text as one line in the gap, then split it: several lines share the gap.
        joined = text_edit.new_line(" ".join(dlg.text().split()), self.project.language, prev, nxt,
                                    dlg.auto_split())
        new = text_edit.split_into_lines(joined, dlg.text(), self.project.language)
        self.push_undo()
        lines[row + 1 : row + 1] = new
        self._lines_changed()
        self.lyrics.setCurrentRow(row + 1)
        if not new[0].span():
            self.log("A nova linha ainda não tem tempos: selecione-a e use a sincronia por toques, [ / ] ou Sincronizar")

    def delete_lines(self) -> None:
        rows = self.lyrics.selected_rows()
        if not self.project or not rows:
            return
        self.push_undo()
        backing = any(self.project.lines[r].backing for r in rows)
        for r in reversed(rows):
            del self.project.lines[r]
        self.canvas.selected = -1
        self._lines_changed(backing_changed=backing)
        self.lyrics.setCurrentRow(min(rows[0], len(self.project.lines) - 1))

    def merge_lines(self) -> None:
        rows = self.lyrics.selected_rows()
        if not self.project or not rows:
            return
        first, last = rows[0], rows[-1] if len(rows) > 1 else rows[0] + 1
        if last >= len(self.project.lines):
            return
        self.push_undo()
        merged = self.project.lines[first]
        for ln in self.project.lines[first + 1 : last + 1]:
            merged = text_edit.merge_lines(merged, ln)
        self.project.lines[first : last + 1] = [merged]
        self._lines_changed(backing_changed=True)
        self.lyrics.setCurrentRow(first)

    def toggle_backing(self) -> None:
        rows = self.lyrics.selected_rows()
        if self.project and rows:
            self._set_backing(rows, not all(self.project.lines[r].backing for r in rows))

    def _set_backing(self, rows: list[int], on: bool) -> None:
        self.push_undo()
        for r in rows:
            self.project.lines[r].backing = on
        self._lines_changed(backing_changed=True)
        if on:
            self.log("Linhas de apoio ficam no áudio do karaokê: escolha “Karaokê (instrumental + apoio)” em Áudio para ouvir")

    # ---- pipeline jobs ----------------------------------------------------

    def _run(self, title: str, fn, on_success=None) -> None:
        self.job = Job(title, fn, self)
        self.job.message.connect(self.log)
        self.job.failed.connect(lambda err: QMessageBox.critical(self, f"Falha — {title}", err))
        if on_success:
            self.job.succeeded.connect(on_success)
        self.job.finished.connect(self._job_finished)
        self.log(f"{title}…")
        self.job.start()
        self._set_enabled()

    def _job_finished(self) -> None:
        self.job = None
        self._set_enabled()

    def _reload(self, _result=None) -> None:
        if self.project and self.project.path:
            self.push_undo()
            undo = self.undo_stack[:]
            pos = self.player.position()
            self._set_project(Project.load(self.project.path))
            self.undo_stack = undo
            # The stems may have been rewritten (Separate): re-read the file, keeping
            # position and play state.
            data = self.track.currentData()
            if data and data != MIX_TRACK:
                self.player.load(Path(data), reload=True)
            self.player.seek(pos)

    def _prepare_job(self) -> Path | None:
        if not self.project or not self.project.path:
            return None
        if self.dirty:
            self.save()
        return self.project.path

    def new_project(self) -> None:
        if not self._maybe_save():
            return
        dlg = NewProjectDialog(self, preset=self._preset_source)
        self._preset_source = None
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.source.text().strip():
            return
        source = dlg.source.text().strip()
        if steps.is_url(source) and not config.download_enabled():
            QMessageBox.warning(self, "Download desativado",
                                "O download está desativado nesta versão. Escolha um arquivo de áudio que você tenha.")
            return
        out = Path(dlg.out.text() or config.PROJECTS_DIR)
        artist, title, lang = dlg.artist.text() or None, dlg.title.text() or None, dlg.lang.text() or None

        def work(log):
            proj = steps.create_project(source, out, title, artist, None, lang, log=log)
            try:
                steps.fetch_lyrics(proj, log=log)
            except steps.LyricsNotFound as e:
                log(f"{e}. Use 'Letra' para carregar um arquivo ou transcrever da voz.")
            return proj.path

        self._run("Criando projeto", work, lambda path: self.open_project(path))

    def fetch_lyrics(self) -> None:
        path = self._prepare_job()
        if path is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Letra")
        box.setText("De onde deve vir a letra?\n\nIsso substitui a letra e os tempos atuais.")
        b_lrclib = box.addButton("LRCLIB", QMessageBox.ButtonRole.AcceptRole)
        b_file = box.addButton("Arquivo (.lrc / .txt)…", QMessageBox.ButtonRole.AcceptRole)
        b_audio = box.addButton("Transcrever da voz", QMessageBox.ButtonRole.AcceptRole)
        b_audio.setToolTip("Reconhecimento de fala da faixa de voz (melhor depois de Separar); confira o resultado linha por linha")
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked == b_audio:
            if not self._ensure_ai(self.fetch_lyrics):
                return
            self._run("Letra a partir do áudio",
                      lambda log: steps.lyrics_from_audio(Project.load(path), log=log), self._reload)
            return
        if clicked not in (b_lrclib, b_file):
            return
        lrc_file = None
        if clicked == b_file:
            f, _ = QFileDialog.getOpenFileName(self, "Arquivo de letra", "", "Letra (*.lrc *.txt)")
            if not f:
                return
            lrc_file = Path(f)
        self._run("Letra", lambda log: steps.fetch_lyrics(Project.load(path), lrc_file, log=log),
                  self._reload)

    def fix_lyrics(self) -> None:
        if not config.experimental_llm():
            return
        if not config.openrouter_key():
            QMessageBox.information(self, "Corrigir letra",
                                    "Isto precisa de uma chave de API do OpenRouter (uma música custa uma fração de centavo).")
            if not self.show_settings() or not config.openrouter_key():
                return
        if not self._ensure_ai(self.fix_lyrics):
            return
        path = self._prepare_job()
        if path is None or not self.project.lines:
            return
        self._run("Corrigir letra", lambda log: steps.reconcile(Project.load(path), log=log),
                  self._review_proposal)

    def _review_proposal(self, proposal) -> None:
        if not proposal.changes:
            QMessageBox.information(self, "Corrigir letra", "A letra já corresponde à gravação.")
            return
        if ProposalDialog(proposal, self).exec() != QDialog.DialogCode.Accepted:
            return
        self.push_undo()
        steps.apply_proposal(self.project, proposal)
        self.dirty = False
        self._set_project_lines()
        self.log("Letra atualizada: use Sincronizar para marcar o tempo das linhas alteradas")

    def _set_project_lines(self) -> None:
        self.canvas.refresh()
        self.lyrics.refresh()
        self.preview.update()
        self._update_title()
        self._update_status()
        self._refresh_tracks()

    def show_settings(self) -> bool:
        ok = SettingsDialog(self).exec() == QDialog.DialogCode.Accepted
        self.act_fix.setVisible(config.experimental_llm())
        return ok

    def _ensure_ai(self, then) -> bool:
        """True if the AI components are installed; otherwise offer to download them and
        run ``then`` once they are ready."""
        st = components.state()
        if st == "ok" or (self.job and self.job.isRunning()):
            return st == "ok"
        if not components.packaged():
            QMessageBox.information(
                self, "Componentes de IA ausentes",
                "A separação de voz e a sincronização precisam das dependências opcionais:\n\nuv sync --extra gui --extra separation --extra align --extra gpu\n(--extra cpu no lugar de gpu, se não houver placa NVIDIA)")
            return False
        if st == "outdated":
            text = ("Esta versão do AutoKaraoke usa componentes de IA atualizados. Baixar a atualização agora?\n(Só o que mudou é baixado.)")
        else:
            size = ("3-4 GB, PyTorch para a sua placa NVIDIA" if components.torch_variant() == "gpu"
                    else "menos de 1 GB, PyTorch para a CPU: nenhuma placa NVIDIA foi encontrada, então as etapas de IA serão lentas")
            text = ("A separação de voz e a sincronização automática precisam dos componentes de IA, "
                    f"baixados uma única vez ({size}).\n\n"
                    "Os modelos em si (~5 GB a mais) são baixados na primeira vez que cada etapa roda.\n\n"
                    "Baixar os componentes agora?")
        if QMessageBox.question(self, "Componentes de IA", text) != QMessageBox.StandardButton.Yes:
            return st == "outdated"  # the previous components still work

        def done(_result) -> None:
            self.log("Componentes de IA prontos")
            if then is not None:
                QTimer.singleShot(0, then)

        self._run("Baixando componentes de IA", components.install, done)
        return False

    def separate(self) -> None:
        if not self._ensure_ai(self.separate):
            return
        path = self._prepare_job()
        if path is not None:
            self._run("Separação de voz", lambda log: steps.separate(Project.load(path), log=log),
                      self._reload)

    def align(self) -> None:
        path = self._prepare_job()
        if path is None:
            return
        if any(s.confidence >= 0.95 for s in self.canvas.sylls):
            r = QMessageBox.question(self, "Sincronizar",
                                     "A sincronização substitui todos os tempos, inclusive os ajustes manuais. Continuar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        engine = self.engine.currentData()
        if engine != "naive" and not self._ensure_ai(self.align):
            return
        self._run("Sincronizar", lambda log: steps.align(Project.load(path), engine, log=log), self._reload)

    def render(self) -> None:
        if not self.project or not self.project.path:
            return
        from autokaraoke.export.ass import project_style
        from autokaraoke.gui.render_dialog import RenderDialog

        dlg = RenderDialog(self.project, project_style(self.project),
                           self.project.path / f"{self.project.slug}.mkv", self)
        result = dlg.exec()
        if result == QDialog.DialogCode.Rejected:
            return
        style = dlg.style()
        if style.to_dict() != project_style(self.project).to_dict():
            self.project.render = style.to_dict()
            self._mark_dirty()
        self.preview.set_style(style)
        if result != QDialog.DialogCode.Accepted:  # "Save style" only
            return
        out = dlg.output_path()
        path = self._prepare_job()
        if path is None or not str(out):
            return
        self._run("Gerando vídeo",
                  lambda log: steps.render(Project.load(path), out, log=log, style=style),
                  lambda result: self.log(f"Vídeo pronto: {result}"))

    def export(self) -> None:
        if not self.project:
            return
        from autokaraoke.export.ass import write_ass
        from autokaraoke.export.lrc import write_lrc

        out, filt = QFileDialog.getSaveFileName(
            self, "Exportar letra sincronizada", str(self.project.path / f"{self.project.slug}.ass"),
            "Legenda ASS (*.ass);;LRC aprimorado (*.lrc)",
        )
        if not out:
            return
        (write_lrc if out.endswith(".lrc") else write_ass)(self.project, Path(out))
        self.log(f"Letra exportada para {out}")

    def show_help(self) -> None:
        HelpDialog(self).exec()
