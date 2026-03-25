"""Profile commands for managing connection profiles."""

import rich_click as click

from a2a_handler.common import Output
from a2a_handler.profiles import (
    find_git_root,
    load_all_profiles,
    profile_file_path,
    resolve_profile_credentials,
)


def _mask_secret(value: str) -> str:
    """Mask secret-like values for safe CLI display."""
    if len(value) > 8:
        return f"{value[:4]}...{value[-4:]}"
    return "****"


@click.group()
def profile() -> None:
    """Manage connection profiles."""
    pass


@profile.command("list")
def profile_list() -> None:
    """List all configured connection profiles."""
    output = Output()
    profiles = load_all_profiles()

    if not profiles:
        output.dim("No profiles configured")
        output.dim(f"Create profiles in {profile_file_path()}")
        return

    output.header(f"Connection Profiles ({len(profiles)})")
    for name, p in sorted(profiles.items()):
        output.blank()
        output.subheader(name)
        output.field("URL", p.agent_url)
        if p.auth:
            output.field("Auth Type", p.auth.auth_type.value)
            if p.auth.env_var:
                output.field("Env Var", p.auth.env_var)
            if p.auth.value:
                output.field("Value", _mask_secret(p.auth.value))
            if (
                p.auth.auth_type.value == "api_key"
                and p.auth.header_name != "X-API-Key"
            ):
                output.field("Header", p.auth.header_name)
        else:
            output.field("Auth", "none", dim_value=True)


@profile.command("show")
@click.argument("name")
def profile_show(name: str) -> None:
    """Show details for a specific profile."""
    output = Output()
    profiles = load_all_profiles()

    if name not in profiles:
        output.error(f"Profile '{name}' not found")
        return

    p = profiles[name]
    output.header(f"Profile: {name}")
    output.field("URL", p.agent_url)

    if not p.auth:
        output.field("Auth", "none", dim_value=True)
        return

    output.field("Auth Type", p.auth.auth_type.value)
    if p.auth.env_var:
        output.field("Env Var", p.auth.env_var)
    if p.auth.value:
        output.field("Value", _mask_secret(p.auth.value))
    if p.auth.auth_type.value == "api_key":
        output.field("Header", p.auth.header_name)

    # Resolve and show runtime status
    credentials, warning = resolve_profile_credentials(p)
    output.blank()
    if credentials:
        output.field("Status", "resolved", value_style="green")
    elif warning:
        output.field("Status", "unavailable", value_style="yellow")
        output.warning(warning)
    else:
        output.field("Status", "no auth configured", dim_value=True)


@profile.command("validate")
def profile_validate() -> None:
    """Validate all profiles and check auth resolution."""
    output = Output()
    profiles = load_all_profiles()

    if not profiles:
        output.dim("No profiles to validate")
        return

    output.header("Profile Validation")
    has_issues = False

    for name, p in sorted(profiles.items()):
        output.blank()
        output.subheader(name)
        output.field("URL", p.agent_url)

        if not p.auth:
            output.field("Auth", "none", dim_value=True)
            continue

        output.field("Auth Type", p.auth.auth_type.value)
        credentials, warning = resolve_profile_credentials(p)
        if credentials:
            output.field("Status", "ok", value_style="green")
        else:
            has_issues = True
            output.field("Status", "error", value_style="red")
            if warning:
                output.warning(warning)

    output.blank()
    if has_issues:
        output.warning("Some profiles have issues")
    else:
        output.success("All profiles valid")


@profile.command("path")
def profile_path() -> None:
    """Show the profile configuration file path."""
    output = Output()

    global_path = profile_file_path()
    output.field("Global", str(global_path))

    git_root = find_git_root()
    if git_root:
        local_path = git_root / ".handler" / "profiles.toml"
        output.field("Local (git)", str(local_path))
    else:
        output.field("Local (git)", "not in a git repository", dim_value=True)
