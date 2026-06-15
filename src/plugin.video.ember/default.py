"""Ember plugin entry point.

Kodi invokes this script for every navigation into the addon, passing the
requested path in the plugin:// URL. We parse the action from the query string
and dispatch to the matching handler.
"""
import sys
from urllib.parse import parse_qsl

import xbmcgui
import xbmcplugin

# Handle Kodi assigns to this plugin instance, and the base plugin:// URL.
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]


def build_url(**params):
    """Build a plugin:// URL for a directory item from query parameters."""
    from urllib.parse import urlencode
    return BASE_URL + "?" + urlencode(params)


def root():
    """The addon's home screen."""
    item = xbmcgui.ListItem(label="Hello from Ember")
    xbmcplugin.addDirectoryItem(HANDLE, build_url(action="hello"), item, isFolder=False)
    xbmcplugin.endOfDirectory(HANDLE)


def hello():
    """Placeholder leaf action."""
    xbmcgui.Dialog().ok("Ember", "It works.")


def dispatch(params):
    """Route a parsed query string to its handler."""
    action = params.get("action")
    if action == "hello":
        hello()
    else:
        root()


if __name__ == "__main__":
    query = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    dispatch(dict(parse_qsl(query)))
