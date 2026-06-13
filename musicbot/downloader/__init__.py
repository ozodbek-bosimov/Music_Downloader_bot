from .client import Downloader
from .models import Song

downloader = Downloader()

__all__ = ['Downloader', 'Song', 'downloader']
