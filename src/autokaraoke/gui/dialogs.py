"""Secondary dialogs: lyric-change review and settings."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from autokaraoke import config
from autokaraoke.gui.lyrics_panel import fmt_time
from autokaraoke.text.reconcile import Proposal

KIND_LABEL = {"edit": "Alterar", "add": "Adicionar", "remove": "Remover", "doubt": "Dúvida"}
KIND_COLOR = {
    "edit": QColor(220, 170, 40),
    "add": QColor(70, 170, 90),
    "remove": QColor(200, 70, 70),
    "doubt": QColor(70, 140, 210),
}


class ProposalDialog(QDialog):
    """Lists the suggested lyric changes with a checkbox each."""

    def __init__(self, proposal: Proposal, parent=None):
        super().__init__(parent)
        self.proposal = proposal
        self.setWindowTitle("Alterações sugeridas na letra")
        v = QVBoxLayout(self)
        info = QLabel(
            "A letra foi comparada com o que é cantado na gravação. Desmarque o que você não quiser.\nDúvidas são linhas em que a transcrição ouviu outra coisa: marque para usar o texto da transcrição ou deixe desmarcada para manter a linha (ela continua marcada para revisão)."
        )
        info.setWordWrap(True)
        v.addWidget(info)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Tempo", "Letra"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        for c in proposal.changes:
            if c.kind == "edit":
                text = f"{c.old}\n→ {c.new}"
            elif c.kind == "doubt":
                text = f"{c.old}\n   ouvido: {c.new}"
            else:
                text = c.new if c.kind == "add" else c.old
            it = QTreeWidgetItem(["  " + KIND_LABEL[c.kind], fmt_time(c.start), text])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if c.accepted else Qt.CheckState.Unchecked)
            it.setForeground(0, QBrush(KIND_COLOR[c.kind]))
            it.setData(0, Qt.ItemDataRole.UserRole, c)
            self.tree.addTopLevelItem(it)
        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)
        v.addWidget(self.tree, 1)

        if proposal.notes:
            notes = QLabel("\n".join(f"• {n}" for n in proposal.notes))
            notes.setWordWrap(True)
            v.addWidget(notes)
        foot = []
        if proposal.model:
            foot.append(proposal.model)
        if proposal.cost is not None:
            foot.append(f"custo US${proposal.cost:.4f}")
        foot.append(f"{len(proposal.result())} linhas após as alterações; use Sincronizar depois")
        v.addWidget(QLabel(" · ".join(foot)))

        row = QHBoxLayout()
        for label, state in (("Marcar tudo", True), ("Desmarcar tudo", False)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, s=state: self._check_all(s))
            row.addWidget(b)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        v.addLayout(row)
        self.resize(820, 560)

    def _check_all(self, state: bool) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(
                0, Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def accept(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.data(0, Qt.ItemDataRole.UserRole).accepted = it.checkState(0) == Qt.CheckState.Checked
        super().accept()


class LineEditDialog(QDialog):
    """Edit one lyric line in syllable notation; each extra text line becomes a new lyric line."""

    def __init__(self, title: str, text: str, note: str = "", parent=None, auto: bool = True,
                 lang: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.lang = lang
        v = QVBoxLayout(self)
        info = QLabel(
            "Palavras separadas por espaços, sílabas por '|' (ex.: <tt>co|ra|ção mi|nha</tt>). Sem nenhum '|', as palavras são divididas automaticamente, se a caixa abaixo estiver marcada.<br>Aperte Enter para criar uma nova linha e <b>dividir</b> a linha em duas ou mais. Os tempos são mantidos se o número de sílabas não mudar.<br>Ctrl+Enter para aplicar."
        )
        info.setWordWrap(True)
        v.addWidget(info)
        if note:
            warn = QLabel(f"⚠ {note}")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #f5a524")
            v.addWidget(warn)
        self.edit = QPlainTextEdit(text)
        f = self.edit.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        self.edit.setFont(f)
        self.edit.selectAll()
        v.addWidget(self.edit, 1)
        row = QHBoxLayout()
        self.auto = QCheckBox("Dividir as palavras em sílabas automaticamente")
        self.auto.setChecked(auto)
        self.auto.setToolTip("Desmarque para linhas que não devem ser divididas, ex.: “(coro)”: cada palavra vira um bloco. Fica lembrado para esta linha.")
        self.auto.toggled.connect(self._resplit)
        again = QPushButton("Dividir de novo")
        again.setToolTip("Refaz a divisão em sílabas do texto acima (palavras inteiras se a caixa estiver desmarcada). Os seus '|' são substituídos.")
        again.clicked.connect(self._resplit)
        row.addWidget(self.auto)
        row.addStretch(1)
        row.addWidget(again)
        v.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.accept)
        v.addWidget(buttons)
        self.resize(640, 220)

    def text(self) -> str:
        return self.edit.toPlainText().strip()

    def auto_split(self) -> bool:
        return self.auto.isChecked()

    def _resplit(self) -> None:
        from autokaraoke.text.edit import resplit

        self.edit.setPlainText(resplit(self.text(), self.lang, self.auto.isChecked()))


HELP_SECTIONS = (
    ("Ajustando uma sílaba à mão", None, (
        "Clique nela na linha do tempo, ou vá até ela com ← / →.",
        "<b>P</b> toca a sílaba, <b>L</b> repete a linha dela. Diminua a <i>Velocidade</i> se precisar.",
        "Arraste o bloco ou as bordas dele, aperte <b>[</b> / <b>]</b> na hora certa enquanto toca, "
        "ou digite os tempos em <i>Início</i> / <i>Fim</i>. <b>Ctrl+← / →</b> move 10 ms "
        "(com Shift: 50 ms).",
        "A exibição <i>Espectrograma</i> mostra as consoantes como listras verticais brilhantes. Inícios e "
        "bordas arrastados grudam nos ataques de voz detectados (marcas ciano); segure <b>Ctrl</b> ao "
        "arrastar para posicioná-los livremente.",
    )),
    ("Teclas", (
        ("Espaço", "Tocar / pausar; é a tecla de toque quando a sincronia por toques está ligada"),
        ("Esc", "Parar a sincronia por toques ou a repetição"),
        ("← / →", "Selecionar a sílaba anterior / seguinte"),
        ("[ / ]", "Definir o início / fim da sílaba selecionada na posição do cursor"),
        ("P / L", "Tocar a sílaba / repetir a linha"),
        ("Ctrl+← / →", "Mover a sílaba 10 ms (com Shift: 50 ms)"),
        ("Ctrl+Z / Ctrl+Shift+Z", "Desfazer / refazer"),
        ("Ctrl+S", "Salvar"),
        ("Ctrl+E", "Exportar a letra sincronizada (ASS / LRC)"),
        ("Ctrl+R", "Gerar o vídeo"),
    ), None),
    ("Lista de letras (seleção múltipla com Ctrl / Shift)", (
        ("Enter / duplo clique", "Editar a linha; digitar uma nova linha divide a linha"),
        ("Insert", "Adicionar uma linha abaixo"),
        ("Delete", "Excluir as linhas selecionadas"),
        ("Ctrl+J", "Juntar as linhas selecionadas, ou a linha com a seguinte"),
        ("B", "Vozes de apoio liga / desliga (linhas azuis, mantidas no áudio do karaokê)"),
    ), None),
    ("Mouse na linha do tempo", (
        ("Arrastar um bloco", "Move a sílaba; o início gruda nas marcas ciano e as vizinhas encostadas "
                              "acompanham"),
        ("Arrastar a borda de um bloco", "Redimensiona, grudando nas marcas ciano; Alt solta da vizinha"),
        ("Ctrl ao arrastar", "Sem grudar"),
        ("Arrastar o divisor da faixa", "Ajusta a altura da faixa de sílabas"),
        ("Clicar na área vazia", "Ir para aquele ponto"),
        ("Duplo clique em um bloco", "Tocar a partir de um pouco antes dele"),
        ("Botão direito em um bloco", "Dividir / juntar sílabas, definir tempos, vozes de apoio"),
        ("Roda / Shift+roda", "Rolar"),
        ("Ctrl+roda", "Zoom"),
    ), None),
    ("Cores", (
        ("Verde", "Tempo confiável"),
        ("Amarelo / vermelho", "A conferir"),
        ("Azul", "Editado por você"),
    ), None),
)


class HelpDialog(QDialog):
    """Keyboard shortcuts and how-to, in a resizable window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atalhos de teclado")
        parts = ["<style>td { padding: 2px 14px 2px 0; vertical-align: top; } "
                 "h3 { margin: 14px 0 4px 0; } kbd, .k { font-weight: bold; white-space: nowrap; }</style>"]
        for title, rows, steps in HELP_SECTIONS:
            parts.append(f"<h3>{title}</h3>")
            if steps:
                parts.append("<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>")
            if rows:
                parts.append("<table>" + "".join(
                    f"<tr><td class='k'>{k}</td><td>{d}</td></tr>" for k, d in rows) + "</table>")
        text = QTextBrowser()
        text.setHtml("".join(parts))
        text.setOpenExternalLinks(True)
        v = QVBoxLayout(self)
        v.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.resize(760, 680)


def save_settings(values: dict[str, str]) -> None:
    """Store settings in the user config .env (keeps unrelated keys) and apply them now."""
    path = config.CONFIG_DIR / ".env"
    lines: list[str] = []
    if path.exists():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.split("=", 1)[0].strip() not in values]
    for k, v in values.items():
        if v:
            lines.append(f"{k}={v}")
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        form = QFormLayout(self)
        self.experimental = QCheckBox("Ativar recursos experimentais com LLM (Corrigir letra)")
        self.experimental.setChecked(config.experimental_llm())
        self.key = QLineEdit(config.openrouter_key() or "")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("sk-or-…  (opcional, em openrouter.ai/keys)")
        self.model = QLineEdit(config.OPENROUTER_MODEL)
        form.addRow(self.experimental)
        form.addRow(QLabel(
            "Experimental: um LLM compara a letra com uma transcrição da voz ('Corrigir letra')\ne limpa letras transcritas do áudio. Os resultados variam: confira cada alteração.\nPrecisa de uma chave do OpenRouter; uma música custa uma fração de centavo.\nAs configurações ficam salvas em " + str(config.CONFIG_DIR / ".env")
        ))
        form.addRow("Chave do OpenRouter", self.key)
        form.addRow("Modelo LLM", self.model)
        self.experimental.toggled.connect(self._toggle_llm)
        self._toggle_llm(self.experimental.isChecked())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(560, 0)

    def _toggle_llm(self, on: bool) -> None:
        self.key.setEnabled(on)
        self.model.setEnabled(on)

    def accept(self) -> None:
        key = self.key.text().strip()
        model = self.model.text().strip() or "deepseek/deepseek-v4.1-flash"
        save_settings({"OPENROUTER_API_KEY": key, "AUTOKARAOKE_LLM_MODEL": model,
                       "AUTOKARAOKE_EXPERIMENTAL_LLM": "1" if self.experimental.isChecked() else ""})
        config.OPENROUTER_MODEL = model
        super().accept()
