"""Pure helpers for the sound-slot widget (SoundEditorPLAN SD-3) —
``data/audio/imported/`` import-copy plus the cross-domain clip refcount.

Qt-free, pygame-free (the ``editor/asset_import.py`` / ``editor/font_import.py``
/ ``editor/cutscene_import.py`` sibling — in ``test_editor_viewport.TestPurity``'s
import list): ``panels/sound_slot.py`` is the only caller.

``data_dir`` is injected on every function; there is no module-level ``data/``
path, so tests run against a temp copy.

REFCOUNTS ARE CROSS-DOMAIN. A clip attached to an enemy sound slot must not read
as "unused" while the designer browses ``buildings`` — the picker would then
invite deleting art that is in use. ``usage_docs`` therefore builds
``{domain: doc_or_None}`` over EVERY domain ``editor.domains.domains()`` derives
(never a hardcoded five), and:

* the domain currently open in the panel is NOT re-read from disk — its entry is
  the live STAGED doc, so a clip the designer attached seconds ago and has not
  saved already counts as referenced;
* a domain that fails to load degrades to ``None`` — "count unknown", never
  zero. ``unreferenced_clips`` returns NOTHING while any domain is unknown. A
  clip reported unreferenced because a file failed to parse is the one failure
  mode that costs a designer their audio.

Nothing here enumerates sound SLOTS: ``clip_users`` walks any document shape and
matches on the slot's own structure (``clips`` list of objects carrying
``file``), so a slot added to a schema later is counted with zero edits here.
"""
import shutil
from dataclasses import dataclass
from pathlib import Path

from editor import domains as domains_mod
from engine import data_io

#: Extensions the importer accepts (D8). Anything else is rejected, not copied.
AUDIO_SUFFIXES = (".ogg", ".wav", ".mp3")

#: Where imported clips land, relative to ``data/audio/``.
IMPORTED_DIRNAME = "imported"

#: Clips above this are worth warning about before they are committed:
#: ``data/audio/Bass_and_drum_Duo.wav`` is already 49 MB, and imported clips are
#: committed content.
OVERSIZE_WARN_BYTES = 8 * 1024 * 1024


def audio_dir(data_dir):
    return Path(data_dir) / "audio"


def imported_dir(data_dir):
    return audio_dir(data_dir) / IMPORTED_DIRNAME


def clip_ref(name, suffix=".ogg"):
    """The ``imported/<name><suffix>`` string stored in a clip's ``file`` —
    relative to ``data/audio/``, which is what the engine resolves against."""
    return f"{IMPORTED_DIRNAME}/{name}{suffix}"


def clip_path(data_dir, ref):
    """Absolute path of a stored ``file`` ref. ``""`` (no clip) -> None."""
    if not ref:
        return None
    return audio_dir(data_dir) / ref


def is_audio(src_path):
    return Path(src_path).suffix.lower() in AUDIO_SUFFIXES


def transcode_available():
    """True when the optional ``soundfile`` dependency imports. Absent means the
    transcode checkbox greys out and the raw-copy path still works — the
    ``opencv-python`` OPTIONAL precedent (``engine/video.py``)."""
    try:
        import soundfile  # noqa: F401
    except Exception:
        return False
    return True


def warn_oversize(path):
    """True when this file is big enough to be worth a confirmation. Imported
    clips are committed content, so a 50 MB wav is a repo decision."""
    try:
        return Path(path).stat().st_size > OVERSIZE_WARN_BYTES
    except OSError:
        return False


def _mint_name(data_dir, stem, suffix):
    """A destination stem that does not collide with an existing import.

    Unlike a cutscene's audio (1:1-owned by its id, ``cutscene_import.audio_dest``)
    a clip is SHARED between slots, so the stem is not owned by anything and a
    same-named second import must not silently overwrite the first."""
    dest_dir = imported_dir(data_dir)
    if not (dest_dir / f"{stem}{suffix}").exists():
        return stem
    i = 2
    while (dest_dir / f"{stem}_{i}{suffix}").exists():
        i += 1
    return f"{stem}_{i}"


def _copy_if_different(src_path, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Path(src_path).resolve() != dest.resolve():
        shutil.copyfile(src_path, dest)


def _transcode_to_ogg(src_path, dest):
    """Best-effort ``soundfile`` transcode. Returns True on success; False means
    the caller falls back to a raw copy — an absent/failing optional dependency
    must never block an import."""
    try:
        import soundfile
    except Exception:
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        data, samplerate = soundfile.read(str(src_path))
        soundfile.write(str(dest), data, samplerate, format="OGG")
    except Exception:
        return False
    return True


def import_clip(data_dir, src, name=None, transcode=False):
    """Copy (or transcode) ``src`` into ``data/audio/imported/`` and return the
    ``imported/<name><suffix>`` ref to store in a clip's ``file``.

    Rejects any extension outside :data:`AUDIO_SUFFIXES` with ``ValueError``
    rather than copying a file the engine cannot load. A colliding stem is
    minted a suffixed name; nothing is ever overwritten.
    """
    src = Path(src)
    if not is_audio(src):
        raise ValueError(
            f"{src.name}: not an audio file "
            f"(accepted: {', '.join(AUDIO_SUFFIXES)})")
    suffix = src.suffix.lower()
    want_transcode = bool(transcode) and suffix != ".ogg" and transcode_available()
    if want_transcode:
        suffix = ".ogg"
    stem = name or src.stem
    stem = _mint_name(data_dir, stem, suffix)
    dest = imported_dir(data_dir) / f"{stem}{suffix}"
    if want_transcode and _transcode_to_ogg(src, dest):
        return clip_ref(stem, suffix)
    if want_transcode:
        # The transcode failed (or soundfile choked on the format): fall back to
        # a raw copy under the SOURCE's suffix, so the import still succeeds.
        suffix = src.suffix.lower()
        stem = _mint_name(data_dir, name or src.stem, suffix)
        dest = imported_dir(data_dir) / f"{stem}{suffix}"
    _copy_if_different(src, dest)
    return clip_ref(stem, suffix)


# -- refcount (PURE — never reads data/; the caller passes the docs in) -------


def _walk_slot_files(node, out):
    """Collect every ``clips[i].file`` under any node shape. Slot-agnostic on
    purpose: no slot name, no domain key and no ``Sounds``/``sounds`` spelling
    appears here, so a slot added by a later schema change is counted for free.
    """
    if isinstance(node, dict):
        clips = node.get("clips")
        if isinstance(clips, list):
            for clip in clips:
                if isinstance(clip, dict) and isinstance(clip.get("file"), str):
                    if clip["file"]:
                        out.append(clip["file"])
        for value in node.values():
            _walk_slot_files(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_slot_files(value, out)


def clip_users(docs, ref):
    """Domains whose document references ``ref``, plus whether any domain's
    usage is UNKNOWN.

    ``docs`` is ``{domain: doc_or_None}`` covering every domain; a ``None``
    entry means that domain could not be read. Returns
    ``(users, unknown)`` — ``users`` a sorted tuple of domain keys, ``unknown``
    a sorted tuple of the domains whose count could not be established. A
    non-empty ``unknown`` means "count unknown", NEVER "unreferenced".
    """
    users = []
    unknown = []
    for domain, doc in (docs or {}).items():
        if doc is None:
            unknown.append(domain)
            continue
        found = []
        _walk_slot_files(doc, found)
        if ref in found:
            users.append(domain)
    return tuple(sorted(users)), tuple(sorted(unknown))


def unreferenced_clips(docs, refs):
    """The subset of ``refs`` no domain in ``docs`` references.

    Returns ``()`` while ANY domain is unknown: a clip must never be reported
    free-to-delete because a balancing file failed to load.
    """
    if any(doc is None for doc in (docs or {}).values()):
        return ()
    return tuple(ref for ref in dict.fromkeys(refs)
                 if not clip_users(docs, ref)[0])


# -- the ONE disk-reading function here --------------------------------------


def usage_docs(data_dir, staged_domain=None, staged_doc=None):
    """``{domain: doc_or_None}`` for every balancing domain, for the refcount.

    * The domain list is ``editor.domains.domains(data_dir)`` — DERIVED, never a
      hardcoded five. A domain with no sound slots simply contributes no users.
    * ``staged_domain`` is NOT read from disk; its entry is ``staged_doc``
      verbatim (the live staged document), so a just-attached, unsaved clip
      counts as referenced.
    * Every other domain is loaded with ``data_io.load_validated``; a per-domain
      failure degrades that entry to ``None`` — "count unknown", never an empty
      doc.
    """
    out = {}
    for domain in domains_mod.domains(data_dir):
        if staged_domain is not None and domain == staged_domain:
            out[domain] = staged_doc
            continue
        try:
            out[domain] = data_io.load_validated(
                domains_mod.balancing_path(domain, data_dir),
                domains_mod.schema_path(domain, data_dir),
            )
        except Exception:
            out[domain] = None
    if staged_domain is not None and staged_domain not in out:
        out[staged_domain] = staged_doc
    return out


@dataclass(frozen=True)
class ImportedClip:
    """One file in ``data/audio/imported/``, as offered by the reuse picker.

    ``users`` empty AND ``unknown`` empty ⇒ genuinely nobody references it (an
    orphan; listed on purpose — it is how you get that audio back). ``unknown``
    non-empty ⇒ usage could not be established; the picker labels the row
    "usage unknown" rather than "unused". Mirrors ``asset_import.ImportedSheet``.
    """

    ref: str            # "imported/<name>.ogg" — what goes in a clip's `file`
    path: Path
    size: int           # bytes
    users: tuple        # domain keys referencing it, sorted
    unknown: tuple      # domain keys whose usage could not be read, sorted

    @property
    def name(self):
        return self.path.stem

    @property
    def usage_known(self):
        return not self.unknown


def imported_clips(data_dir, docs=None):
    """Every audio file already in ``data/audio/imported/``, sorted by name and
    annotated with the domains using it. ``docs`` is the ``usage_docs`` mapping;
    omitted means "usage unknown for everything", which the picker shows as
    such and which never claims a clip is unused."""
    data_dir = Path(data_dir)
    out = []
    for path in sorted(imported_dir(data_dir).glob("*")):
        if path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        ref = clip_ref(path.stem, path.suffix.lower())
        if docs is None:
            users, unknown = (), ("<not loaded>",)
        else:
            users, unknown = clip_users(docs, ref)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        out.append(ImportedClip(ref=ref, path=path, size=size,
                                users=users, unknown=unknown))
    return tuple(out)
