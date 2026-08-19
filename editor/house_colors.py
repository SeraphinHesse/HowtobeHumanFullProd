"""The house colours every editor colour picker always offers.

Three named colours a designer reaches for constantly and had to retype the
hex of every time. They are seeded into ``QColorDialog``'s CUSTOM colour row
immediately before the dialog opens, so they are present in every picker in
the editor, every time — including a fresh install with no custom colours
saved, and after Qt has cycled the user's own custom slots.

**Why the LAST three slots** (``_SLOT_BASE``): Qt's own *Add to Custom
Colors* button fills the 16 slots from index 0 upward, so seeding the tail
leaves a designer's first thirteen picks alone. Re-seeding on every open is
what makes "always available" true rather than "available until something
overwrote them".

The table itself is Qt-free (and unit-tested as such); only ``pick_color``
touches Qt.
"""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

#: ``(display name, (r, g, b))`` — the names are for humans reading this
#: file and the docs; ``QColorDialog``'s custom cells carry no labels.
HOUSE_COLORS = (
    ("Pink", (0xC6, 0x51, 0x97)),
    ("Orange", (0xCF, 0x57, 0x3C)),
    ("Gold", (0xD5, 0xB7, 0x4D)),
)

#: First custom slot the house colours occupy. 16 slots exist (Qt's
#: ``QColorDialog.customCount()``), so this puts them in the last three.
_SLOT_BASE = 16 - len(HOUSE_COLORS)


def seed_house_colors():
    """Write the house colours into the shared custom-colour row.

    Application-wide and idempotent — ``QColorDialog``'s custom colours are
    static state, so one call before any picker opens is enough for that
    picker, and calling it again simply rewrites the same three slots.
    """
    for offset, (_name, rgb) in enumerate(HOUSE_COLORS):
        QColorDialog.setCustomColor(_SLOT_BASE + offset, QColor(*rgb))


def pick_color(parent, current, title="Pick a color"):
    """THE editor's colour picker: house colours seeded, then the dialog.

    ``current`` is the swatch's present ``[r, g, b]`` (anything falsy starts
    on white). Returns a fresh ``[r, g, b]`` list, or ``None`` when the
    designer cancelled — the shape every call site here already spoke.
    """
    seed_house_colors()
    base = QColor(*current[:3]) if current else QColor(255, 255, 255)
    chosen = QColorDialog.getColor(base, parent, title)
    if not chosen.isValid():
        return None
    return [chosen.red(), chosen.green(), chosen.blue()]
