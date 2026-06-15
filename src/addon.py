"""Ember entry point — register the routes (once) and run the dispatch loop.

The route handlers live in resources/routes.py. Importing that module runs its
`@router.route` decorators, registering every route. Under reuseLanguageInvoker
this entry script re-executes on each navigation, but the imported routes module
is cached, so registration happens once per interpreter — not once per nav (which
would otherwise keep appending duplicate routes to the singleton router).
"""
from resources import routes  # noqa: F401 — importing registers all @router.route handlers
from resources.framework import router

if __name__ == "__main__":
    router.run()
