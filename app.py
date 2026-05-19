from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSizeGrip,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_DIR = Path.home() / ".techsticky"
NOTES_FILE = APP_DIR / "marktext_clean_note.json"

DEFAULT_NOTE = """
"""

COMMAND_STARTERS = (
    "subfinder", "assetfinder", "amass", "httpx", "nmap", "ffuf",
    "gobuster", "feroxbuster", "katana", "gau", "waybackurls",
    "curl", "wget", "python", "python3", "pip", "pip3", "git",
    "docker", "kubectl", "sqlmap", "nikto", "whatweb", "dnsx",
    "naabu", "nuclei", "dalfox", "trufflehog", "jwt-tool", "cat",
    "grep", "sort", "uniq", "tee", "qsreplace", "subjack",
)


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self.heading_format = QTextCharFormat()
        self.heading_format.setForeground(QColor("#38bdf8"))
        self.heading_format.setFontWeight(QFont.Bold)

        self.fence_format = QTextCharFormat()
        self.fence_format.setForeground(QColor("#64748b"))

        self.command_format = QTextCharFormat()
        self.command_format.setForeground(QColor("#e879f9"))
        self.command_format.setFontFamily("JetBrains Mono")

        self.quote_format = QTextCharFormat()
        self.quote_format.setForeground(QColor("#93c5fd"))

    def highlightBlock(self, text: str) -> None:
        stripped = text.strip()

        if stripped.startswith("#"):
            self.setFormat(0, len(text), self.heading_format)
        elif stripped.startswith("```"):
            self.setFormat(0, len(text), self.fence_format)
        elif stripped.startswith(">"):
            self.setFormat(0, len(text), self.quote_format)
        elif looks_like_command(stripped):
            self.setFormat(0, len(text), self.command_format)


class LineNumberArea(QWidget):
    def __init__(self, editor: "SourceEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class SourceEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()

        self.line_number_area = LineNumberArea(self)

        font = QFont("JetBrains Mono")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        self.setFont(font)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 24 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _=0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0,
                rect.y(),
                self.line_number_area.width(),
                rect.height(),
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

        content_rect = self.contentsRect()
        self.line_number_area.setGeometry(
            content_rect.left(),
            content_rect.top(),
            self.line_number_area_width(),
            content_rect.height(),
        )

    def paint_line_numbers(self, event) -> None:
        from PySide6.QtGui import QPainter

        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#0b1120"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#475569"))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 10,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(block_number + 1),
                )

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#101827"))
        selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


def looks_like_command(line: str) -> bool:
    if not line:
        return False

    if line.startswith(("#", "- ", "* ", ">", "|", "```")):
        return False

    lowered = line.lower()

    if any(lowered == cmd or lowered.startswith(cmd + " ") for cmd in COMMAND_STARTERS):
        return True

    command_symbols = (" -", " --", " | ", " > ", " >> ", " && ")
    return any(symbol in line for symbol in command_symbols) and len(line.split()) >= 2


def auto_codeblock_markdown(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    command_buffer: list[str] = []
    in_fence = False

    def flush_commands() -> None:
        nonlocal command_buffer

        if not command_buffer:
            return

        if output and output[-1].strip():
            output.append("")

        output.append("```bash")
        output.extend(command_buffer)
        output.append("```")
        command_buffer = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_commands()
            in_fence = not in_fence
            output.append(line)
            continue

        if in_fence:
            output.append(line)
            continue

        if looks_like_command(stripped):
            command_buffer.append(stripped)
            continue

        flush_commands()
        output.append(line)

    flush_commands()

    return re.sub(r"\n{4,}", "\n\n\n", "\n".join(output).strip() + "\n")


class MarkTextSticky(QMainWindow):
    def __init__(self):
        super().__init__()

        self.drag_position = QPoint()
        self.mode = "preview"

        self.setWindowTitle("TechSticky")
        self.resize(1120, 760)
        self.setMinimumSize(760, 480)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)

        self.root = QWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)

        self.root_layout = QVBoxLayout(self.root)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.create_top_bar()
        self.create_content()
        self.create_footer()
        self.apply_styles()

        self.highlighter = MarkdownHighlighter(self.editor.document())

        self.save_timer = QTimer()
        self.save_timer.setInterval(450)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_note)

        self.editor.textChanged.connect(self.on_text_changed)

        self.load_note()
        self.show_preview_mode()

    def create_top_bar(self) -> None:
        self.top_bar = QWidget()
        self.top_bar.setObjectName("topBar")
        self.top_bar.setFixedHeight(56)

        layout = QHBoxLayout(self.top_bar)
        layout.setContentsMargins(20, 0, 14, 0)
        layout.setSpacing(8)

        self.logo = QLabel("T")
        self.logo.setObjectName("logo")

        title_box = QVBoxLayout()
        title_box.setContentsMargins(8, 0, 0, 0)
        title_box.setSpacing(0)

        self.title = QLabel("TechSticky")
        self.title.setObjectName("title")

        self.subtitle = QLabel("Markdown notes")
        self.subtitle.setObjectName("subtitle")

        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)

        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.show_preview_mode)

        self.source_button = QPushButton("Source")
        self.source_button.clicked.connect(self.show_source_mode)

        self.format_button = QPushButton("Format")
        self.format_button.clicked.connect(self.format_note)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_markdown_file)

        self.load_button = QPushButton("Load")
        self.load_button.clicked.connect(self.load_markdown_file)

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.clicked.connect(self.close)

        layout.addWidget(self.logo)
        layout.addLayout(title_box)
        layout.addStretch()
        layout.addWidget(self.preview_button)
        layout.addWidget(self.source_button)
        layout.addWidget(self.format_button)
        layout.addWidget(self.save_button)
        layout.addWidget(self.load_button)
        layout.addWidget(self.close_button)

        self.root_layout.addWidget(self.top_bar)

    def create_content(self) -> None:
        self.content_frame = QFrame()
        self.content_frame.setObjectName("contentFrame")

        layout = QVBoxLayout(self.content_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.preview = QTextBrowser()
        self.preview.setObjectName("preview")
        self.preview.setOpenExternalLinks(True)

        self.editor = SourceEditor()
        self.editor.setObjectName("editor")
        self.editor.setPlaceholderText("Write Markdown here...")

        layout.addWidget(self.preview)
        layout.addWidget(self.editor)

        self.root_layout.addWidget(self.content_frame)

    def create_footer(self) -> None:
        self.footer = QFrame()
        self.footer.setObjectName("footer")
        self.footer.setFixedHeight(30)

        layout = QHBoxLayout(self.footer)
        layout.setContentsMargins(20, 0, 10, 6)

        self.status = QLabel("Saved")
        self.status.setObjectName("status")

        self.mode_label = QLabel("Preview mode")
        self.mode_label.setObjectName("modeLabel")

        grip = QSizeGrip(self)
        grip.setFixedSize(18, 18)

        layout.addWidget(self.status)
        layout.addStretch()
        layout.addWidget(self.mode_label)
        layout.addSpacing(10)
        layout.addWidget(grip)

        self.root_layout.addWidget(self.footer)

    def apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget#root {
                background: #0b1120;
                border: 1px solid #1e293b;
                border-radius: 18px;
            }

            QWidget#topBar {
                background: #0b1120;
                border-bottom: 1px solid #1e293b;
                border-top-left-radius: 18px;
                border-top-right-radius: 18px;
            }

            QLabel#logo {
                color: #020617;
                background: #38bdf8;
                border-radius: 10px;
                min-width: 30px;
                min-height: 30px;
                max-width: 30px;
                max-height: 30px;
                font-size: 16px;
                font-weight: 900;
                qproperty-alignment: AlignCenter;
            }

            QLabel#title {
                color: #f8fafc;
                font-size: 14px;
                font-weight: 800;
                letter-spacing: 0.3px;
            }

            QLabel#subtitle {
                color: #64748b;
                font-size: 11px;
                font-weight: 600;
            }

            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 7px 12px;
                font-size: 13px;
                font-weight: 650;
            }

            QPushButton:hover {
                color: #e2e8f0;
                background: #111827;
                border-color: #1f2a3d;
            }

            QPushButton:pressed {
                background: #020617;
            }

            QPushButton#closeButton {
                background: #991b1b;
                color: white;
                min-width: 34px;
                border: none;
                font-weight: 800;
            }

            QPushButton#closeButton:hover {
                background: #dc2626;
            }

            QFrame#contentFrame {
                background: #0b1120;
            }

            QTextBrowser#preview {
                background: #0b1120;
                border: none;
                color: #dbeafe;
                selection-background-color: #2563eb;
                selection-color: white;
            }

            QPlainTextEdit#editor {
                background: #0b1120;
                color: #dbeafe;
                border: none;
                padding: 38px 64px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }

            QFrame#footer {
                background: #0b1120;
                border-top: 1px solid #1e293b;
                border-bottom-left-radius: 18px;
                border-bottom-right-radius: 18px;
            }

            QLabel#status,
            QLabel#modeLabel {
                color: #64748b;
                font-size: 12px;
                font-weight: 600;
            }

            QScrollBar:vertical {
                background: #0b1120;
                width: 10px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 42px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical:hover {
                background: #475569;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

    def markdown_to_html(self, text: str) -> str:
        return markdown.markdown(
            text,
            extensions=["fenced_code", "codehilite", "tables", "sane_lists", "nl2br"],
            extension_configs={
                "codehilite": {
                    "guess_lang": False,
                    "use_pygments": True,
                    "noclasses": False,
                }
            },
        )

    def build_html_page(self, body_html: str) -> str:
        pygments_css = HtmlFormatter(style="monokai").get_style_defs(".codehilite")

        return f"""
        <html>
        <head>
            <style>
                {pygments_css}

                * {{
                    box-sizing: border-box;
                }}

                body {{
                    margin: 0;
                    padding: 46px 78px 76px 78px;
                    background: #0b1120;
                    color: #cbd5e1;
                    font-family: "Inter", "Segoe UI", Arial, sans-serif;
                    font-size: 16px;
                    line-height: 1.72;
                }}

                body::before {{
                    content: "";
                    display: block;
                    height: 1px;
                    max-width: 860px;
                    margin: 0 auto;
                }}

                h1, h2, h3, p, ul, ol, blockquote, hr, table, .codehilite, pre {{
                    max-width: 860px;
                    margin-left: auto;
                    margin-right: auto;
                }}

                h1 {{
                    color: #f8fafc;
                    font-size: 36px;
                    line-height: 1.16;
                    margin-top: 0;
                    margin-bottom: 22px;
                    padding-bottom: 18px;
                    border-bottom: 1px solid #1e293b;
                    font-weight: 850;
                    letter-spacing: -0.5px;
                }}

                h2 {{
                    color: #f8fafc;
                    font-size: 25px;
                    line-height: 1.25;
                    margin-top: 40px;
                    margin-bottom: 14px;
                    font-weight: 800;
                    letter-spacing: -0.2px;
                }}

                h2::before {{
                    content: "";
                    display: inline-block;
                    width: 5px;
                    height: 22px;
                    background: #38bdf8;
                    border-radius: 999px;
                    margin-right: 12px;
                    vertical-align: -4px;
                }}

                h3 {{
                    color: #93c5fd;
                    font-size: 17px;
                    margin-top: 24px;
                    margin-bottom: 8px;
                    font-weight: 760;
                }}

                p {{
                    margin-top: 12px;
                    margin-bottom: 16px;
                }}

                ul, ol {{
                    margin-top: 12px;
                    margin-bottom: 20px;
                    padding-left: 28px;
                }}

                li {{
                    margin: 7px 0;
                }}

                blockquote {{
                    color: #cbd5e1;
                    background: #111827;
                    border: 1px solid #1e293b;
                    border-left: 4px solid #38bdf8;
                    border-radius: 12px;
                    padding: 14px 18px;
                    margin-top: 20px;
                    margin-bottom: 22px;
                }}

                hr {{
                    border: none;
                    border-top: 1px solid #1e293b;
                    margin-top: 34px;
                    margin-bottom: 34px;
                }}

                code {{
                    background: #111827;
                    color: #f0abfc;
                    padding: 2px 6px;
                    border-radius: 6px;
                    font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
                    font-size: 13px;
                }}

                .codehilite {{
                    background: #08111f !important;
                    border: 1px solid #1e293b;
                    border-left: 4px solid #38bdf8;
                    border-radius: 10px;
                    overflow: hidden;
                    margin-top: 8px;
                    margin-bottom: 16px;
                    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.22);
                }}

                .codehilite pre {{
                    background: #08111f !important;
                    margin: 0;
                    padding: 8px 12px;
                    color: #e5e7eb;
                    font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
                    font-size: 13px;
                    line-height: 1.35;
                    white-space: pre-wrap;
                    word-break: break-word;
                    max-width: none;
                }}

                pre {{
                    background: #08111f !important;
                    border: 1px solid #1e293b;
                    border-left: 4px solid #38bdf8;
                    border-radius: 10px;
                    color: #e5e7eb;
                    font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
                    font-size: 13px;
                    line-height: 1.35;
                    padding: 8px 12px;
                    white-space: pre-wrap;
                    word-break: break-word;
                }}

                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin-top: 18px;
                    margin-bottom: 22px;
                    overflow: hidden;
                    border-radius: 12px;
                    background: #08111f;
                    border: 1px solid #1e293b;
                }}

                th, td {{
                    border: 1px solid #1e293b;
                    padding: 10px 12px;
                    text-align: left;
                }}

                th {{
                    background: #111827;
                    color: #f8fafc;
                    font-weight: 760;
                }}

                td {{
                    color: #cbd5e1;
                }}

                a {{
                    color: #38bdf8;
                    text-decoration: none;
                }}

                a:hover {{
                    text-decoration: underline;
                }}

                ::selection {{
                    background: #2563eb;
                    color: white;
                }}
            </style>
        </head>
        <body>
            {body_html}
        </body>
        </html>
        """

    def on_text_changed(self) -> None:
        self.refresh_preview()
        self.status.setText("Unsaved")
        self.save_timer.start()

    def refresh_preview(self) -> None:
        html_body = self.markdown_to_html(self.editor.toPlainText())
        self.preview.setHtml(self.build_html_page(html_body))

    def format_note(self) -> None:
        text = auto_codeblock_markdown(self.editor.toPlainText())

        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)

        self.refresh_preview()
        self.save_note()
        self.show_preview_mode()

    def set_active_button(self) -> None:
        active_style = """
            background: #111827;
            color: #f8fafc;
            border: 1px solid #1f2a3d;
        """

        self.preview_button.setStyleSheet(active_style if self.mode == "preview" else "")
        self.source_button.setStyleSheet(active_style if self.mode == "source" else "")

    def show_preview_mode(self) -> None:
        self.mode = "preview"
        self.editor.hide()
        self.preview.show()
        self.mode_label.setText("Preview mode")
        self.set_active_button()

    def show_source_mode(self) -> None:
        self.mode = "source"
        self.preview.hide()
        self.editor.show()
        self.mode_label.setText("Source mode")
        self.set_active_button()
        self.editor.setFocus()


    def save_markdown_file(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Markdown Note",
            str(Path.home() / "techsticky-note.md"),
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
        )

        if not file_path:
            return

        path = Path(file_path)

        if path.suffix == "":
            path = path.with_suffix(".md")

        path.write_text(self.editor.toPlainText(), encoding="utf-8")

        self.save_note()
        self.status.setText(f"Saved: {path.name}")

    def load_markdown_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Markdown Note",
            str(Path.home()),
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
        )

        if not file_path:
            return

        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        self.editor.blockSignals(True)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)

        self.refresh_preview()
        self.save_note()
        self.status.setText(f"Loaded: {path.name}")
        self.show_preview_mode()


    def save_note(self) -> None:
        APP_DIR.mkdir(exist_ok=True)
        data = {
            "content": self.editor.toPlainText(),
            "width": self.width(),
            "height": self.height(),
            "x": self.x(),
            "y": self.y(),
            "mode": self.mode,
        }
        NOTES_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
        self.status.setText("Saved")

    def load_note(self) -> None:
        if not NOTES_FILE.exists():
            self.editor.setPlainText(DEFAULT_NOTE)
            self.refresh_preview()
            return

        try:
            data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
            self.editor.setPlainText(data.get("content", DEFAULT_NOTE))
            self.resize(data.get("width", 1120), data.get("height", 760))
            self.move(data.get("x", 120), data.get("y", 100))
            self.refresh_preview()

            self.mode = data.get("mode", "preview")
        except Exception:
            self.editor.setPlainText(DEFAULT_NOTE)
            self.refresh_preview()

    def closeEvent(self, event) -> None:
        self.save_note()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.top_bar.geometry().contains(event.position().toPoint()):
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() == Qt.LeftButton and not self.drag_position.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.drag_position = QPoint()
        self.save_note()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MarkTextSticky()
    window.show()
    sys.exit(app.exec())
