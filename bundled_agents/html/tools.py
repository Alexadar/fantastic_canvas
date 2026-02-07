"""HTML bundle — renders HTML content in iframes."""


def register_tools(engine, fire_broadcasts, process_runner=None):
    """No extra tools — html agents use core post_output / content_alias."""
    return {}


def register_dispatch():
    """No custom dispatch."""
    return {}
