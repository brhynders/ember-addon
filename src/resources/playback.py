"""Playback routes — placeholders until scraping/resolving is wired up.

A media row's `/play/...` URL lands here; for now we just report that playback
isn't ready and fail the resolve cleanly. Resolution talks to Kodi directly via
plugin.handle — it isn't a directory listing, so it doesn't belong in ui.py.
"""
import xbmcgui
import xbmcplugin

from resources.framework import plugin


def _resolve(url):
    """Hand Kodi a playable URL (or fail the resolve if `url` is falsy)."""
    if url:
        xbmcplugin.setResolvedUrl(plugin.handle, True, xbmcgui.ListItem(path=url))
    else:
        xbmcplugin.setResolvedUrl(plugin.handle, False, xbmcgui.ListItem())


@plugin.route("/play/movie/{id}")
def play_movie(id):
    plugin.notify("Playback isn't wired up yet")
    _resolve(None)


@plugin.route("/play/episode/{id}/{season}/{episode}")
def play_episode(id, season, episode):
    plugin.notify("Playback isn't wired up yet")
    _resolve(None)
