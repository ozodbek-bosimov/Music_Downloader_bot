class DownloadError(Exception):
    """Base class for download-related errors."""


class UnsupportedSpotifyLinkError(DownloadError):
    """Raised for Spotify albums/playlists, which this lightweight instance
    doesn't expand (it would be too heavy for the free-tier host)."""


class DownloadBlockedError(DownloadError):
    """YouTube refused the request ("Sign in to confirm you're not a bot").
    Usually temporary rate-limiting; cookies fix it long-term."""


class TrackTooLargeError(DownloadError):
    """The audio is larger than the Telegram upload limit."""


class VideoUnavailableError(DownloadError):
    """The video is private, removed, region-locked or otherwise unavailable."""

class DRMProtectedError(DownloadError):
    """The track is DRM protected and cannot be downloaded."""
