"""The shared Plugin singleton.

Imported by addon.py (which defines the menu) and by every provider module
(tmdb.py, playback.py, ...) so they can register routes on the same instance.
Built once under reuseLanguageInvoker; run() refreshes per-navigation state.
"""
from resources.framework import Plugin

plugin = Plugin()
