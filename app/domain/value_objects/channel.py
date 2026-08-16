"""Channel value object — the closed set of supported communication channels.

Extended in Phase 4 (Change 2) to include SLACK and DISCORD alongside EMAIL and TELEGRAM, so
the Channel Registry can reason about all four. Having a member here does not imply a working
adapter exists — only EMAIL and TELEGRAM have adapters scaffolded under
app/integrations/inbound/channels/ (still stubs); SLACK and DISCORD are registry-known but
adapter-less until a future phase builds them. The Channel Registry (see
app/domain/services/channel_registry.py) is what tracks which of the four are actually
usable right now — this enum is just the closed set of possible values.
"""

from enum import Enum


class Channel(str, Enum):
    EMAIL = "email"
    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
