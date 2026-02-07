"""@chat_run — marks a bundle function as an on-demand chat agent.

Usage in a bundle's tools.py:

    from core.chat_run import chat_run

    @chat_run
    async def run(ask, say):
        name = await ask("what's your name?")
        say(f"hello {name}!")

The decorated function receives:
    ask(prompt: str) -> str   — async, prints prompt, reads user input
    say(message: str) -> None — prints message to conversation
"""


def chat_run(fn):
    """Mark an async function as a chat-capable run hook."""
    fn._chat_run = True
    return fn


def find_chat_run(module):
    """Find the @chat_run decorated function in a module. Returns fn or None."""
    for name in dir(module):
        obj = getattr(module, name, None)
        if callable(obj) and getattr(obj, "_chat_run", False):
            return obj
    return None
