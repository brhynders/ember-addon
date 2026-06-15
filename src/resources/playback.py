"""Playback routes — placeholders until scraping/resolving is wired up.

A media row's `/play/...` URL lands here; for now we just report that playback
isn't ready and fail the resolve cleanly.
"""
from resources.framework import plugin


@plugin.route("/play/movie/{id}")
def play_movie(id):
    plugin.notify("Playback isn't wired up yet")
    plugin.resolve_fail()


@plugin.route("/play/episode/{id}/{season}/{episode}")
def play_episode(id, season, episode):
    plugin.notify("Playback isn't wired up yet")
    plugin.resolve_fail()
