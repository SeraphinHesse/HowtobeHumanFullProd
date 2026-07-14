"""Easter-egg overlay: a giant red "THATS MY PRODUCER!!!!!" banner over the
producer's photo, shown for 3 seconds. Pure chrome — no selection/data tie-in.
"""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

PRODUCER_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "thats_my_producer.png"
PRODUCER_SOUND_PATH = Path(__file__).resolve().parent / "assets" / "thats_my_producer.m4a"
DISPLAY_MS = 3000


def _play_producer_sound(parent: QWidget) -> None:
    player = QMediaPlayer(parent)
    audio_output = QAudioOutput(parent)
    player.setAudioOutput(audio_output)
    player.setSource(QUrl.fromLocalFile(str(PRODUCER_SOUND_PATH)))
    player.play()
    # Keep references alive on `parent` — a GC'd QMediaPlayer/QAudioOutput
    # stops mid-playback.
    parent._producer_player = player
    parent._producer_audio_output = audio_output


def show_thats_my_producer(parent: QWidget) -> None:
    """Pop up the producer banner centered over `parent` for DISPLAY_MS,
    with the producer sound playing alongside it."""
    _play_producer_sound(parent)

    overlay = QWidget(parent)
    overlay.setAutoFillBackground(True)
    layout = QVBoxLayout(overlay)

    image_label = QLabel()
    pixmap = QPixmap(str(PRODUCER_IMAGE_PATH))
    if not pixmap.isNull():
        image_label.setPixmap(pixmap.scaledToHeight(
            400, Qt.TransformationMode.SmoothTransformation))
    image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(image_label)

    text_label = QLabel("THATS MY PRODUCER!!!!!")
    text_label.setStyleSheet("color: red; font-size: 48px; font-weight: bold;")
    text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(text_label)

    overlay.adjustSize()
    parent_center = parent.rect().center()
    overlay.move(parent_center.x() - overlay.width() // 2,
                 parent_center.y() - overlay.height() // 2)
    overlay.raise_()
    overlay.show()

    parent._producer_overlay = overlay
    QTimer.singleShot(DISPLAY_MS, overlay.deleteLater)
