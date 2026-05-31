"""
Claude Classifier Module for auradev

Sends telemetry data to Claude API for cognitive state classification.
Handles API calls, response validation, and fallback behavior.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, CLASSIFIER_MODEL, STATES

_CACHE_CONFIDENCE_THRESHOLD = 0.70


class CognitiveClassifier:
    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.last_state = None
        self._last_fingerprint: Optional[Tuple] = None
        self._last_result: Optional[Dict[str, Any]] = None

        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self.logger = logging.getLogger(__name__)
        
        self.system_prompt = """You are analyzing developer behavioral telemetry to classify cognitive state.

Respond ONLY with valid JSON in this exact format:
{
    "state": "<one of: flow, stuck, debugging, reviewing, context_switching>",
    "confidence": <float between 0.0 and 1.0>,
    "reason": "<one sentence explanation>"
}

State definitions:
- flow: Steady, productive typing with minimal interruptions
- stuck: Low typing, high backspace ratio, or long idle periods
- debugging: Variable typing patterns, moderate window switching
- reviewing: Low typing, stable window, minimal backspaces
- context_switching: High window switching, erratic mouse movement

Base your decision on the telemetry patterns, not just individual metrics."""

    def _metrics_fingerprint(self, metrics: Dict[str, Any]) -> Tuple:
        """Bucket continuous metrics so near-identical telemetry produces the same key."""
        return (
            int(metrics.get("wpm", 0) // 5) * 5,
            round(metrics.get("backspace_ratio", 0), 1),
            min(int(metrics.get("window_switches", 0)), 10),
            int(metrics.get("idle_seconds", 0) // 30) * 30,
            int(metrics.get("cpu_percent", 0) // 10) * 10,
        )

    def classify_state(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a cached result when metrics fingerprint matches the last call
        and that call returned high confidence, otherwise call the Anthropic API.
        """
        fingerprint = self._metrics_fingerprint(metrics)
        if (
            self._last_fingerprint == fingerprint
            and self._last_result is not None
            and self._last_result.get("confidence", 0) >= _CACHE_CONFIDENCE_THRESHOLD
        ):
            self.logger.info("Classifier cache hit — skipping API call")
            return self._last_result

        try:
            telemetry_json = json.dumps(metrics, indent=2)

            response = self.client.messages.create(
                model=CLASSIFIER_MODEL,
                max_tokens=100,
                system=self.system_prompt,
                messages=[
                    {
                        "role": "user", 
                        "content": f"Classify this developer telemetry:\\n\\n{telemetry_json}"
                    }
                ]
            )
            
            response_text = response.content[0].text.strip()
            result = json.loads(response_text)

            if self._validate_response(result):
                self.last_state = result["state"]
                self._last_fingerprint = fingerprint
                self._last_result = result
                return result
            else:
                self.logger.error(f"Invalid response format: {result}")
                return self._get_fallback_state("Invalid response format")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            return self._get_fallback_state(f"JSON decode error: {e}")
        except Exception as e:
            self.logger.error(f"Classification API error: {e}")
            return self._get_fallback_state(f"API error: {e}")
    
    def _validate_response(self, result: Dict) -> bool:
        """Validate the Claude response has required fields and valid values."""
        if not isinstance(result, dict):
            return False
        
        # Check required fields
        if "state" not in result or "confidence" not in result or "reason" not in result:
            return False
        
        # Validate state
        if result["state"] not in STATES:
            return False
        
        # Validate confidence
        try:
            confidence = float(result["confidence"])
            if not (0.0 <= confidence <= 1.0):
                return False
        except (ValueError, TypeError):
            return False
        
        # Validate reason is a string
        if not isinstance(result["reason"], str) or not result["reason"].strip():
            return False
        
        return True
    
    def _get_fallback_state(self, error_reason: str) -> Dict[str, Any]:
        """Return fallback state when classification fails."""
        fallback_state = self.last_state if self.last_state else "reviewing"
        
        return {
            "state": fallback_state,
            "confidence": 0.5,
            "reason": f"Fallback due to error: {error_reason}"
        }