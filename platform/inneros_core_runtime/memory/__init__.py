"""Memory layer — agent messages (canal único de comunicación)."""

from raphiia_openai.memory.agent_messages import (
    compact_agent_mailbox,
    compact_all_mailboxes,
    create_agent_message,
    list_agent_messages,
    migrate_legacy_agent_messages,
    sync_chatgpt_mirror,
    update_agent_message_status,
    write_agent_message,
)

__all__ = [
    "compact_agent_mailbox",
    "compact_all_mailboxes",
    "create_agent_message",
    "list_agent_messages",
    "migrate_legacy_agent_messages",
    "sync_chatgpt_mirror",
    "update_agent_message_status",
    "write_agent_message",
]
