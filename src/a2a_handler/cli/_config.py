"""Rich-click configuration for the CLI."""

import rich_click as click

click.rich_click.TEXT_MARKUP = "markdown"
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
click.rich_click.STYLE_HELPTEXT = ""
click.rich_click.STYLE_OPTION = "cyan"
click.rich_click.STYLE_ARGUMENT = "cyan"
click.rich_click.STYLE_COMMAND = "green"
click.rich_click.STYLE_SWITCH = "bold green"

click.rich_click.OPTION_GROUPS = {
    "handler": [
        {"name": "Global Options", "options": ["--verbose", "--debug", "--help"]},
    ],
    "handler message send": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
        {
            "name": "Message Options",
            "options": ["--text", "--stream", "--continue", "--context-id", "--task-id"],
        },
        {
            "name": "Authentication Options",
            "options": ["--bearer", "--api-key"],
        },
        {
            "name": "Push Notification Options",
            "options": ["--push-url", "--push-token"],
        },
    ],
    "handler message stream": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
        {
            "name": "Message Options",
            "options": ["--text"],
        },
        {
            "name": "Conversation Options",
            "options": ["--continue", "--context-id", "--task-id"],
        },
        {
            "name": "Authentication Options",
            "options": ["--bearer", "--api-key"],
        },
        {
            "name": "Push Notification Options",
            "options": ["--push-url", "--push-token"],
        },
    ],
    "handler task get": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
        {"name": "Query Options", "options": ["--task", "--history-length"]},
    ],
    "handler task cancel": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
    ],
    "handler task resubscribe": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
    ],
    "handler task notification set": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
        {"name": "Notification Options", "options": ["--task", "--webhook-url", "--token"]},
    ],
    "handler task notification get": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
    ],
    "handler card get": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
    ],
    "handler card validate": [
        {
            "name": "Source",
            "options": ["--url", "--server", "--file"],
        },
    ],
    "handler server add": [
        {"name": "Server", "options": ["--url"]},
        {
            "name": "Authentication",
            "options": ["--bearer", "--api-key", "--api-key-header", "--cert", "--key"],
        },
        {"name": "Scope", "options": ["--global", "--repository"]},
    ],
    "handler server remove": [
        {"name": "Scope", "options": ["--global", "--repository"]},
    ],
    "handler server run agent": [
        {"name": "Server Options", "options": ["--host", "--port", "--help"]},
    ],
    "handler server run push": [
        {"name": "Server Options", "options": ["--host", "--port", "--help"]},
    ],
    "handler session show": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
    ],
    "handler session clear": [
        {
            "name": "Target",
            "options": ["--url", "--server"],
        },
        {"name": "Clear Options", "options": ["--all", "--help"]},
    ],
    "handler auth set": [
        {
            "name": "Auth Type",
            "options": ["--bearer", "--api-key", "--api-key-header"],
        },
    ],
}

click.rich_click.COMMAND_GROUPS = {
    "handler": [
        {"name": "Agent Communication", "commands": ["message", "task"]},
        {"name": "Agent Discovery", "commands": ["card"]},
        {"name": "Authentication", "commands": ["auth"]},
        {"name": "Servers", "commands": ["server"]},
        {"name": "Interfaces", "commands": ["tui", "web"]},
        {"name": "Utilities", "commands": ["session", "version"]},
    ],
    "handler message": [
        {"name": "Message Commands", "commands": ["send", "stream"]},
    ],
    "handler task": [
        {"name": "Task Commands", "commands": ["get", "cancel", "resubscribe"]},
        {"name": "Push Notifications", "commands": ["notification"]},
    ],
    "handler task notification": [
        {"name": "Notification Commands", "commands": ["set"]},
    ],
    "handler card": [
        {"name": "Card Commands", "commands": ["get", "validate"]},
    ],
    "handler server": [
        {"name": "Management", "commands": ["list", "show", "add", "remove", "validate"]},
        {"name": "Run", "commands": ["run"]},
    ],
    "handler server run": [
        {"name": "Server Commands", "commands": ["agent", "push"]},
    ],
    "handler session": [
        {"name": "Session Commands", "commands": ["list", "show", "clear"]},
    ],
    "handler auth": [
        {"name": "Auth Commands", "commands": ["set", "show", "clear"]},
    ],
}
