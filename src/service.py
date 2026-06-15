"""Trakt scrobbler service.

A persistent xbmc.Player that watches global playback. When a movie or episode
with a tmdb id (which Ember's source items carry on their VideoInfoTag) starts,
it scrobbles start/pause/stop to Trakt; Trakt marks an item watched once it's
stopped past ~80%. Honours the "Scrobble to Trakt" setting (checked in
trakt.scrobble). build.py wires this as an xbmc.service because the file exists.
"""
import xbmc

from resources import trakt


class _Scrobbler(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._item = None        # current Trakt scrobble payload, or None

    def onAVStarted(self):
        self._item = self._identify()
        self._send("start")

    def onPlayBackPaused(self):
        self._send("pause")

    def onPlayBackResumed(self):
        self._send("start")

    def onPlayBackStopped(self):
        self._send("stop")
        self._item = None

    def onPlayBackEnded(self):
        self._send("stop")
        self._item = None

    def _send(self, action):
        if self._item:
            trakt.scrobble(action, self._item, self._progress())

    def _progress(self):
        try:
            total = self.getTotalTime()
            return round(self.getTime() / total * 100, 2) if total else 0.0
        except RuntimeError:        # nothing playing / time not ready yet
            return 0.0

    def _identify(self):
        """Build a Trakt scrobble payload from the playing item's info tag."""
        try:
            tag = self.getVideoInfoTag()
        except RuntimeError:
            return None
        tmdb = tag.getUniqueID("tmdb")
        if not tmdb:
            return None
        media = tag.getMediaType()
        if media == "movie":
            return {"movie": {"ids": {"tmdb": int(tmdb)}}}
        if media == "episode":
            return {"show": {"ids": {"tmdb": int(tmdb)}},
                    "episode": {"season": tag.getSeason(), "number": tag.getEpisode()}}
        return None


if __name__ == "__main__":
    player = _Scrobbler()           # noqa: F841 — kept alive by the loop below
    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(5):
            break
