"""
scaler.py
---------
Scaling decision engine — translates a predicted RPS into a target replica count.

This module contains zero I/O. It is a pure function from
(predicted_rps, current_pods, timestamp) → target_pods.

Keeping I/O out makes the decision logic trivially unit-testable.
The Kubernetes patch call lives in k8s_client.py.

Decision rules:
  1. Scale UP:   Immediately when pods_required > current_pods.
                 No cooldown — under-provisioning is always worse than
                 a transient extra pod.

  2. Scale DOWN: Only when:
                   predicted_rps < current_capacity * SCALE_DOWN_THRESHOLD
                   AND the cooldown window has elapsed since the last scale-down.

  3. Bounds:     Target is always clamped to [min_pods, max_pods].

ScaleDecision dataclass:
  Carries the target AND the reason string so the caller can log a
  human-readable explanation for every decision (or non-decision).
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from autoscaler.config import Config

logger = logging.getLogger(__name__)


@dataclass
class ScaleDecision:
    target_pods: int
    """The replica count we want to reach."""

    should_scale: bool
    """True if target_pods != current_pods and the action is approved."""

    reason: str
    """Human-readable explanation of why this decision was made."""

    predicted_rps: float
    current_pods: int
    current_capacity_rps: float = field(init=False)

    def __post_init__(self):
        # current_capacity_rps is derived, not passed in
        object.__setattr__(self, "current_capacity_rps", 0.0)


class ScalingDecisionEngine:
    def __init__(self, config: Config):
        self._pod_capacity = config.pod_capacity_rps
        self._min_pods = config.min_pods
        self._max_pods = config.max_pods
        self._scale_down_threshold = config.scale_down_threshold
        self._cooldown_seconds = config.cooldown_seconds

        # Tracks the monotonic clock time of the last scale-down action
        self._last_scale_down_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def decide(self, predicted_rps: float, current_pods: int) -> ScaleDecision:
        """
        Compute the target pod count and decide whether to act.

        Args:
            predicted_rps:  Peak RPS predicted by the forecaster.
            current_pods:   Replica count currently active in Kubernetes.

        Returns:
            ScaleDecision with target and whether to execute it.
        """
        pods_required = self._pods_for_rps(predicted_rps)
        current_capacity = current_pods * self._pod_capacity

        # --- Scale UP (immediate) ----------------------------------------
        if pods_required > current_pods:
            return ScaleDecision(
                target_pods=pods_required,
                should_scale=True,
                reason=(
                    f"Scale UP: predicted {predicted_rps:.1f} RPS requires "
                    f"{pods_required} pods (current: {current_pods}, "
                    f"capacity: {current_capacity:.0f} RPS)"
                ),
                predicted_rps=predicted_rps,
                current_pods=current_pods,
            )

        # --- Scale DOWN (guarded) ----------------------------------------
        if pods_required < current_pods:
            utilisation = predicted_rps / current_capacity if current_capacity > 0 else 0
            threshold_met = utilisation < self._scale_down_threshold

            if not threshold_met:
                return ScaleDecision(
                    target_pods=current_pods,
                    should_scale=False,
                    reason=(
                        f"Hold: predicted utilisation {utilisation:.0%} is above "
                        f"scale-down threshold {self._scale_down_threshold:.0%}"
                    ),
                    predicted_rps=predicted_rps,
                    current_pods=current_pods,
                )

            in_cooldown, remaining = self._in_cooldown()
            if in_cooldown:
                return ScaleDecision(
                    target_pods=current_pods,
                    should_scale=False,
                    reason=(
                        f"Hold: in scale-down cooldown for another "
                        f"{remaining:.0f}s"
                    ),
                    predicted_rps=predicted_rps,
                    current_pods=current_pods,
                )

            # All guards passed — approve scale-down
            self._last_scale_down_at = time.monotonic()
            return ScaleDecision(
                target_pods=pods_required,
                should_scale=True,
                reason=(
                    f"Scale DOWN: predicted utilisation {utilisation:.0%} < "
                    f"threshold {self._scale_down_threshold:.0%}, "
                    f"cooldown elapsed → {current_pods} → {pods_required} pods"
                ),
                predicted_rps=predicted_rps,
                current_pods=current_pods,
            )

        # --- No change -------------------------------------------------------
        return ScaleDecision(
            target_pods=current_pods,
            should_scale=False,
            reason=(
                f"No change: {current_pods} pods at "
                f"{predicted_rps:.1f}/{current_capacity:.0f} RPS"
            ),
            predicted_rps=predicted_rps,
            current_pods=current_pods,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pods_for_rps(self, rps: float) -> int:
        """Compute pods required, clamped to [min_pods, max_pods]."""
        raw = math.ceil(rps / self._pod_capacity)
        return max(self._min_pods, min(self._max_pods, raw))

    def _in_cooldown(self) -> tuple[bool, float]:
        """
        Returns (in_cooldown, seconds_remaining).
        If no scale-down has ever occurred, cooldown is not active.
        """
        if self._last_scale_down_at is None:
            return False, 0.0
        elapsed = time.monotonic() - self._last_scale_down_at
        remaining = self._cooldown_seconds - elapsed
        return remaining > 0, max(0.0, remaining)
