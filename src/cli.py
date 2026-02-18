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
STATE_DIR = Path("~/.pulse/state").expanduser()
LOG_FILE = Path("~/.pulse/logs/pulse.log").expanduser()
STDOUT_LOG = Path("~/.pulse/logs/pulse-stdout.log").expanduser()
PID_FILE = Path("~/.pulse/pulse.pid").expanduser()
MUTATIONS_FILE = STATE_DIR / "mutations.json"
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
        table.add_row("State", str(STATE_DIR))
        table.add_row("Logs", str(STDOUT_LOG))
    else:
        table.add_row("Status", "[red bold]● stopped[/]")
        table.add_row("Service", "LaunchAgent" if PLIST.exists() else "[dim]not installed[/]")
        table.add_row("State", str(STATE_DIR))
        if STATE_DIR.exists():
            state_file = STATE_DIR / "pulse-state.json"
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
        state_file = STATE_DIR / "pulse-state.json"
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
    history_file = STATE_DIR / "trigger-history.jsonl"
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
    log_file = STATE_DIR / "mutations.jsonl"
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

    # help
    sub.add_parser("help", help="Show all commands with usage and descriptions")

    args = parser.parse_args()

    if args.no_color:
        console.no_color = True

    cmd = args.command or "status"

    commands = {
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
        "help": cmd_help,
    }

    fn = commands.get(cmd)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
