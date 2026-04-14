from __future__ import annotations

import time


class PIDController:
    """PID Controller for offboard axis manipulation and alignment."""

    def __init__(
        self,
        p: float = 0.02,
        i: float = 0.0,
        d: float = 0.0,
        current_time: float | None = None,
    ) -> None:
        self.k_p = p
        self.k_i = i
        self.k_d = d

        self.sample_time = 0.00
        self.current_time = current_time if current_time is not None else time.time()
        self.last_time = self.current_time

        self.clear()

    def clear(self) -> None:
        """Clears PID computations and coefficients."""
        self.setpoint = 0.0

        self.p_term = 0.0
        self.i_term = 0.0
        self.d_term = 0.0
        self.last_error = 0.0

        # Windup Guard
        self.int_error = 0.0
        self.windup_guard = 20.0

        self.output = 0.0

    def update(self, feedback_value: float, current_time: float | None = None) -> None:
        """Calculates PID value for given reference feedback.
        
        Args:
            feedback_value: The current measured value (e.g., error margin).
            current_time: Override for simulation stepping.
        """
        error = self.setpoint - feedback_value

        self.current_time = current_time if current_time is not None else time.time()
        delta_time = self.current_time - self.last_time
        delta_error = error - self.last_error

        if delta_time >= self.sample_time:
            self.p_term = self.k_p * error
            self.i_term += error * delta_time

            # Windup Guard
            if self.i_term < -self.windup_guard:
                self.i_term = -self.windup_guard
            elif self.i_term > self.windup_guard:
                self.i_term = self.windup_guard

            self.d_term = 0.0
            if delta_time > 0:
                self.d_term = delta_error / delta_time

            # Remember last time and last error for next calculation
            self.last_time = self.current_time
            self.last_error = error

            self.output = self.p_term + (self.k_i * self.i_term) + (self.k_d * self.d_term)

    def set_k_p(self, proportional_gain: float) -> None:
        """Determines how aggressively the PID reacts to the current error."""
        self.k_p = proportional_gain

    def set_k_i(self, integral_gain: float) -> None:
        """Controls reaction to accumulated past error."""
        self.k_i = integral_gain

    def set_k_d(self, derivative_gain: float) -> None:
        """Determines reaction to rate of change."""
        self.k_d = derivative_gain

    def set_windup(self, windup: float) -> None:
        """Integral windup guard limit to prevent extreme overshoot."""
        self.windup_guard = windup

    def set_sample_time(self, sample_time: float) -> None:
        """Pre-determined evaluation interval."""
        self.sample_time = sample_time
