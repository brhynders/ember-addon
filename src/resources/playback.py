"""Playback callbacks — placeholders until scraping/resolving is wired up.

A media row's `play.*` route lands here; for now we just report that playback
isn't ready and fail the resolve cleanly.
"""
from resources.plugin import plugin


@plugin.callback("play.movie")
def play_movie(params):
    plugin.notify("Playback isn't wired up yet")
    return plugin.resolve_fail()


@plugin.callback("play.episode")
def play_episode(params):
    plugin.notify("Playback isn't wired up yet")
    return plugin.resolve_fail()
