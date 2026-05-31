"""
Session Logger Module for auradev

Handles terminal output with ANSI colors, ASCII visuals, and file logging.
Tracks session statistics and generates final summaries.
"""

import getpass
import math
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List
from config import LOG_FILE, SYNC_URL
from database import save_cycle

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class SessionLogger:
    def __init__(self, session_id: str = None, user_id: str = None):
        self.session_id = session_id if session_id is not None else str(uuid.uuid4())
        
        # Auto-detect user_id from USER_ID env or system username
        if user_id is None:
            user_id = os.getenv("USER_ID")
            if user_id is None:
                try:
                    user_id = getpass.getuser()
                except Exception:
                    user_id = "default"
        
        self.user_id = user_id
        self.session_entries: List[Dict[str, Any]] = []
        self.session_start_time = time.time()

        # ANSI truecolor template aligned with dashboard palette.
        self.state_colors = {
            "flow": self._ansi_hex("#b2c5ff"),
            "stuck": self._ansi_hex("#ffdad6"),
            "debugging": self._ansi_hex("#dae2ff"),
            "reviewing": self._ansi_hex("#fbd7fd"),
            "context_switching": self._ansi_hex("#e8dff0"),
        }
        self.primary_color = self._ansi_hex("#2c375c")
        self.navy_color = self._ansi_hex("#434e74")
        self.mauve_color = self._ansi_hex("#ae8fb1")
        self.text_color = self._ansi_hex("#f7edff")
        self.muted_color = self._ansi_hex("#bac5f2")
        self.rule_color = self._ansi_hex("#434e74")
        self.status_colors = {
            "ok": self._ansi_hex("#b2c5ff"),
            "warn": self._ansi_hex("#fbd7fd"),
            "error": self._ansi_hex("#ffdad6"),
            "offline": self._ansi_hex("#76767f"),
        }
        self.reset_color = "\033[0m"
        self.bold = "\033[1m"
        self.dim = "\033[2m"

        # State-specific ASCII icons
        self.state_icons = {
            "flow": "~[O]~",
            "stuck": "[???]",
            "debugging": "[:*:]",
            "reviewing": "(o_o)",
            "context_switching": "<==>",
        }

        # Spectrum characters for waveform visualizer
        self.spectrum_chars = " ▁▂▃▄▅▆▇█"

        # Clear/create log file
        with open(LOG_FILE, "w") as f:
            f.write(f"auradev Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        self._print_logo()

    def _print_logo(self):
        """Print a fancy ASCII startup banner."""
        logo = (
            f"\n"
            f"{self.primary_color}{self.bold}╔══════════════════════════════════════════════════════════╗{self.reset_color}\n"
            f"{self.primary_color}{self.bold}║{self.reset_color}                                                          {self.primary_color}{self.bold}║{self.reset_color}\n"
            f"{self.primary_color}{self.bold}║{self.reset_color}      {self.mauve_color}♪    ∿  A U R A D E V  ∿    ♪{self.reset_color}                       {self.primary_color}{self.bold}║{self.reset_color}\n"
            f"{self.primary_color}{self.bold}║{self.reset_color}                                                          {self.primary_color}{self.bold}║{self.reset_color}\n"
            f"{self.primary_color}{self.bold}║{self.reset_color}      {self.navy_color}Ambient Music Engine for Developers{self.reset_color}                 {self.primary_color}{self.bold}║{self.reset_color}\n"
            f"{self.primary_color}{self.bold}║{self.reset_color}                                                          {self.primary_color}{self.bold}║{self.reset_color}\n"
            f"{self.primary_color}{self.bold}╚══════════════════════════════════════════════════════════╝{self.reset_color}\n"
        )
        print(logo)

    @staticmethod
    def _ansi_hex(hex_color: str) -> str:
        """Return a 24-bit ANSI foreground color sequence from #RRGGBB."""
        cleaned = hex_color.lstrip("#")
        if len(cleaned) != 6:
            return ""
        r = int(cleaned[0:2], 16)
        g = int(cleaned[2:4], 16)
        b = int(cleaned[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"

    def _generate_waveform(self, state: str, width: int = 52) -> str:
        """Generate a pseudo-spectrum waveform based on cognitive state."""
        chars = self.spectrum_chars
        wave = []
        seed = hash(state) % 10000
        rng = random.Random(seed)

        for i in range(width):
            if state == "flow":
                val = 0.5 + 0.4 * math.sin(i * 0.35 + seed * 0.01)
            elif state == "stuck":
                val = 0.2 + 0.5 * abs(math.sin(i * 1.2 + seed * 0.1)) * (0.5 + 0.5 * math.cos(i * 3.7))
            elif state == "debugging":
                spike = max(0, math.sin(i * 0.6 + seed) * math.cos(i * 2.1))
                val = 0.15 + 0.7 * spike
            elif state == "reviewing":
                val = 0.25 + 0.15 * math.sin(i * 0.12 + seed)
            else:  # context_switching
                val = 0.3 + 0.4 * abs(math.sin(i * 0.45 + seed)) * ((i % 3) / 2.0 + 0.2)

            idx = max(0, min(len(chars) - 1, int(val * (len(chars) - 1))))
            wave.append(chars[idx])

        return "".join(wave)

    def _progress_bar(self, value: float, max_val: float, width: int = 20) -> str:
        """Create a Unicode block progress bar."""
        if max_val <= 0:
            return "░" * width
        filled = int((min(value, max_val) / max_val) * width)
        filled = max(0, min(filled, width))
        return "█" * filled + "░" * (width - filled)

    def _pulse_color(self, state: str, confidence: float) -> str:
        """Return a color with optional bold pulse for high confidence."""
        base = self.state_colors.get(state, "")
        if confidence > 0.85:
            return base + self.bold
        return base

    def _rule(self, char: str = "═", width: int = 60) -> str:
        """Render a palette-colored divider line."""
        return f"{self.rule_color}{char * width}{self.reset_color}"

    def log_cycle(self, metrics: Dict[str, Any], classification: Dict[str, Any]):
        """Log a single collection cycle to terminal and file."""
        timestamp = datetime.now()

        # Create entry
        entry = {
            "timestamp": timestamp,
            "metrics": metrics.copy(),
            "classification": classification.copy(),
        }
        self.session_entries.append(entry)

        # Terminal output with rich visuals
        state = classification["state"]
        confidence = classification["confidence"]
        reason = classification["reason"]

        color = self._pulse_color(state, confidence)
        icon = self.state_icons.get(state, "◆")

        print(f"\n{self._rule('═')}")
        print(
            f" {self.mauve_color}{icon}{self.reset_color}  "
            f"{color}{state.upper()}{self.reset_color}  "
            f"{self.muted_color}confidence:{self.reset_color} "
            f"{color}{confidence:.0%}{self.reset_color}"
        )
        print(
            f" {' '*4}{self.muted_color}∿{self.reset_color} "
            f"{self.navy_color}{self._generate_waveform(state)}{self.reset_color} "
            f"{self.muted_color}∿{self.reset_color}"
        )
        print(f" {' '*4}{self.muted_color}→{self.reset_color} {self.text_color}{reason}{self.reset_color}")
        print(self._rule("─"))
        print(
            f"  {self.primary_color}WPM{self.reset_color}        "
            f"{self.navy_color}{self._progress_bar(metrics['wpm'], 120)}{self.reset_color} "
            f"{self.text_color}{metrics['wpm']:>6.1f}{self.reset_color}"
        )
        print(
            f"  {self.primary_color}Backspace{self.reset_color}  "
            f"{self.navy_color}{self._progress_bar(metrics['backspace_ratio'] * 100, 50)}{self.reset_color} "
            f"{self.text_color}{metrics['backspace_ratio']:>6.2f}{self.reset_color}"
        )
        print(
            f"  {self.primary_color}CPU{self.reset_color}        "
            f"{self.navy_color}{self._progress_bar(metrics['cpu_percent'], 100)}{self.reset_color} "
            f"{self.text_color}{metrics['cpu_percent']:>6.1f}%{self.reset_color}"
        )
        print(
            f"  {self.primary_color}Idle{self.reset_color}       "
            f"{self.navy_color}{self._progress_bar(metrics['idle_seconds'], 60)}{self.reset_color} "
            f"{self.text_color}{metrics['idle_seconds']:>6.1f}s{self.reset_color}"
        )
        print(
            f"  {self.primary_color}Switches{self.reset_color}   "
            f"{self.navy_color}{self._progress_bar(metrics['window_switches'], 20)}{self.reset_color} "
            f"{self.text_color}{metrics['window_switches']:>6}{self.reset_color}"
        )
        print(
            f"  {self.primary_color}Window{self.reset_color}     "
            f"{self.text_color}{metrics['active_window'][:42]}{self.reset_color}"
        )
        print(self._rule("═"))

        # File logging (unchanged format)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {state.upper()} "
                   f"(confidence: {confidence:.2f})\n")
            f.write(f"  Metrics: WPM={metrics['wpm']:.1f}, "
                   f"Backspace={metrics['backspace_ratio']:.2f}, "
                   f"Mouse={metrics['mouse_distance']:.1f}, "
                   f"CPU={metrics['cpu_percent']:.1f}%, "
                   f"Idle={metrics['idle_seconds']:.1f}s, "
                   f"Switches={metrics['window_switches']}\n")
            f.write(f"  Window: {metrics['active_window']}\n")
            f.write(f"  Reason: {reason}\n\n")

        # Persist to SQLite
        try:
            save_cycle(self.session_id, metrics, classification, self.user_id)
        except Exception as e:
            print(
                f"{self.status_colors['warn']}{self.bold}Warning:{self.reset_color} "
                f"{self.text_color}failed to save cycle to DB: {e}{self.reset_color}",
                file=sys.stderr,
            )

        # Sync to cloud API
        self._sync_to_cloud(metrics, classification)

    def _sync_to_cloud(self, metrics: Dict[str, Any], classification: Dict[str, Any]):
        """Send cycle data to cloud API for dashboard sync."""
        if not HAS_REQUESTS or not SYNC_URL:
            return
        
        try:
            payload = {
                "session_id": self.session_id,
                "state": classification.get("state", "reviewing"),
                "confidence": classification.get("confidence", 0.0),
                "reason": classification.get("reason", ""),
                "wpm": metrics.get("wpm", 0.0),
                "backspace_ratio": metrics.get("backspace_ratio", 0.0),
                "window_switches": metrics.get("window_switches", 0),
                "mouse_distance": metrics.get("mouse_distance", 0.0),
                "cpu_percent": metrics.get("cpu_percent", 0.0),
                "idle_seconds": metrics.get("idle_seconds", 0.0),
                "active_window": metrics.get("active_window", ""),
            }
            resp = requests.post(SYNC_URL, json=payload, timeout=5)
            if resp.status_code == 200:
                print(
                    f"  {self.status_colors['ok']}☁ synced to cloud{self.reset_color} "
                    f"{self.dim}{self.muted_color}(dashboard live){self.reset_color}"
                )
            else:
                print(
                    f"  {self.status_colors['error']}☁ sync failed: {resp.status_code}{self.reset_color}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"  {self.status_colors['error']}☁ sync error: {e}{self.reset_color}", file=sys.stderr)

    def print_session_summary(self):
        """Print final session statistics and save to file."""
        if not self.session_entries:
            print(f"{self.muted_color}No session data to summarize.{self.reset_color}")
            return

        session_duration = time.time() - self.session_start_time
        total_cycles = len(self.session_entries)

        # Calculate state percentages
        state_counts = {}
        for entry in self.session_entries:
            state = entry["classification"]["state"]
            state_counts[state] = state_counts.get(state, 0) + 1

        state_percentages = {
            state: (count / total_cycles) * 100
            for state, count in state_counts.items()
        }

        # Find longest continuous flow window
        flow_windows = self._find_flow_windows()
        longest_flow = max(flow_windows, key=len) if flow_windows else []

        # Format summary
        print(f"\n{self.rule_color}{'╔' + '═'*58 + '╗'}{self.reset_color}")
        print(
            f"{self.rule_color}║{self.reset_color}"
            f"{self.primary_color}{self.bold}{' '*20 + 'SESSION SUMMARY' + ' '*23}{self.reset_color}"
            f"{self.rule_color}║{self.reset_color}"
        )
        print(f"{self.rule_color}{'╠' + '═'*58 + '╣'}{self.reset_color}")
        print(
            f"  {self.primary_color}Duration:{self.reset_color}    "
            f"{self.text_color}{timedelta(seconds=int(session_duration))}{self.reset_color}"
        )
        print(
            f"  {self.primary_color}Total cycles:{self.reset_color} "
            f"{self.text_color}{total_cycles}{self.reset_color}"
        )
        print(self._rule("─"))
        print(f"  {self.muted_color}State Distribution:{self.reset_color}")

        for state in ["flow", "stuck", "debugging", "reviewing", "context_switching"]:
            if state in state_percentages:
                color = self.state_colors[state]
                percentage = state_percentages[state]
                bar_length = int(percentage / 5)  # Scale to 20 chars max
                bar = "█" * bar_length + "░" * (20 - bar_length)
                print(f"  {color}{state.ljust(16)}{self.reset_color} {bar} {percentage:5.1f}%")

        if longest_flow:
            flow_start = longest_flow[0]["timestamp"].strftime('%H:%M:%S')
            flow_duration = len(longest_flow) * 30  # 30 second intervals
            print(self._rule("─"))
            print(
                f"  {self.mauve_color}✦ Longest Flow Window:{self.reset_color} "
                f"{self.text_color}{flow_duration}s starting at {flow_start}{self.reset_color}"
            )

        print(f"{self.rule_color}{'╚' + '═'*58 + '╝'}{self.reset_color}")

        # Save summary to file
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n" + "="*60 + "\n")
            f.write("SESSION SUMMARY\n")
            f.write("="*60 + "\n")
            f.write(f"Duration: {timedelta(seconds=int(session_duration))}\n")
            f.write(f"Total cycles: {total_cycles}\n\n")
            f.write("State Distribution:\n")

            for state, percentage in state_percentages.items():
                f.write(f"  {state.ljust(16)}: {percentage:5.1f}%\n")

            if longest_flow:
                flow_start = longest_flow[0]["timestamp"].strftime('%H:%M:%S')
                flow_duration = len(longest_flow) * 30
                f.write(f"\nLongest Flow Window: {flow_duration}s starting at {flow_start}\n")

    def _find_flow_windows(self) -> List[List[Dict[str, Any]]]:
        """Find all continuous flow state windows."""
        windows = []
        current_window = []

        for entry in self.session_entries:
            if entry["classification"]["state"] == "flow":
                current_window.append(entry)
            else:
                if current_window:
                    windows.append(current_window)
                    current_window = []

        # Add final window if it ends in flow
        if current_window:
            windows.append(current_window)

        return windows
