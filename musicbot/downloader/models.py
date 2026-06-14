from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Song:
    """A lightweight track description.

    We only need enough metadata to label the audio file we send back to
    Telegram, so this stays tiny and keeps the whole app dependency-light.
    """

    name: str
    artist: str
    duration: int = 0
    thumbnail_path: Path | None = None

    @property
    def display_name(self) -> str:
        if self.artist:
            return f'{self.artist} - {self.name}'
        return self.name
