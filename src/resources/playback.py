"""Playback routes — placeholders until scraping/resolving is wired up.

A media row's `/play/...` URL lands here; for now we just report that playback
isn't ready and fail the resolve cleanly. Resolution talks to Kodi directly via
router.handle — it isn't a directory listing, so it doesn't belong in ui.py.
"""
import xbmcgui
import xbmcplugin

from resources.framework import notify, router


def _resolve(url):
    """Hand Kodi a playable URL (or fail the resolve if `url` is falsy)."""
    if url:
        xbmcplugin.setResolvedUrl(router.handle, True, xbmcgui.ListItem(path=url))
    else:
        xbmcplugin.setResolvedUrl(router.handle, False, xbmcgui.ListItem())


@router.route("/play/movie/{id}")
def play_movie(id):
    notify("Playback isn't wired up yet")
    _resolve(None)


@router.route("/play/episode/{id}/{season}/{episode}")
def play_episode(id, season, episode):
    notify("Playback isn't wired up yet")
    _resolve(None)
