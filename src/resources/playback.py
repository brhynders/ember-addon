"""Playback resolution — placeholder until scraping/resolving is wired up.

The /play route handlers live in addon.py; they call resolve() here. Resolution
talks to Kodi directly via router.handle (it isn't a directory listing, so it
doesn't belong in ui.py). For now there's nothing to play, so handlers pass None
and we just fail the resolve cleanly.
"""
import xbmcgui
import xbmcplugin

from resources.framework import router


def resolve(url):
    """Hand Kodi a playable URL (or fail the resolve if `url` is falsy)."""
    if url:
        xbmcplugin.setResolvedUrl(router.handle, True, xbmcgui.ListItem(path=url))
    else:
        xbmcplugin.setResolvedUrl(router.handle, False, xbmcgui.ListItem())
