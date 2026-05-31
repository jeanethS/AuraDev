"""
auradev - Ambient Music Engine for Developers

Samples developer behavioral telemetry, classifies cognitive state via Claude,
and plays procedurally generated music matching that state.

Usage:
    python main.py          # Normal mode with Claude classification
    python main.py --demo   # Demo mode (cycles through states, no Claude)
"""

import argparse
import getpass
import os
import signal
import sys
import threading
import time
import uuid
from typing import Dict, Any, Optional

from collector import TelemetryCollector
from classifier import CognitiveClassifier
import lyria
from logger import SessionLogger
from database import init_db, get_db_path
from config import SAMPLE_INTERVAL, STATES, API_PORT, LYRIA_PROJECT_ID

try:
    import api as api_module
    import uvicorn
except ImportError:
    api_module = None
    uvicorn = None


class auradev:
    def __init__(
        self,
        demo_mode: bool = False,
        max_cycles: Optional[int] = None,
        sample_interval: Optional[int] = None,
        collector=None,
        classifier=None,
        audio_engine=None,
        logger=None,
    ):
        self.demo_mode = demo_mode
        self.running = False
        self._stopped = False
        self.demo_state_index = 0
        self.cycle_count = 0

        # Allow overriding interval for tests
        self.sample_interval = sample_interval if sample_interval is not None else SAMPLE_INTERVAL

        # Demo mode defaults to 3 cycles, normal mode runs until interrupted
        if max_cycles is not None:
            self.max_cycles = max_cycles
        else:
            self.max_cycles = 3 if demo_mode else None

        # Detect user_id from USER_ID env or system username
        self.user_id = os.getenv("USER_ID")
        if self.user_id is None:
            try:
                self.user_id = getpass.getuser()
            except Exception:
                self.user_id = "default"

        # Session identity and persistence
        self.session_id = str(uuid.uuid4())
        init_db(self.user_id)
        
        # Get and display database path
        self.db_path = get_db_path(self.user_id)
        print(f"User: {self.user_id}")
        print(f"Database: {self.db_path}")

        # Initialize components (allow injection for testing)
        self.collector = collector if collector is not None else TelemetryCollector()
        self.audio_engine = audio_engine if audio_engine is not None else None
        self.logger = logger if logger is not None else SessionLogger(
            session_id=self.session_id, 
            user_id=self.user_id
        )

        # Initialize Lyria when no audio engine is injected
        if self.audio_engine is None:
            lyria.init_lyria(LYRIA_PROJECT_ID)

        # Only initialize classifier in normal mode
        if not demo_mode:
            try:
                self.classifier = classifier if classifier is not None else CognitiveClassifier()
            except ValueError as e:
                print(f"Error: {e}")
                print("Please set ANTHROPIC_API_KEY environment variable or use --demo mode")
                sys.exit(1)
        else:
            self.classifier = None
            print("Running in demo mode - no Claude API calls")

        # Set up signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)

        # Start API server in background
        self._start_api_server()

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        print("\nShutting down auradev...")
        self.running = False

    def _start_api_server(self) -> None:
        """Start FastAPI in a background daemon thread."""
        if api_module is None or uvicorn is None:
            print("Warning: fastapi or uvicorn not installed. Skipping API server.")
            return
        api_module.app.state.session_id = self.session_id
        config = uvicorn.Config(api_module.app, host="0.0.0.0", port=API_PORT, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        print(f"API server running at http://localhost:{API_PORT}")

    def start(self):
        """Start the main application loop."""
        self.running = True

        print("auradev starting...")
        print("Press Ctrl+C to stop")

        # Start telemetry collection
        if not self.demo_mode:
            self.collector.start_listeners()

        try:
            self._main_loop()
        except Exception as e:
            print(f"Error in main loop: {e}")
        finally:
            self.stop()

    def _main_loop(self):
        """Main application loop - collect, classify, play, log."""
        while self.running:
            try:
                # Collect telemetry metrics
                if self.demo_mode:
                    metrics = self._get_demo_metrics()
                else:
                    metrics = self.collector.collect_metrics()

                # Classify cognitive state
                if self.demo_mode:
                    classification = self._get_demo_classification()
                else:
                    classification = self.classifier.classify_state(metrics)

                # Update audio
                if self.audio_engine is not None:
                    self.audio_engine.play_state(classification["state"])
                else:
                    lyria.play_state(classification["state"])

                # Log the cycle
                self.logger.log_cycle(metrics, classification)

                # Prefetch remaining states after first classification
                if self.audio_engine is None and self.cycle_count == 0:
                    lyria.prefetch_next(classification["state"])

                self.cycle_count += 1

                # Stop if we've reached max cycles (demo mode)
                if self.max_cycles is not None and self.cycle_count >= self.max_cycles:
                    print(f"\nDemo complete after {self.cycle_count} cycles.")
                    self.running = False
                    break

                # Wait for next sample
                self._interruptible_sleep(self.sample_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error in cycle: {e}")
                # Continue running despite errors
                self._interruptible_sleep(self.sample_interval)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in short chunks so Ctrl+C can stop without racing cleanup."""
        end = time.time() + seconds
        while self.running and time.time() < end:
            time.sleep(min(0.5, max(0.0, end - time.time())))

    def _get_demo_metrics(self) -> Dict[str, Any]:
        """Generate fake metrics for demo mode."""
        import random

        # Cycle through different metric patterns
        patterns = [
            # Flow pattern
            {
                "wpm": random.uniform(40, 60),
                "backspace_ratio": random.uniform(0.05, 0.15),
                "window_switches": random.randint(0, 1),
                "mouse_distance": random.uniform(100, 300),
                "cpu_percent": random.uniform(20, 40),
                "idle_seconds": random.uniform(0, 5),
            },
            # Stuck pattern
            {
                "wpm": random.uniform(5, 15),
                "backspace_ratio": random.uniform(0.3, 0.5),
                "window_switches": random.randint(0, 2),
                "mouse_distance": random.uniform(50, 150),
                "cpu_percent": random.uniform(10, 25),
                "idle_seconds": random.uniform(10, 30),
            },
            # Debugging pattern
            {
                "wpm": random.uniform(20, 35),
                "backspace_ratio": random.uniform(0.15, 0.25),
                "window_switches": random.randint(2, 4),
                "mouse_distance": random.uniform(200, 500),
                "cpu_percent": random.uniform(30, 60),
                "idle_seconds": random.uniform(2, 8),
            },
        ]

        pattern = patterns[self.demo_state_index % len(patterns)]
        pattern["active_window"] = "Demo Application"
        return pattern

    def _get_demo_classification(self) -> Dict[str, Any]:
        """Generate demo classification results."""
        states_cycle = ["flow", "stuck", "debugging", "reviewing", "context_switching"]
        current_state = states_cycle[self.demo_state_index % len(states_cycle)]

        # Advance to next state after each classification
        self.demo_state_index += 1

        return {
            "state": current_state,
            "confidence": 0.85,
            "reason": f"Demo mode cycling through {current_state} state"
        }

    def stop(self):
        """Stop the application and cleanup resources."""
        if self._stopped:
            return
        self._stopped = True
        self.running = False

        # Stop telemetry collection
        if hasattr(self, 'collector') and self.collector is not None:
            self.collector.stop_listeners()

        # Stop audio
        if hasattr(self, 'audio_engine') and self.audio_engine is not None:
            if hasattr(self.audio_engine, 'cleanup'):
                self.audio_engine.cleanup()
            elif hasattr(self.audio_engine, 'stop'):
                self.audio_engine.stop()
        else:
            lyria.stop()

        # Print session summary
        if hasattr(self, 'logger') and self.logger is not None:
            self.logger.print_session_summary()

        print("auradev stopped.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="auradev - Ambient Music Engine for Developers")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode (no telemetry collection or Claude API calls)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Sample interval in seconds (default: 30, demo: 5)"
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Maximum number of cycles to run (default: unlimited, demo: 3)"
    )
    parser.add_argument(
        "--no-drums",
        action="store_true",
        help="Disable drum beats (melody only)"
    )
    parser.add_argument(
        "--drum-volume",
        type=float,
        default=0.4,
        help="Drum volume relative to melody (0.0-1.0, default: 0.4)"
    )

    args = parser.parse_args()

    # Set default intervals
    interval = args.interval
    if interval is None:
        interval = 5 if args.demo else SAMPLE_INTERVAL

    app = auradev(
        demo_mode=args.demo,
        sample_interval=interval,
        max_cycles=args.max_cycles
    )
    
    # Configure audio
    if hasattr(app.audio_engine, 'set_drums_enabled'):
        app.audio_engine.set_drums_enabled(not args.no_drums)
    if hasattr(app.audio_engine, 'set_drum_volume'):
        app.audio_engine.set_drum_volume(args.drum_volume)
    
    app.start()


if __name__ == "__main__":
    main()
