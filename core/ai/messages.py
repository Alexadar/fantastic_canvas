"""AI message codes — constants for provider lifecycle events."""


class AI_MSG:
    """Message codes returned to callers during provider lifecycle events."""

    PROVIDER_STOPPED = "[provider stopped]"
    PROVIDER_CHANGING = "[provider changing — please wait]"
    PROVIDER_NOT_READY = "[provider not ready]"
    PROVIDER_STARTING = "[provider starting — please wait]"
    MODEL_DOWNLOADING = "please wait — model downloading..."
    MODEL_READY = "ready"
    NO_PROVIDER = "no provider running"
    SWAP_FAILED = "swap failed"
