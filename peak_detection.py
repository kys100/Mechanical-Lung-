"""Peak-flow segmentation and pressure capture for the mechanical-lung logger."""

import math
from dataclasses import dataclass
from numbers import Integral


DEFAULT_PEAK_TOLERANCE_PCT = 10.0
DEFAULT_MAX_SENSOR_AGE_MS = 20.0
DEFAULT_PEAK_THRESHOLD_FRAC = 0.35
DEFAULT_PEAK_THRESHOLD_FLOOR = 1.5
DEFAULT_WARMUP_BREATHS = 3


@dataclass(frozen=True)
class PeakDetectionConfig:
    """Validated peak-detection policy shared by analysis and display code."""

    threshold_frac: float = DEFAULT_PEAK_THRESHOLD_FRAC
    min_threshold: float = DEFAULT_PEAK_THRESHOLD_FLOOR
    exit_frac: float = 0.5
    min_samples: int = 5
    plateau_frac: float = 0.99
    smooth_window: int = 9
    target_tolerance_frac: float = DEFAULT_PEAK_TOLERANCE_PCT / 100.0
    max_sensor_age_us: float = DEFAULT_MAX_SENSOR_AGE_MS * 1000.0
    warmup_breaths: int = DEFAULT_WARMUP_BREATHS

    def __post_init__(self):
        fractions = (
            "threshold_frac", "exit_frac", "plateau_frac",
            "target_tolerance_frac",
        )
        for field_name in fractions:
            value = self._finite_float(field_name, getattr(self, field_name))
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{field_name} must be greater than zero "
                                 "and no greater than one")
            object.__setattr__(self, field_name, value)

        for field_name in ("min_threshold", "max_sensor_age_us"):
            value = self._finite_float(field_name, getattr(self, field_name))
            if value <= 0.0:
                raise ValueError(f"{field_name} must be greater than zero")
            object.__setattr__(self, field_name, value)

        for field_name, minimum in (("min_samples", 1),
                                    ("smooth_window", 1),
                                    ("warmup_breaths", 0)):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{field_name} must be an integer")
            value = int(value)
            if value < minimum:
                qualifier = "greater than zero" if minimum == 1 else "nonnegative"
                raise ValueError(f"{field_name} must be {qualifier}")
            object.__setattr__(self, field_name, value)

    @staticmethod
    def _finite_float(field_name, value):
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be a finite number")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a finite number") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{field_name} must be a finite number")
        return parsed

    @staticmethod
    def target_magnitude(target):
        if target is None:
            return 0.0
        target = abs(float(target))
        return target if math.isfinite(target) else 0.0

    def opening_threshold(self, target):
        return max(
            self.min_threshold,
            self.threshold_frac * self.target_magnitude(target),
        )


def centred_moving_average(vals, window):
    """Return a zero-lag moving average over a completed segment."""
    count = len(vals)
    if count == 0 or window <= 1 or count < window:
        return list(vals)
    if window % 2 == 0:
        window -= 1
    if window <= 1:
        return list(vals)
    half = window // 2
    prefix = [0.0] * (count + 1)
    for index, value in enumerate(vals):
        prefix[index + 1] = prefix[index] + value
    averaged = list(vals)
    for index in range(half, count - half):
        low = index - half
        high = index + half + 1
        averaged[index] = (prefix[high] - prefix[low]) / window
    return averaged


class PeakFlowDetector:
    """Segment breath excursions and emit peak-flow/pressure events.

    Segmentation uses the live trailing-average flow supplied by each sample.
    Peak location uses a centred offline average after the excursion closes.
    Electrical flow sign remains separate from the firmware-provided phase so
    reversing flow-sensor hoses cannot silently swap mechanical phase labels.
    """

    def __init__(self, config, on_peak):
        self.config = config
        self.on_peak = on_peak
        self._sign = 0
        self._buf = []
        self._latched_threshold = None
        self._latched_exit = None
        self._breath_index = 0
        self._current_breath_index = 0
        self._current_phase = None
        self._last_completed_phase = None
        self.count = 0
        self.discarded = 0
        self.target_passes = 0
        self.target_misses = 0
        self.partial_excursions = 0
        self.pressure_incomplete = 0
        self.timing_failures = 0
        self.qualified_peaks = 0
        self.unqualified_peaks = 0

    def _open(self, sample, sign, threshold):
        self._sign, self._buf = sign, [sample]
        self._latched_threshold = threshold
        self._latched_exit = threshold * self.config.exit_frac
        self._current_phase = sample.phase
        self._current_breath_index = self._breath_index + int(
            sample.phase == 0 and self._last_completed_phase == 1)

    def push(self, sample):
        # Firmware transmits last-good values beside false validity flags.
        if not sample.flow_ok:
            if self._sign != 0:
                self._close(complete=False)
            return

        flow = sample.flow_avg
        if self._sign == 0:
            threshold = self.config.opening_threshold(sample.target_peak_slm)
            if flow >= threshold:
                self._open(sample, 1, threshold)
            elif flow <= -threshold:
                self._open(sample, -1, threshold)
            return
        if self._sign * flow > self._latched_exit:
            self._buf.append(sample)
            return
        closing_sign = self._sign
        self._close(complete=True)
        threshold = self.config.opening_threshold(sample.target_peak_slm)
        if closing_sign > 0 and flow <= -threshold:
            self._open(sample, -1, threshold)
        elif closing_sign < 0 and flow >= threshold:
            self._open(sample, 1, threshold)

    def flush(self):
        """Emit an open excursion as partial and exclude it from scoring."""
        if self._sign != 0:
            self._close(complete=False)

    def _close(self, complete):
        samples, sign = self._buf, self._sign
        breath_index = self._current_breath_index
        phase = self._current_phase
        self._sign, self._buf = 0, []
        self._latched_threshold = self._latched_exit = None
        self._current_phase = None
        if len(samples) < self.config.min_samples:
            self.discarded += 1
            return
        if complete and phase in (0, 1):
            self._breath_index = breath_index
            self._last_completed_phase = phase

        raw = [sample.flow_raw for sample in samples]
        smooth = centred_moving_average(raw, self.config.smooth_window)
        signed_smooth = [sign * value for value in smooth]
        peak_index = max(range(len(samples)), key=signed_smooth.__getitem__)
        peak_magnitude = signed_smooth[peak_index]
        cut = self.config.plateau_frac * peak_magnitude

        peak_offset = 0.0
        if 0 < peak_index < len(samples) - 1:
            previous, current, following = signed_smooth[peak_index - 1:peak_index + 2]
            curvature = previous - 2.0 * current + following
            if curvature < 0.0:
                candidate = 0.5 * (previous - following) / curvature
                if -0.5 <= candidate <= 0.5:
                    peak_offset = candidate
                    peak_magnitude = (current -
                                      0.25 * (previous - following) * candidate)
        peak_value = sign * peak_magnitude
        if peak_offset < 0.0:
            peak_time_s = (samples[peak_index].t_s + peak_offset *
                           (samples[peak_index].t_s - samples[peak_index - 1].t_s))
        elif peak_offset > 0.0:
            peak_time_s = (samples[peak_index].t_s + peak_offset *
                           (samples[peak_index + 1].t_s - samples[peak_index].t_s))
        else:
            peak_time_s = samples[peak_index].t_s

        plateau_indices = [
            index for index, value in enumerate(smooth) if sign * value >= cut
        ]
        if not plateau_indices:
            plateau_indices = [peak_index]
        plateau = [samples[index] for index in plateau_indices]
        plateau_contiguous = all(
            right == left + 1
            for left, right in zip(plateau_indices, plateau_indices[1:])
        )

        pressure_count = len(samples[0].pok)
        pressure_means = []
        pressure_stddevs = []
        for channel in range(pressure_count):
            valid = [sample.pa[channel] for sample in plateau
                     if sample.pok[channel]]
            if valid:
                mean = sum(valid) / len(valid)
                pressure_means.append(mean)
                pressure_stddevs.append(math.sqrt(
                    sum((value - mean) ** 2 for value in valid) / len(valid)))
            else:
                pressure_means.append(float("nan"))
                pressure_stddevs.append(float("nan"))
        pressure_ok_fractions = [
            sum(1 for sample in plateau if sample.pok[channel]) / len(plateau)
            for channel in range(pressure_count)
        ]

        peak_sample = samples[peak_index]
        target_peak = self.config.target_magnitude(peak_sample.target_peak_slm)
        target_error = (peak_magnitude - target_peak
                        if target_peak > 0.0 else float("nan"))
        target_error_pct = (100.0 * target_error / target_peak
                            if target_peak > 0.0 else float("nan"))
        target_met = (abs(target_error) <=
                      self.config.target_tolerance_frac * target_peak
                      if complete and target_peak > 0.0 else None)
        if target_met is True:
            self.target_passes += 1
        elif target_met is False:
            self.target_misses += 1
        if not complete:
            self.partial_excursions += 1

        valid_pressure_ages = [
            age for ok, age in zip(peak_sample.pok, peak_sample.pa_age_us)
            if ok and age >= 0
        ]
        pressure_all_ok = all(peak_sample.pok)
        if not pressure_all_ok:
            self.pressure_incomplete += 1
        max_pressure_age = max(valid_pressure_ages) if valid_pressure_ages else -1
        pressure_age_span = (
            max(valid_pressure_ages) - min(valid_pressure_ages)
            if valid_pressure_ages else -1
        )
        flow_pressure_skew = (
            max(abs(age - peak_sample.flow_age_us) for age in valid_pressure_ages)
            if valid_pressure_ages and peak_sample.flow_age_us >= 0 else -1
        )
        timing_ok = (
            peak_sample.flow_age_us >= 0 and
            peak_sample.flow_age_us <= self.config.max_sensor_age_us and
            len(valid_pressure_ages) == pressure_count and
            max_pressure_age <= self.config.max_sensor_age_us
        )
        if not timing_ok:
            self.timing_failures += 1

        qualified_peak = (bool(target_met and pressure_all_ok and timing_ok)
                          if target_met is not None else None)
        if qualified_peak is True:
            self.qualified_peaks += 1
        elif qualified_peak is False:
            self.unqualified_peaks += 1

        self.count += 1
        self.on_peak({
            "peak_idx": self.count,
            "sample": peak_sample,
            "direction": sign,
            "flow_peak_slm": peak_value,
            "peak_time_s": peak_time_s,
            "peak_offset_samples": peak_offset,
            "target_peak_slm": target_peak,
            "target_error_slm": target_error,
            "target_error_pct": target_error_pct,
            "target_met": target_met,
            "is_warmup": breath_index < self.config.warmup_breaths,
            "excursion_complete": complete,
            "pa_mean": pressure_means,
            "pa_std": pressure_stddevs,
            "pa_ok_frac": pressure_ok_fractions,
            "pressure_all_ok": pressure_all_ok,
            "max_pressure_age_us": max_pressure_age,
            "pressure_age_span_us": pressure_age_span,
            "flow_pressure_skew_us": flow_pressure_skew,
            "timing_ok": timing_ok,
            "qualified_peak": qualified_peak,
            "plateau_n": len(plateau),
            "plateau_contiguous": plateau_contiguous,
            "plateau_span_s": plateau[-1].t_s - plateau[0].t_s,
            "excursion_n": len(samples),
            # Boundaries come from sample.flow_avg, the logger's trailing live
            # average, and lag by roughly half that live window. They are not
            # delayed by this config's offline centred smoothing window.
            "excursion_s": samples[-1].t_s - samples[0].t_s,
        })
