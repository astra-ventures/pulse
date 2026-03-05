#!/usr/bin/env python3
"""
Pulse CLI — manage the autonomous cognition engine.

Usage:
    pulse                     Show status overview
    pulse status              Show status overview
    pulse drives              Show all drives with pressure visualization
    pulse triggers            Recent trigger history
    pulse mutations           Mutation audit log
    pulse mutate <json>       Submit a mutation (or interactive)
    pulse spike <drive> [amt] Spike a drive's pressure
    pulse decay <drive> [amt] Decay a drive's pressure
    pulse config              Show current config
    pulse start               Start the daemon
    pulse stop                Stop the daemon  
    pulse restart             Restart the daemon
    pulse logs [n]            Show recent log lines
    pulse health              Raw health check
"""

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Rich imports
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich import box

console = Console()

HEALTH_URL = "http://127.0.0.1:{port}"
DEFAULT_PORT = 9720
_DEFAULT_STATE_DIR = Path("~/.pulse/state").expanduser()
LOG_FILE = Path("~/.pulse/logs/pulse.log").expanduser()
STDOUT_LOG = Path("~/.pulse/logs/pulse-stdout.log").expanduser()
PID_FILE = Path("~/.pulse/pulse.pid").expanduser()
MUTATIONS_FILE = _DEFAULT_STATE_DIR / "mutations.json"
PLIST = Path("~/Library/LaunchAgents/ai.openclaw.pulse.plist").expanduser()


def _port():
    """Get health port from config or default."""
    return DEFAULT_PORT


def _get(endpoint: str) -> dict:
    """GET a JSON endpoint from the health API."""
    import urllib.request
    url = f"{HEALTH_URL.format(port=_port())}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _is_running() -> tuple:
    """Check if daemon is running. Returns (running, pid)."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True, pid
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    return False, None


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"
    else:
        d = int(seconds // 86400)
        h = int((seconds % 86400) // 3600)
        return f"{d}d {h}h"


def _format_ago(timestamp: float) -> str:
    """Format a timestamp as 'Xm ago'."""
    if not timestamp:
        return "never"
    ago = time.time() - timestamp
    return f"{_format_duration(ago)} ago"


def _pressure_bar(pressure: float, max_p: float = 5.0, width: int = 20) -> Text:
    """Create a colored pressure bar."""
    ratio = min(pressure / max_p, 1.0)
    filled = int(ratio * width)
    empty = width - filled

    if ratio < 0.3:
        color = "green"
    elif ratio < 0.6:
        color = "yellow"
    elif ratio < 0.8:
        color = "bright_red"
    else:
        color = "red bold"

    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * empty, style="dim")
    return bar


def _write_mutation_queue(mutations: list):
    """Write mutations to queue with file locking (matches daemon's lock)."""
    MUTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Touch the file if it doesn't exist
    if not MUTATIONS_FILE.exists():
        MUTATIONS_FILE.write_text("[]")

    with open(MUTATIONS_FILE, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            raw = f.read().strip()
            existing = []
            if raw and raw != "[]":
                try:
                    existing = json.loads(raw)
                    if not isinstance(existing, list):
                        existing = [existing]
                except json.JSONDecodeError:
                    existing = []
            existing.extend(mutations)
            f.seek(0)
            f.write(json.dumps(existing, indent=2))
            f.truncate()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ─── Commands ────────────────────────────────────────────────────

# Preset configs for pulse init
_PRESETS = {
    "1": {
        "name": "Personal Assistant",
        "desc": "Curiosity, growth, social, goals — balanced autonomous agent",
        "drives": {
            "goals":     {"weight": 1.2},
            "curiosity": {"weight": 0.8},
            "emotions":  {"weight": 0.9},
            "growth":    {"weight": 0.7},
            "social":    {"weight": 0.6},
            "unfinished":{"weight": 0.9},
        },
    },
    "2": {
        "name": "Research Agent",
        "desc": "Curiosity and unfinished work dominate — deep focus mode",
        "drives": {
            "curiosity": {"weight": 1.5},
            "unfinished":{"weight": 1.3},
            "goals":     {"weight": 0.8},
            "growth":    {"weight": 0.6},
        },
    },
    "3": {
        "name": "Minimal (system only)",
        "desc": "Just the system health drive — lowest pressure, quiet agent",
        "drives": {
            "system": {"weight": 1.0},
            "goals":  {"weight": 0.8},
        },
    },
}

_INIT_CONFIG_TEMPLATE = """\
# Pulse Configuration — generated by `pulse init`
# Edit to customize. See pulse.example.yaml for all options.

openclaw:
  webhook_url: "http://127.0.0.1:18789/hooks/agent"
  webhook_token: "${{PULSE_HOOK_TOKEN}}"
  max_turns_per_hour: 10
  min_trigger_interval: 300

workspace:
  root: "{workspace}"

drives:
  pressure_rate: 0.01
  trigger_threshold: 0.7
  max_pressure: 1.0
  success_decay: 0.5
  override_min_individual_pressure: 1.5
  adaptive_decay: true
  categories:
{drive_lines}
logging:
  file: "~/.pulse/logs/pulse.log"
  level: "INFO"
"""


def _indent_drives(drives: dict) -> str:
    lines = []
    for name, cfg in drives.items():
        lines.append(f"    {name}:")
        lines.append(f"      weight: {cfg['weight']}")
    return "\n".join(lines)


def cmd_init(args):
    """Interactive setup — configure and start Pulse in under 3 minutes."""
    import shutil

    console.print()
    console.print(Panel(
        "[bold cyan]Welcome to Pulse[/bold cyan]\n"
        "[dim]Autonomous cognition engine for OpenClaw agents[/dim]\n\n"
        "This wizard will set up your Pulse configuration.\n"
        "Takes about 2-3 minutes.",
        title="🫀 [bold]pulse init[/bold]",
        border_style="cyan",
    ))
    console.print()

    config_dir  = Path("~/.pulse/config").expanduser()
    config_file = config_dir / "pulse.yaml"
    env_file    = Path("~/.pulse/.env").expanduser()

    # ── Check existing config ──────────────────────────────────────────────────
    if config_file.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {config_file}")
        overwrite = console.input("Overwrite? [y/N] ").strip().lower()
        if overwrite != "y":
            console.print("[dim]Aborted. Your existing config is unchanged.[/dim]")
            return

    # ── Webhook token ──────────────────────────────────────────────────────────
    console.print("[bold]Step 1/3[/bold] — OpenClaw webhook token")
    console.print("[dim]Find it at: Settings → Webhooks in OpenClaw[/dim]")
    console.print("[dim]Or run: openclaw config | grep HOOKS_TOKEN[/dim]")
    console.print()

    env_token = os.environ.get("PULSE_HOOK_TOKEN") or os.environ.get("OPENCLAW_HOOKS_TOKEN", "")
    if env_token:
        console.print(f"[green]✓ Found token in environment[/green] (first 8 chars: {env_token[:8]}...)")
        token = env_token
    else:
        token = console.input("Webhook token: ").strip()
        if not token:
            console.print("[red]Error: token required.[/red]")
            return

    # ── Workspace path ─────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]Step 2/3[/bold] — Workspace path")
    default_ws = str(Path("~/.openclaw/workspace").expanduser())
    console.print(f"[dim]Default: {default_ws}[/dim]")
    ws_input = console.input(f"Workspace path [{default_ws}]: ").strip()
    workspace = ws_input or default_ws

    # ── Preset ────────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]Step 3/3[/bold] — Agent personality")
    for k, v in _PRESETS.items():
        console.print(f"  [{k}] {v['name']} — {v['desc']}")
    preset_key = console.input("Choose [1/2/3] (default 1): ").strip() or "1"
    preset = _PRESETS.get(preset_key, _PRESETS["1"])
    console.print(f"[green]✓[/green] {preset['name']} selected")

    # ── Write config ───────────────────────────────────────────────────────────
    console.print()
    console.print("[dim]Writing configuration...[/dim]")

    config_dir.mkdir(parents=True, exist_ok=True)
    Path("~/.pulse/logs").expanduser().mkdir(parents=True, exist_ok=True)
    Path("~/.pulse/state").expanduser().mkdir(parents=True, exist_ok=True)

    drive_lines = _indent_drives(preset["drives"])
    config_content = _INIT_CONFIG_TEMPLATE.format(
        workspace=workspace,
        drive_lines=drive_lines,
    )
    config_file.write_text(config_content)
    console.print(f"[green]✓[/green] Config written to {config_file}")

    # Write .env
    env_content = f"PULSE_HOOK_TOKEN={token}\n"
    if env_file.exists():
        # Preserve existing, update/add PULSE_HOOK_TOKEN
        lines = [ln for ln in env_file.read_text().splitlines() if not ln.startswith("PULSE_HOOK_TOKEN=")]
        lines.append(f"PULSE_HOOK_TOKEN={token}")
        env_file.write_text("\n".join(lines) + "\n")
    else:
        env_file.write_text(env_content)
    console.print(f"[green]✓[/green] Token saved to {env_file}")

    # ── LaunchAgent ───────────────────────────────────────────────────────────
    console.print()
    plist = Path("~/Library/LaunchAgents/ai.openclaw.pulse.plist").expanduser()
    if plist.exists():
        console.print(f"[dim]LaunchAgent already installed at {plist}[/dim]")
        install_la = False
    else:
        la_answer = console.input("Install LaunchAgent (auto-start on login)? [Y/n] ").strip().lower()
        install_la = la_answer != "n"

    if install_la and not plist.exists():
        # Find the pulse binary
        pulse_bin = shutil.which("pulse") or str(Path("~/.local/bin/pulse").expanduser())
        run_sh    = Path("~/.pulse/run.sh").expanduser()

        run_sh_content = f"""#!/bin/bash
set -a; source ~/.pulse/.env; set +a
cd {workspace}
exec {pulse_bin or 'python3 -m pulse.src'}
"""
        run_sh.write_text(run_sh_content)
        run_sh.chmod(0o755)

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>          <string>ai.openclaw.pulse</string>
    <key>ProgramArguments</key>
    <array><string>{run_sh}</string></array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>  <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>PULSE_HOOK_TOKEN</key>  <string>{token}</string>
        <key>HOME</key>  <string>{Path.home()}</string>
    </dict>
    <key>RunAtLoad</key>    <true/>
    <key>KeepAlive</key>    <true/>
    <key>ThrottleInterval</key>  <integer>30</integer>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.pulse/logs/pulse-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.pulse/logs/pulse-stderr.log</string>
</dict>
</plist>"""
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(plist_content)
        os.system(f"launchctl load {plist} 2>/dev/null")
        console.print(f"[green]✓[/green] LaunchAgent installed and loaded")

    # ── Start daemon ───────────────────────────────────────────────────────────
    console.print()
    start_answer = console.input("Start Pulse now? [Y/n] ").strip().lower()
    if start_answer != "n":
        running, _ = _is_running()
        if running:
            console.print("[green]✓ Pulse is already running[/green]")
        else:
            cmd_start(args)

    # ── Done ───────────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold green]Setup complete![/bold green]\n\n"
        f"  Config:  [dim]{config_file}[/dim]\n"
        f"  Preset:  [dim]{preset['name']}[/dim]\n\n"
        "  [bold]pulse status[/bold]   — check if daemon is running\n"
        "  [bold]pulse drives[/bold]   — see drive pressure levels\n"
        "  [bold]pulse logs[/bold]     — watch the log stream\n"
        "  [bold]pulse stop[/bold]     — stop the daemon",
        title="🫀 [bold]Pulse is ready[/bold]",
        border_style="green",
    ))


def cmd_status(args):
    """Show full status overview."""
    running, pid = _is_running()

    # Header
    console.print()
    console.print("🫀 [bold magenta]Pulse[/] — Autonomous Cognition Engine", highlight=False)
    console.print()

    # Status table
    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold", min_width=18)
    table.add_column("Value")

    if running:
        health = _get("/health")
        status_data = _get("/status")

        # Daemon status
        table.add_row("Status", f"[green bold]● running[/] (pid {pid})")
        if health:
            table.add_row("Uptime", _format_duration(health.get("uptime_seconds", 0)))
            table.add_row("Triggers", str(health.get("turn_count", 0)))
        
        if status_data:
            # Rate limits
            rl = status_data.get("rate_limit", {})
            table.add_row(
                "Rate",
                f"{rl.get('turns_last_hour', 0)}/{rl.get('max_per_hour', 10)} turns/hr · "
                f"cooldown {rl.get('cooldown_remaining', 0)}s"
            )

            # Last trigger
            ts = status_data.get("triggers", {})
            lt = ts.get("last")
            if lt:
                table.add_row("Last trigger", f"{_format_ago(lt.get('timestamp', 0))}")
            else:
                table.add_row("Last trigger", "[dim]none yet[/]")

            # Evaluator mode
            ev = status_data.get("evaluator", {})
            mode = ev.get("mode", "?")
            if mode == "model":
                model = ev.get("model", "?")
                table.add_row("Evaluator", f"[cyan]model[/] ({model})")
            else:
                table.add_row("Evaluator", "[yellow]rules[/]")

            # Drive summary
            drives = status_data.get("drives", {})
            if drives:
                top = max(drives.items(), key=lambda x: x[1].get("weighted", 0))
                total = sum(d.get("weighted", 0) for d in drives.values())
                table.add_row(
                    "Drives",
                    f"{len(drives)} active · top: [bold]{top[0]}[/] "
                    f"({top[1].get('pressure', 0):.1f}) · total pressure: {total:.1f}"
                )

            # Trigger stats
            if ts.get("total", 0) > 0:
                table.add_row(
                    "Trigger stats",
                    f"{ts.get('total', 0)} total · {ts.get('successful', 0)} successful"
                )
        
        table.add_row("Health", f"http://127.0.0.1:{_port()}")
        table.add_row("Service", "LaunchAgent" if PLIST.exists() else "[dim]manual[/]")
        table.add_row("State", str(_DEFAULT_STATE_DIR))
        table.add_row("Logs", str(STDOUT_LOG))
    else:
        table.add_row("Status", "[red bold]● stopped[/]")
        table.add_row("Service", "LaunchAgent" if PLIST.exists() else "[dim]not installed[/]")
        table.add_row("State", str(_DEFAULT_STATE_DIR))
        if _DEFAULT_STATE_DIR.exists():
            state_file = _DEFAULT_STATE_DIR / "pulse-state.json"
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text())
                    saved_at = data.get("_saved_at", 0)
                    table.add_row("Last state", _format_ago(saved_at))
                    drives = data.get("drives", {})
                    if drives:
                        table.add_row("Saved drives", f"{len(drives)} drives persisted")
                except Exception:
                    pass

    console.print(table)
    console.print()


def cmd_drives(args):
    """Show all drives with pressure visualization."""
    running, _ = _is_running()

    max_p = 5.0  # default

    if running:
        data = _get("/status")
        if not data:
            console.print("[red]Could not connect to Pulse health endpoint[/]")
            return
        drives = data.get("drives", {})
        max_p = data.get("max_pressure", 5.0)
    else:
        # Read from state file
        state_file = _DEFAULT_STATE_DIR / "pulse-state.json"
        if not state_file.exists():
            console.print("[dim]No drive state found[/]")
            return
        state = json.loads(state_file.read_text())
        drives = state.get("drives", {})
        console.print("[yellow]⚠ Pulse is stopped — showing last saved state[/]\n")

    if not drives:
        console.print("[dim]No drives configured[/]")
        return

    console.print("🫀 [bold magenta]Pulse Drives[/]\n")

    table = Table(box=box.SIMPLE_HEAVY, padding=(0, 1))
    table.add_column("Drive", style="bold", min_width=12)
    table.add_column("Pressure", min_width=24)
    table.add_column("Value", justify="right", min_width=6)
    table.add_column("Weight", justify="right", min_width=6)
    table.add_column("Weighted", justify="right", min_width=8)
    table.add_column("Last Addressed", min_width=12)

    # Sort by weighted pressure descending
    sorted_drives = sorted(
        drives.items(),
        key=lambda x: x[1].get("weighted", x[1].get("pressure", 0) * x[1].get("weight", 1)),
        reverse=True,
    )

    for name, d in sorted_drives:
        pressure = d.get("pressure", 0)
        weight = d.get("weight", 1.0)
        weighted = d.get("weighted", pressure * weight)
        last = d.get("last_addressed", 0)

        bar = _pressure_bar(pressure, max_p=max_p)
        table.add_row(
            name,
            bar,
            f"{pressure:.2f}",
            f"×{weight:.1f}",
            f"[bold]{weighted:.2f}[/]",
            _format_ago(last) if last else "[dim]never[/]",
        )

    console.print(table)

    total = sum(d.get("weighted", d.get("pressure", 0) * d.get("weight", 1)) for d in drives.values())
    console.print(f"\n  Total weighted pressure: [bold]{total:.2f}[/]")
    
    # Show threshold
    if running:
        status = _get("/status")
        if status:
            console.print(f"  Trigger threshold: {status.get('trigger_threshold', '?')}")
    console.print()


def cmd_triggers(args):
    """Show recent trigger history."""
    history_file = _DEFAULT_STATE_DIR / "trigger-history.jsonl"
    if not history_file.exists():
        console.print("[dim]No trigger history yet[/]")
        return

    n = args.count or 20
    entries = []
    with open(history_file) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    entries = entries[-n:]
    if not entries:
        console.print("[dim]No triggers recorded[/]")
        return

    console.print(f"🫀 [bold magenta]Pulse Triggers[/] (last {len(entries)})\n")

    table = Table(box=box.SIMPLE, padding=(0, 1))
    table.add_column("Time", min_width=18)
    table.add_column("", min_width=2)
    table.add_column("Drive", min_width=10)
    table.add_column("Pressure", justify="right", min_width=8)
    table.add_column("Reason", max_width=60)

    for entry in reversed(entries):
        ts = entry.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts).strftime("%b %d %I:%M %p")
        success = "✅" if entry.get("success") else "❌"
        drive = entry.get("top_drive", "?")
        pressure = entry.get("pressure", 0)
        reason = entry.get("reason", "?")
        # Truncate long reasons
        if len(reason) > 60:
            reason = reason[:57] + "..."

        table.add_row(dt, success, drive, f"{pressure:.2f}", reason)

    console.print(table)
    console.print()


def cmd_mutations(args):
    """Show mutation audit log."""
    log_file = _DEFAULT_STATE_DIR / "mutations.jsonl"
    if not log_file.exists():
        console.print("[dim]No mutations recorded yet[/]")
        return

    n = args.count or 20
    entries = []
    with open(log_file) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    entries = entries[-n:]
    if not entries:
        console.print("[dim]No mutations recorded[/]")
        return

    console.print(f"🧬 [bold magenta]Pulse Mutations[/] (last {len(entries)})\n")

    table = Table(box=box.SIMPLE, padding=(0, 1))
    table.add_column("Time", min_width=18)
    table.add_column("Type", min_width=12)
    table.add_column("Target", min_width=20)
    table.add_column("Change", min_width=16)
    table.add_column("", min_width=2)
    table.add_column("Reason", max_width=40)

    for entry in reversed(entries):
        ts = entry.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts).strftime("%b %d %I:%M %p")
        mut_type = entry.get("mutation_type", "?")
        target = entry.get("target", "?")
        before = entry.get("before", "?")
        after = entry.get("after", "?")
        clamped = "⚠️" if entry.get("clamped") else ""
        reason = entry.get("reason", "")
        if len(reason) > 40:
            reason = reason[:37] + "..."

        change = f"{before} → {after}"
        if len(str(change)) > 16:
            change = str(change)[:16]

        table.add_row(dt, mut_type, target, change, clamped, reason)

    console.print(table)
    
    total = 0
    clamped = 0
    with open(log_file) as f:
        for line in f:
            total += 1
            try:
                if json.loads(line).get("clamped"):
                    clamped += 1
            except Exception:
                pass
    console.print(f"\n  Total: {total} mutations · {clamped} clamped by guardrails")
    console.print()


def cmd_mutate(args):
    """Submit a mutation to the queue."""
    if args.json_str:
        try:
            mutation = json.loads(args.json_str)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON:[/] {e}")
            return
    else:
        # Interactive mode
        console.print("🧬 [bold]Submit Mutation[/]\n")
        console.print("Types: adjust_weight, adjust_threshold, adjust_rate,")
        console.print("       adjust_cooldown, add_drive, remove_drive, spike_drive, decay_drive\n")
        
        mut_type = console.input("[bold]Type:[/] ").strip()
        if not mut_type:
            return

        mutation = {"type": mut_type}
        
        # Get valid drive names for validation
        valid_drives = set()
        status = _get("/status")
        if status:
            valid_drives = set(status.get("drives", {}).keys())
        
        if mut_type in ("adjust_weight", "remove_drive", "spike_drive", "decay_drive"):
            if valid_drives:
                console.print(f"  [dim]Available: {', '.join(sorted(valid_drives))}[/]")
            drive_name = console.input("[bold]Drive name:[/] ").strip()
            if valid_drives and drive_name not in valid_drives and mut_type != "spike_drive":
                console.print(f"[yellow]Warning: '{drive_name}' not in current drives[/]")
            mutation["drive"] = drive_name
        if mut_type == "add_drive":
            mutation["name"] = console.input("[bold]Drive name:[/] ").strip()
        if mut_type in ("adjust_weight", "adjust_threshold", "adjust_rate", "adjust_cooldown", "adjust_turns_per_hour"):
            mutation["value"] = float(console.input("[bold]Value:[/] ").strip())
        if mut_type == "add_drive":
            mutation["weight"] = float(console.input("[bold]Weight (0.1-2.0):[/] ").strip() or "0.5")
        if mut_type in ("spike_drive", "decay_drive"):
            mutation["amount"] = float(console.input("[bold]Amount:[/] ").strip() or "0.3")
        
        mutation["reason"] = console.input("[bold]Reason:[/] ").strip() or "manual CLI mutation"

    # Write to queue with locking
    items = mutation if isinstance(mutation, list) else [mutation]
    _write_mutation_queue(items)
    console.print(f"\n[green]✓[/] Mutation queued → will apply next cycle (~30s)")
    console.print(f"  [dim]{json.dumps(mutation)}[/]")


def cmd_spike(args):
    """Quick spike a drive."""
    mutation = {
        "type": "spike_drive",
        "drive": args.drive,
        "amount": args.amount,
        "reason": "manual spike via CLI",
    }
    _write_mutation_queue([mutation])
    console.print(f"[green]✓[/] Spiked [bold]{args.drive}[/] +{args.amount} → next cycle")


def cmd_decay(args):
    """Quick decay a drive."""
    mutation = {
        "type": "decay_drive",
        "drive": args.drive,
        "amount": args.amount,
        "reason": "manual decay via CLI",
    }
    _write_mutation_queue([mutation])
    console.print(f"[green]✓[/] Decayed [bold]{args.drive}[/] -{args.amount} → next cycle")


_GENOME_FILE = _DEFAULT_STATE_DIR / "genome.json"

# Default genome (mirrors genome.py defaults — used when state file absent)
_DEFAULT_GENOME = {
    "version": "3.0",
    "created_at": 0,
    "modules": {
        "endocrine": {"decay_rates": {"cortisol": -0.05, "dopamine": -0.08, "serotonin": -0.02,
                                      "oxytocin": -0.04, "adrenaline": -0.28, "melatonin": -0.01},
                      "high_threshold": 0.5, "low_threshold": 0.3},
        "limbic":    {"half_life_ms": 14400000, "decay_threshold": 0.5, "contagion_multiplier": 0.5},
        "retina":    {"default_threshold": 0.3, "focus_threshold": 0.8},
        "circadian": {"dawn_hours": [6, 9], "daylight_hours": [9, 17], "golden_hours": [17, 22]},
        "amygdala":  {"fast_path_threshold": 0.7},
        "phenotype": {"default_humor": 0.3, "default_intensity": 0.5},
        "telomere":  {"drift_threshold": 0.3},
        "hypothalamus": {"signal_threshold": 3, "retirement_days": 30, "weight_floor": 0.1},
        "soma":      {"energy_cost_per_token": 0.001, "rem_replenish": 0.5},
    },
}


def _read_genome() -> dict:
    """Read genome from state file, or return default."""
    if _GENOME_FILE.exists():
        try:
            return json.loads(_GENOME_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULT_GENOME.copy()


def _write_genome(g: dict):
    """Write genome to state file."""
    _GENOME_FILE.parent.mkdir(parents=True, exist_ok=True)
    g["created_at"] = int(time.time())
    _GENOME_FILE.write_text(json.dumps(g, indent=2))


def cmd_genome(args):
    """Export, import, diff, or show the Pulse genome (DNA config)."""
    sub = getattr(args, "genome_cmd", None) or "show"

    if sub == "export":
        g = _read_genome()
        if getattr(args, "output", None):
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(g, indent=2))
            console.print(f"[green]✓[/] Genome exported → [bold]{out}[/]")
        else:
            print(json.dumps(g, indent=2))

    elif sub == "import":
        path = Path(args.file)
        if not path.exists():
            console.print(f"[red]✗[/] File not found: {path}")
            sys.exit(1)
        try:
            incoming = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            console.print(f"[red]✗[/] Invalid JSON: {e}")
            sys.exit(1)
        if "modules" not in incoming:
            console.print("[red]✗[/] Invalid genome: missing 'modules' key")
            sys.exit(1)
        _write_genome(incoming)
        n = len(incoming.get("modules", {}))
        console.print(f"[green]✓[/] Genome imported from [bold]{path}[/] — {n} modules")
        console.print(f"  Version: {incoming.get('version', '?')}")
        if _is_running()[0]:
            console.print("  [dim]Note: restart daemon to apply changes: [bold]pulse restart[/][/]")

    elif sub == "diff":
        path = Path(args.file)
        if not path.exists():
            console.print(f"[red]✗[/] File not found: {path}")
            sys.exit(1)
        try:
            other = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            console.print(f"[red]✗[/] Invalid JSON: {e}")
            sys.exit(1)
        current = _read_genome()

        table = Table(title="Genome Diff", box=box.SIMPLE_HEAVY, padding=(0, 1))
        table.add_column("Module", style="cyan")
        table.add_column("Key")
        table.add_column("Current", style="green")
        table.add_column(f"File: {path.name}", style="yellow")

        current_mods = current.get("modules", {})
        other_mods = other.get("modules", {})
        all_modules = set(current_mods) | set(other_mods)
        diffs_found = 0

        for mod in sorted(all_modules):
            cur_cfg = current_mods.get(mod, {})
            oth_cfg = other_mods.get(mod, {})
            all_keys = set(cur_cfg) | set(oth_cfg)
            for key in sorted(all_keys):
                cur_val = cur_cfg.get(key, "[missing]")
                oth_val = oth_cfg.get(key, "[missing]")
                if str(cur_val) != str(oth_val):
                    table.add_row(mod, key, str(cur_val), str(oth_val))
                    diffs_found += 1

        if diffs_found == 0:
            console.print("[green]✓[/] Genomes are identical.")
        else:
            console.print(table)
            console.print(f"\n[yellow]{diffs_found} difference(s)[/]")

    else:  # show
        g = _read_genome()
        modules = g.get("modules", {})
        # If no mutations yet, show defaults for reference
        source = "live mutations"
        if not modules:
            modules = _DEFAULT_GENOME["modules"]
            source = "defaults (no mutations yet)"

        n_modules = len(modules)
        console.print()
        console.print(Panel(
            f"Version: [bold]{g.get('version', '?')}[/]  │  "
            f"Modules: [bold]{n_modules}[/]  │  "
            f"Source: [dim]{source}[/]",
            title="🧬 Pulse Genome",
            border_style="magenta",
        ))

        table = Table(box=box.SIMPLE_HEAVY, padding=(0, 1), show_edge=False)
        table.add_column("Module", style="cyan")
        table.add_column("Key")
        table.add_column("Value", style="green")

        for mod, cfg in sorted(modules.items()):
            if isinstance(cfg, dict):
                for key, val in sorted(cfg.items()):
                    table.add_row(mod, key, str(val))
            else:
                table.add_row(mod, "", str(cfg))

        console.print(table)
        console.print()
        console.print("  [dim]pulse genome export -o backup.json   # save a backup[/]")
        console.print("  [dim]pulse genome import FILE              # restore[/]")
        console.print("  [dim]pulse genome diff FILE                # compare[/]\n")


def cmd_plugin(args):
    """Manage Pulse plugins — list, discover, and inspect loaded plugins."""
    from pulse.src.plugin_registry import PluginRegistry, discover_plugins, _DEFAULT_PLUGIN_DIR

    sub = getattr(args, "plugin_cmd", None) or "list"

    reg = PluginRegistry.get()

    if sub == "discover":
        plugin_dir = Path(args.dir) if getattr(args, "dir", None) else _DEFAULT_PLUGIN_DIR
        n, errors = discover_plugins(registry=reg, plugin_dir=plugin_dir)
        if n > 0:
            console.print(f"[green]✓[/] Discovered and registered {n} plugin(s) from {plugin_dir}")
        else:
            console.print(f"[yellow]○[/] No new plugins found in {plugin_dir}")
        for err in errors:
            console.print(f"  [red]✗[/] {err}")
        return

    if sub == "health":
        health = reg.health_all()
        if not health:
            console.print("[dim]No plugins registered.[/]")
            return
        from rich.table import Table
        table = Table(title="Plugin Health", box=None, show_header=True,
                      header_style="bold dim", padding=(0, 1))
        table.add_column("Name")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Errors")
        for h in health:
            status = "[green]enabled[/]" if h["enabled"] else "[red]disabled[/]"
            table.add_row(h["name"], h["version"], status, str(h["error_count"]))
        console.print(table)
        return

    # Default: list
    if reg.count == 0:
        # Try auto-discovery first
        discover_plugins(registry=reg)

    if reg.count == 0:
        console.print("[dim]No plugins loaded.[/]")
        console.print(f"\n  Install plugins in: [cyan]{_DEFAULT_PLUGIN_DIR}[/]")
        console.print("  File pattern: [cyan]pulse_plugin_*.py[/]")
        console.print("  Class must subclass [cyan]PulsePlugin[/]")
        return

    from rich.table import Table
    table = Table(title=f"Loaded Plugins ({reg.count})", box=None, show_header=True,
                  header_style="bold dim", padding=(0, 1))
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("Status")

    for h in reg.health_all():
        name = h["name"]
        plugin = reg._plugins.get(name)
        desc = (plugin.description[:50] if plugin else "") or "—"
        status = "[green]✓[/]" if h["enabled"] else "[red]✗ disabled[/]"
        table.add_row(name, h["version"], desc, status)

    console.print(table)
    console.print(f"\n  [dim]pulse plugin discover     # scan ~/.pulse/plugins/[/]")
    console.print(f"  [dim]pulse plugin health       # show error counts[/]")


def cmd_config(args):
    """Show current configuration."""
    # Find config file
    candidates = [
        Path("pulse.yaml"),
        Path("~/.pulse/pulse.yaml").expanduser(),
        Path(__file__).parent.parent / "config" / "pulse.yaml",
    ]
    
    config_path = None
    for c in candidates:
        if c.exists():
            config_path = c
            break

    if not config_path:
        console.print("[red]No pulse.yaml found[/]")
        return

    console.print(f"🫀 [bold magenta]Pulse Config[/] — {config_path}\n")
    
    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Pretty print key sections
    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold", min_width=22)
    table.add_column("Value")

    oc = config.get("openclaw", {})
    table.add_row("Webhook", oc.get("webhook_url", "?"))
    table.add_row("Max turns/hr", str(oc.get("max_turns_per_hour", "?")))
    table.add_row("Min cooldown", f"{oc.get('min_trigger_interval', '?')}s")
    table.add_row("", "")

    d = config.get("drives", {})
    table.add_row("Pressure rate", str(d.get("pressure_rate", "?")))
    table.add_row("Trigger threshold", str(d.get("trigger_threshold", "?")))
    table.add_row("Max pressure", str(d.get("max_pressure", "?")))
    table.add_row("Success decay", str(d.get("success_decay", "?")))
    table.add_row("", "")

    ev = config.get("evaluator", {})
    mode = ev.get("mode", "rules")
    table.add_row("Evaluator mode", mode)
    if mode == "model":
        m = ev.get("model", {})
        table.add_row("Model", m.get("model", "?"))
        table.add_row("Model URL", m.get("base_url", "?"))
    table.add_row("", "")

    cats = d.get("categories", {})
    for name, cat in cats.items():
        table.add_row(f"Drive: {name}", f"weight={cat.get('weight', '?')}, source={cat.get('source', '?')}")

    console.print(table)
    console.print()


def cmd_constellation(args):
    """Constellation — manage inter-agent peer registry and aura broadcast.

    Commands:
      list                   List registered peer agents
      register NAME URL      Register a peer agent (e.g. vera http://127.0.0.1:9722)
      deregister NAME        Remove a peer agent from the registry
      broadcast              Push current aura to all peers
      state                  Show own aura + last received aura from each peer
    """
    from pulse.src import aura as aura_module

    sub = getattr(args, "constellation_cmd", None) or "list"

    if sub == "register":
        name = getattr(args, "name", "").lower()
        url = getattr(args, "url", "")
        token = getattr(args, "token", "") or ""
        weight = getattr(args, "weight", None)

        if not name or not url:
            console.print("[red]✗[/] Usage: pulse constellation register NAME URL [--token TOK] [--weight 0.5]")
            return

        peer = aura_module.register_peer(name, url, token=token, weight=weight)
        console.print(f"\n✨ [bold]Constellation[/] — Peer registered\n")
        console.print(f"  Name:    [cyan]{name}[/]")
        console.print(f"  URL:     {peer['url']}")
        console.print(f"  Weight:  {peer['weight']:.2f}  (emotional contagion strength)")
        console.print(f"  Token:   {'[dim]set[/]' if token else '[dim]none[/]'}")
        console.print()
        console.print(f"  [dim]pulse constellation broadcast   # push aura to all peers[/]")
        return

    if sub == "deregister":
        name = getattr(args, "name", "").lower()
        if not name:
            console.print("[red]✗[/] Usage: pulse constellation deregister NAME")
            return
        removed = aura_module.deregister_peer(name)
        if removed:
            console.print(f"[green]✓[/] Removed [cyan]{name}[/] from constellation")
        else:
            console.print(f"[yellow]○[/] [cyan]{name}[/] not found in constellation")
        return

    if sub == "broadcast":
        peers = aura_module.get_peers()
        if not peers:
            console.print("[yellow]○[/] No peers registered. Use [bold]pulse constellation register[/] first.")
            return
        console.print(f"\n✨ [bold]Constellation Broadcast[/] — pushing aura to {len(peers)} peer(s)...\n")
        aura_state = aura_module.emit()
        results = aura_module.broadcast_to_peers(aura_state)
        for peer_name, result in results.items():
            if result["ok"]:
                console.print(f"  [green]✓[/] {peer_name}")
            else:
                console.print(f"  [red]✗[/] {peer_name}: {result['error']}")
        ok_count = sum(1 for r in results.values() if r["ok"])
        console.print(f"\n  Reached {ok_count}/{len(results)} peers.")
        console.print(f"  Mood broadcast: [cyan]{aura_state.get('mood', 'neutral')}[/]  energy: {aura_state.get('energy', 1.0):.2f}")
        return

    if sub == "state":
        state = aura_module.get_constellation_state()
        own = state.get("own", {})
        peers = state.get("peers", {})

        console.print(f"\n✨ [bold]Constellation State[/]\n")
        console.print(f"  [bold cyan]Iris (own)[/]")
        own_aura = own.get("aura", {})
        console.print(f"    mood:    {own_aura.get('mood', 'neutral')}")
        console.print(f"    energy:  {own_aura.get('energy', 1.0):.2f}")
        console.print(f"    focus:   {own_aura.get('focus', 0.5):.2f}")
        console.print(f"    battery: {own_aura.get('social_battery', 0.8):.2f}")

        if not peers:
            console.print(f"\n  [dim]No peers registered.[/]")
            console.print(f"  [dim]pulse constellation register vera http://127.0.0.1:9722[/]")
        else:
            console.print()
            for peer_name, peer_data in peers.items():
                weight = peer_data.get("weight", 0.5)
                last_aura = peer_data.get("aura", {})
                received_at = peer_data.get("received_at")
                last_error = peer_data.get("last_error")

                ts_str = ""
                if received_at:
                    ts_str = f"  [dim](last: {time.strftime('%H:%M:%S', time.localtime(received_at))})[/]"

                console.print(f"  [bold cyan]{peer_name}[/]  weight={weight:.2f}{ts_str}")
                if last_aura:
                    console.print(f"    mood:    {last_aura.get('mood', '—')}")
                    console.print(f"    energy:  {last_aura.get('energy', '—')}")
                else:
                    console.print(f"    [dim]No aura received yet[/]")
                if last_error:
                    console.print(f"    [red]⚠ error: {last_error[:80]}[/]")
        console.print()
        return

    # Default: list
    peers = aura_module.get_peers()
    const_data = aura_module._load_constellation()
    own_name = const_data.get("own_name", "iris")

    console.print(f"\n✨ [bold]Constellation[/]  (this agent: [cyan]{own_name}[/])\n")
    if not peers:
        console.print("  [dim]No peers registered.[/]")
        console.print()
        console.print("  [dim]pulse constellation register vera http://127.0.0.1:9722[/]")
        console.print("  [dim]pulse constellation register mira http://127.0.0.1:9723[/]")
        console.print("  [dim]pulse constellation register sage http://127.0.0.1:9724[/]")
        console.print("  [dim]pulse constellation register lyra http://127.0.0.1:9725[/]")
    else:
        from rich.table import Table
        table = Table(box=None, show_header=True, header_style="bold dim", padding=(0, 1))
        table.add_column("Name")
        table.add_column("URL")
        table.add_column("Weight")
        table.add_column("Last Ping")
        table.add_column("Status")

        for peer_name, peer_data in peers.items():
            url = peer_data.get("url", "")
            weight = peer_data.get("weight", 0.5)
            last_ping = peer_data.get("last_ping")
            last_error = peer_data.get("last_error")
            ping_str = time.strftime("%H:%M:%S", time.localtime(last_ping)) if last_ping else "—"
            status_str = "[green]ok[/]" if last_ping and not last_error else (
                "[red]error[/]" if last_error else "[dim]never[/]"
            )
            table.add_row(
                f"[cyan]{peer_name}[/]", url, f"{weight:.2f}", ping_str, status_str
            )
        console.print(table)
    console.print()
    console.print("  [dim]pulse constellation register NAME URL   # add peer[/]")
    console.print("  [dim]pulse constellation broadcast            # push aura[/]")
    console.print("  [dim]pulse constellation state                # view all auras[/]")


def cmd_prefrontal(args):
    """PREFRONTAL — runtime identity enforcement.

    Commands:
      status      Show compliance health (default)
      scan TEXT   Scan a text snippet for identity drift
      trend       Show last 20 compliance records
    """
    from pulse.src import prefrontal

    sub = getattr(args, "prefrontal_cmd", None) or "status"

    if sub == "scan":
        text = getattr(args, "text", "") or ""
        if not text:
            console.print("[red]✗[/] Provide text to scan: pulse prefrontal scan 'your text here'")
            return
        result = prefrontal.scan_response(text, source="cli")
        score = result["compliance_score"]
        assessment = result["assessment"]
        color = {"clean": "green", "drift_minor": "yellow",
                 "drift_moderate": "orange3", "drift_severe": "red"}.get(assessment, "white")
        console.print(f"\n🧠 [bold]PREFRONTAL Scan[/]\n")
        console.print(f"  Score:      [{color}]{score:.3f}[/]")
        console.print(f"  Assessment: [{color}]{assessment}[/]")
        if result["drift_flags"]:
            console.print(f"\n  [bold]Drift detected:[/]")
            for f in result["drift_flags"]:
                console.print(f"    [red]✗[/] {f['label']}: {f['matches'][:2]}")
        if result["identity_flags"]:
            console.print(f"\n  [bold]Identity markers:[/]")
            for f in result["identity_flags"]:
                console.print(f"    [green]✓[/] {f['label']} (×{f['count']})")
        return

    if sub == "trend":
        trend = prefrontal.get_compliance_trend(n=20)
        if not trend:
            console.print("[dim]No compliance records yet.[/]")
            return
        from rich.table import Table
        table = Table(title="PREFRONTAL Compliance Trend (last 20)", box=None,
                      show_header=True, header_style="bold dim", padding=(0, 1))
        table.add_column("Time")
        table.add_column("Score")
        table.add_column("Assessment")
        table.add_column("Drift")
        for r in trend:
            ts = time.strftime("%H:%M:%S", time.localtime(r["ts"]))
            score = r["score"]
            a = r["assessment"]
            color = {"clean": "green", "drift_minor": "yellow",
                     "drift_moderate": "orange3", "drift_severe": "red"}.get(a, "white")
            drift_labels = ", ".join(r.get("drift_labels", [])) or "—"
            table.add_row(ts, f"[{color}]{score:.3f}[/]", f"[{color}]{a}[/]", drift_labels)
        console.print(table)
        return

    # Default: status
    status = prefrontal.get_status()
    compliance = status["running_compliance"]
    color = "green" if compliance >= 0.85 else "yellow" if compliance >= 0.65 else "red"
    sys_status = status["status"]

    console.print(f"\n🧠 [bold magenta]PREFRONTAL[/] — Identity Enforcement\n")
    console.print(f"  Status:        [{color}]{sys_status}[/]")
    console.print(f"  Compliance:    [{color}]{compliance:.3f}[/] (running EMA)")
    console.print(f"  Recent avg:    {status['recent_avg']:.3f} (last 10 checks)")
    console.print(f"  Checks run:    {status['checks_run']}")
    console.print(f"  Drift events:  {status['drift_events']} ({status['drift_rate']:.1%} drift rate)")
    console.print(f"  Severe drifts: {status['severe_drift_events']}")
    if status["active_correction"]:
        console.print(f"  [bold red]⚠ Active correction mode — last scan detected severe drift[/]")
    if status["last_check"]:
        last = time.strftime("%H:%M:%S", time.localtime(status["last_check"]))
        console.print(f"  Last check:    {last}")
    console.print()
    console.print("  [dim]pulse prefrontal scan 'text'  # scan a snippet[/]")
    console.print("  [dim]pulse prefrontal trend        # compliance history[/]")


def cmd_start(args):
    """Start the daemon."""
    running, pid = _is_running()
    if running:
        console.print(f"[yellow]Already running[/] (pid {pid})")
        return

    if PLIST.exists():
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)],
            capture_output=True,
        )
        time.sleep(2)
        running, pid = _is_running()
        if running:
            console.print(f"[green]✓[/] Pulse started (pid {pid})")
        else:
            console.print("[red]Failed to start[/] — check logs: pulse logs")
    else:
        console.print("[dim]No LaunchAgent installed. Starting in foreground...[/]")
        os.execvp(
            sys.executable,
            [sys.executable, "-m", "pulse.src"],
        )


def cmd_stop(args):
    """Stop the daemon."""
    running, pid = _is_running()
    if not running:
        console.print("[dim]Not running[/]")
        return

    if PLIST.exists():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)],
            capture_output=True,
        )
    else:
        os.kill(pid, signal.SIGTERM)

    # Wait for shutdown
    for _ in range(10):
        time.sleep(0.5)
        r, _ = _is_running()
        if not r:
            console.print("[green]✓[/] Pulse stopped")
            return
    
    console.print("[yellow]Sent stop signal — daemon may still be shutting down[/]")


def cmd_restart(args):
    """Restart the daemon."""
    running, _ = _is_running()
    if running:
        console.print("Stopping...")
        cmd_stop(args)
        time.sleep(1)
    console.print("Starting...")
    cmd_start(args)


def cmd_logs(args):
    """Show recent log lines."""
    log = STDOUT_LOG if STDOUT_LOG.exists() else LOG_FILE
    if not log.exists():
        console.print("[dim]No log file found[/]")
        return

    n = args.count or 30
    try:
        lines = log.read_text().strip().split("\n")
        for line in lines[-n:]:
            # Colorize log levels
            if "[error" in line.lower() or "ERROR" in line:
                console.print(f"[red]{line}[/]", highlight=False)
            elif "[warn" in line.lower() or "WARNING" in line:
                console.print(f"[yellow]{line}[/]", highlight=False)
            elif "TRIGGER" in line or "🫀" in line:
                console.print(f"[magenta]{line}[/]", highlight=False)
            elif "MUTATION" in line or "🧬" in line:
                console.print(f"[cyan]{line}[/]", highlight=False)
            else:
                console.print(line, highlight=False)
    except OSError as e:
        console.print(f"[red]Error reading logs:[/] {e}")


def cmd_help(args):
    """Show all commands with descriptions and usage."""
    console.print()
    console.print("🫀 [bold magenta]Pulse[/] — Autonomous Cognition Engine\n")

    table = Table(box=box.SIMPLE_HEAVY, padding=(0, 2), show_edge=False)
    table.add_column("Command", style="bold cyan", min_width=30)
    table.add_column("Description")

    commands_info = [
        ("", "[bold]Setup[/]"),
        ("pulse init", "Interactive first-run wizard — token, workspace, preset, LaunchAgent"),
        ("", "[bold]Status & Monitoring[/]"),
        ("pulse", "Show status overview (same as pulse status)"),
        ("pulse status", "Daemon health, uptime, drive summary, trigger stats"),
        ("pulse drives", "All drives with pressure bars, weights, and last-addressed times"),
        ("pulse triggers [-n 20]", "Recent trigger history with success/failure and reasons"),
        ("pulse mutations [-n 20]", "Mutation audit log — every self-modification recorded"),
        ("pulse health", "Raw JSON from /health, /status, and /evolution endpoints"),
        ("pulse logs [-n 30]", "Colored log viewer (errors red, triggers magenta, mutations cyan)"),
        ("pulse config", "Show current configuration from pulse.yaml"),
        ("", ""),
        ("", "[bold]Drive Control[/]"),
        ("pulse spike <drive> [amount]", "Spike a drive's pressure (default +0.3). Applied next cycle."),
        ("pulse decay <drive> [amount]", "Decay a drive's pressure (default -0.3). Applied next cycle."),
        ("", ""),
        ("", "[bold]Self-Modification[/]"),
        ("pulse mutate", "Interactive mutation builder — walks you through type, target, value"),
        ("pulse mutate '<json>'", "Submit a mutation as raw JSON. Queued for next cycle (~30s)."),
        ("", "  Types: adjust_weight, adjust_threshold, adjust_rate, adjust_cooldown,"),
        ("", "         adjust_turns_per_hour, add_drive, remove_drive, spike_drive, decay_drive"),
        ("", ""),
        ("", "[bold]Genome (DNA Config)[/]"),
        ("pulse genome", "Show current genome — all module thresholds and weights"),
        ("pulse genome export [-o FILE]", "Export genome to JSON file (or stdout)"),
        ("pulse genome import FILE", "Import genome from a JSON file"),
        ("pulse genome diff FILE", "Compare current genome against a saved file"),
        ("", ""),
        ("", "[bold]Daemon Lifecycle[/]"),
        ("pulse start", "Start daemon via LaunchAgent (or foreground if no plist)"),
        ("pulse stop", "Graceful shutdown (SIGTERM)"),
        ("pulse restart", "Stop + start"),
    ]

    for cmd, desc in commands_info:
        table.add_row(cmd, desc)

    console.print(table)

    console.print("\n[bold]Options:[/]")
    console.print("  --no-color    Disable ANSI colors")
    console.print("  -h, --help    Show this help\n")

    console.print("[bold]Examples:[/]")
    console.print("  pulse spike curiosity 0.5          [dim]# Boost curiosity drive[/]")
    console.print("  pulse decay system 1.0             [dim]# Reduce system pressure[/]")
    console.print('  pulse mutate \'{"type": "add_drive", "name": "art", "weight": 0.6, "reason": "creative exploration"}\'')
    console.print("  pulse triggers -n 5                [dim]# Last 5 triggers[/]")
    console.print("  pulse logs -n 50                   [dim]# Last 50 log lines[/]")
    console.print()

    console.print("[dim]State: ~/.pulse/state/ · Logs: ~/.pulse/logs/ · Config: pulse/config/pulse.yaml[/]")
    console.print("[dim]Health API: http://127.0.0.1:9720 (/health, /status, /evolution, /mutations)[/]")
    console.print()


def cmd_health(args):
    """Raw health check."""
    running, pid = _is_running()
    if not running:
        console.print("[red]Pulse is not running[/]")
        return

    for endpoint in ["/health", "/status", "/evolution"]:
        data = _get(endpoint)
        if data:
            console.print(f"\n[bold]{endpoint}[/]")
            console.print(json.dumps(data, indent=2, default=str))
        else:
            console.print(f"\n[red]{endpoint}: unreachable[/]")


# ─── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="pulse",
        description="🫀 Pulse — Autonomous Cognition Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colors")
    
    sub = parser.add_subparsers(dest="command")

    # status (default)
    sub.add_parser("init",   help="Interactive setup wizard — first-time configuration")
    sub.add_parser("status", help="Show status overview")

    # drives
    sub.add_parser("drives", help="Show all drives with pressure bars")

    # triggers
    p = sub.add_parser("triggers", help="Recent trigger history")
    p.add_argument("-n", "--count", type=int, default=20, help="Number of entries")

    # mutations
    p = sub.add_parser("mutations", help="Mutation audit log")
    p.add_argument("-n", "--count", type=int, default=20, help="Number of entries")

    # mutate
    p = sub.add_parser("mutate", help="Submit a mutation")
    p.add_argument("json_str", nargs="?", help="Mutation as JSON string")

    # spike
    p = sub.add_parser("spike", help="Spike a drive's pressure")
    p.add_argument("drive", help="Drive name")
    p.add_argument("amount", type=float, nargs="?", default=0.3, help="Spike amount")

    # decay
    p = sub.add_parser("decay", help="Decay a drive's pressure")
    p.add_argument("drive", help="Drive name")
    p.add_argument("amount", type=float, nargs="?", default=0.3, help="Decay amount")

    # config
    sub.add_parser("config", help="Show current configuration")

    # start/stop/restart
    sub.add_parser("start", help="Start the daemon")
    sub.add_parser("stop", help="Stop the daemon")
    sub.add_parser("restart", help="Restart the daemon")

    # logs
    p = sub.add_parser("logs", help="Show recent log lines")
    p.add_argument("-n", "--count", type=int, default=30, help="Number of lines")

    # health
    sub.add_parser("health", help="Raw health/status/evolution endpoints")

    # genome — DNA export/import/diff
    g_parser = sub.add_parser("genome", help="Export, import, or diff the Pulse genome (DNA config)")
    g_sub = g_parser.add_subparsers(dest="genome_cmd")
    g_export = g_sub.add_parser("export", help="Export current genome to JSON")
    g_export.add_argument("--output", "-o", metavar="FILE", help="Output file (default: stdout)")
    g_import = g_sub.add_parser("import", help="Import genome from a JSON file")
    g_import.add_argument("file", metavar="FILE", help="Path to genome JSON")
    g_diff = g_sub.add_parser("diff", help="Compare current genome against a saved file")
    g_diff.add_argument("file", metavar="FILE", help="Path to genome JSON to compare against")
    g_sub.add_parser("show", help="Show current genome (default if no subcommand)")

    # plugin
    p_parser = sub.add_parser("plugin", help="Manage community plugins")
    p_sub = p_parser.add_subparsers(dest="plugin_cmd")
    p_sub.add_parser("list", help="List loaded plugins (default)")
    p_discover = p_sub.add_parser("discover", help="Scan plugin dir and load new plugins")
    p_discover.add_argument("--dir", metavar="DIR", help="Plugin directory to scan (default: ~/.pulse/plugins/)")
    p_sub.add_parser("health", help="Show plugin health + error counts")

    # constellation — inter-agent peer registry
    cn_parser = sub.add_parser("constellation", help="Manage inter-agent peer registry and aura broadcast")
    cn_sub = cn_parser.add_subparsers(dest="constellation_cmd")
    cn_sub.add_parser("list", help="List registered peer agents (default)")
    cn_register = cn_sub.add_parser("register", help="Register a peer agent")
    cn_register.add_argument("name", metavar="NAME", help="Agent name (e.g. vera, mira, sage, lyra)")
    cn_register.add_argument("url", metavar="URL", help="Base URL for the peer's Pulse API (e.g. http://127.0.0.1:9722)")
    cn_register.add_argument("--token", metavar="TOKEN", default="", help="Bearer token for the peer's API")
    cn_register.add_argument("--weight", type=float, metavar="WEIGHT", default=None, help="Emotional contagion weight (0.0–1.0)")
    cn_deregister = cn_sub.add_parser("deregister", help="Remove a peer agent from the registry")
    cn_deregister.add_argument("name", metavar="NAME", help="Agent name to remove")
    cn_sub.add_parser("broadcast", help="Push current aura to all registered peers")
    cn_sub.add_parser("state", help="Show own aura + last received aura from each peer")

    # prefrontal
    se_parser = sub.add_parser("prefrontal", help="Runtime identity enforcement — compliance tracking")
    se_sub = se_parser.add_subparsers(dest="prefrontal_cmd")
    se_sub.add_parser("status", help="Show compliance health (default)")
    se_scan = se_sub.add_parser("scan", help="Scan a text snippet for identity drift")
    se_scan.add_argument("text", metavar="TEXT", help="Text to scan")
    se_sub.add_parser("trend", help="Show last 20 compliance records")

    # help
    sub.add_parser("help", help="Show all commands with usage and descriptions")

    args = parser.parse_args()

    if args.no_color:
        console.no_color = True

    cmd = args.command or "status"

    commands = {
        "init":   cmd_init,
        "status": cmd_status,
        "drives": cmd_drives,
        "triggers": cmd_triggers,
        "mutations": cmd_mutations,
        "mutate": cmd_mutate,
        "spike": cmd_spike,
        "decay": cmd_decay,
        "config": cmd_config,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "logs": cmd_logs,
        "health": cmd_health,
        "genome": cmd_genome,
        "plugin": cmd_plugin,
        "constellation": cmd_constellation,
        "prefrontal": cmd_prefrontal,
        "help": cmd_help,
    }

    fn = commands.get(cmd)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
