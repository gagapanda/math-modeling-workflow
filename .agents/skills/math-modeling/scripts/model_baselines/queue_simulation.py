"""Simulate an auditable steady-state M/M/1 FCFS queue baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t


METRICS = (
    "mean_waiting_time",
    "mean_system_time",
    "p95_waiting_time",
    "probability_of_wait",
    "time_average_queue_length",
    "time_average_system_size",
    "utilization",
    "effective_arrival_rate",
    "little_lq_residual",
    "little_l_residual",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_positive(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return number


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _bounded_integer(
    value: object, label: str, minimum: int, maximum: int
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _validate_config(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("input JSON must be an object")
    if raw.get("model") != "M/M/1":
        raise ValueError("model must be exactly M/M/1")
    if raw.get("discipline", "FCFS") != "FCFS":
        raise ValueError("only FCFS discipline is supported")
    if raw.get("capacity", "infinite") != "infinite":
        raise ValueError("only infinite system capacity is supported")

    arrival_rate = _finite_positive(raw.get("arrival_rate"), "arrival_rate")
    service_rate = _finite_positive(raw.get("service_rate"), "service_rate")
    if arrival_rate >= service_rate:
        raise ValueError(
            "steady-state M/M/1 requires arrival_rate < service_rate"
        )
    arrival_source = _nonempty_text(
        raw.get("arrival_rate_source"), "arrival_rate_source"
    )
    service_source = _nonempty_text(
        raw.get("service_rate_source"), "service_rate_source"
    )
    time_unit = _nonempty_text(raw.get("time_unit"), "time_unit")

    simulation = raw.get("simulation", {})
    if not isinstance(simulation, dict):
        raise ValueError("simulation must be an object")
    customers = _bounded_integer(
        simulation.get("customers", 20_000),
        "simulation.customers",
        100,
        5_000_000,
    )
    warmup_customers = _bounded_integer(
        simulation.get("warmup_customers", 2_000),
        "simulation.warmup_customers",
        0,
        1_000_000,
    )
    replications = _bounded_integer(
        simulation.get("replications", 8),
        "simulation.replications",
        3,
        100,
    )
    convergence_points = _bounded_integer(
        simulation.get("convergence_points", 12),
        "simulation.convergence_points",
        3,
        100,
    )
    event_output_limit = _bounded_integer(
        simulation.get("event_output_limit", 10_000),
        "simulation.event_output_limit",
        0,
        100_000,
    )
    seed = simulation.get("seed", 42)
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2**32 - 1
    ):
        raise ValueError(
            "simulation.seed must be an integer in [0, 2^32 - 1]"
        )
    confidence_level = simulation.get("confidence_level", 0.95)
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not math.isfinite(float(confidence_level))
        or not 0.5 < float(confidence_level) < 1
    ):
        raise ValueError(
            "simulation.confidence_level must be a finite number in (0.5, 1)"
        )

    return {
        "model": "M/M/1",
        "discipline": "FCFS",
        "capacity": "infinite",
        "arrival_rate": arrival_rate,
        "service_rate": service_rate,
        "arrival_rate_source": arrival_source,
        "service_rate_source": service_source,
        "time_unit": time_unit,
        "simulation": {
            "customers": customers,
            "warmup_customers": warmup_customers,
            "replications": replications,
            "seed": seed,
            "confidence_level": float(confidence_level),
            "convergence_points": convergence_points,
            "event_output_limit": event_output_limit,
        },
    }


def _generate_path(
    arrival_rate: float,
    service_rate: float,
    customers: int,
    warmup_customers: int,
    seed: int,
) -> dict[str, np.ndarray]:
    total = warmup_customers + customers + 1
    rng = np.random.default_rng(seed)
    inter_arrivals = rng.exponential(1 / arrival_rate, total)
    service_times = rng.exponential(1 / service_rate, total)
    arrivals = np.cumsum(inter_arrivals)
    starts = np.empty(total, dtype=float)
    departures = np.empty(total, dtype=float)
    previous_departure = 0.0
    for index in range(total):
        starts[index] = max(arrivals[index], previous_departure)
        departures[index] = starts[index] + service_times[index]
        previous_departure = departures[index]
    return {
        "inter_arrival": inter_arrivals,
        "arrival": arrivals,
        "service_time": service_times,
        "service_start": starts,
        "departure": departures,
        "waiting_time": starts - arrivals,
        "system_time": departures - arrivals,
    }


def _overlap_sum(
    starts: np.ndarray,
    ends: np.ndarray,
    window_start: float,
    window_end: float,
) -> float:
    overlap = np.minimum(ends, window_end) - np.maximum(starts, window_start)
    return float(np.clip(overlap, 0, None).sum())


def _metrics_for_path(
    path: dict[str, np.ndarray],
    warmup_customers: int,
    customers: int,
) -> dict[str, float]:
    observed = slice(warmup_customers, warmup_customers + customers)
    window_start = float(path["arrival"][warmup_customers])
    window_end = float(path["arrival"][warmup_customers + customers])
    duration = window_end - window_start
    waiting = path["waiting_time"][observed]
    system = path["system_time"][observed]

    queue_area = _overlap_sum(
        path["arrival"], path["service_start"], window_start, window_end
    )
    system_area = _overlap_sum(
        path["arrival"], path["departure"], window_start, window_end
    )
    busy_area = _overlap_sum(
        path["service_start"], path["departure"], window_start, window_end
    )
    effective_rate = customers / duration
    mean_wait = float(np.mean(waiting))
    mean_system = float(np.mean(system))
    lq = queue_area / duration
    system_size = system_area / duration
    return {
        "mean_waiting_time": mean_wait,
        "mean_system_time": mean_system,
        "p50_waiting_time": float(np.quantile(waiting, 0.50)),
        "p95_waiting_time": float(np.quantile(waiting, 0.95)),
        "probability_of_wait": float(np.mean(waiting > 1e-12)),
        "time_average_queue_length": lq,
        "time_average_system_size": system_size,
        "utilization": busy_area / duration,
        "effective_arrival_rate": effective_rate,
        "little_lq_residual": lq - effective_rate * mean_wait,
        "little_l_residual": system_size - effective_rate * mean_system,
        "observation_start": window_start,
        "observation_end": window_end,
        "observation_duration": duration,
    }


def _theory(arrival_rate: float, service_rate: float) -> dict[str, float]:
    utilization = arrival_rate / service_rate
    mean_system_time = 1 / (service_rate - arrival_rate)
    mean_waiting_time = utilization / (service_rate - arrival_rate)
    waiting_quantile_probability = 0.95
    p95_waiting_time = (
        0.0
        if waiting_quantile_probability <= 1 - utilization
        else -math.log(
            (1 - waiting_quantile_probability) / utilization
        )
        / (service_rate - arrival_rate)
    )
    return {
        "utilization": utilization,
        "mean_waiting_time": mean_waiting_time,
        "mean_system_time": mean_system_time,
        "p95_waiting_time": p95_waiting_time,
        "probability_of_wait": utilization,
        "time_average_queue_length": arrival_rate * mean_waiting_time,
        "time_average_system_size": arrival_rate * mean_system_time,
        "effective_arrival_rate": arrival_rate,
    }


def _confidence_summary(
    replication_frame: pd.DataFrame,
    theory: dict[str, float],
    confidence_level: float,
) -> pd.DataFrame:
    records = []
    critical = float(
        t.ppf(
            (1 + confidence_level) / 2,
            df=len(replication_frame) - 1,
        )
    )
    for metric in METRICS:
        values = replication_frame[metric].to_numpy(dtype=float)
        mean = float(np.mean(values))
        standard_deviation = float(np.std(values, ddof=1))
        standard_error = standard_deviation / math.sqrt(len(values))
        theoretical = theory.get(metric)
        absolute_error = (
            abs(mean - theoretical) if theoretical is not None else None
        )
        relative_error = (
            absolute_error / abs(theoretical)
            if theoretical not in (None, 0)
            else None
        )
        records.append(
            {
                "metric": metric,
                "replication_mean": mean,
                "between_replication_standard_deviation": standard_deviation,
                "standard_error": standard_error,
                "confidence_lower": mean - critical * standard_error,
                "confidence_upper": mean + critical * standard_error,
                "theoretical_value": theoretical,
                "absolute_error": absolute_error,
                "relative_error": relative_error,
                "theoretical_value_in_confidence_interval": (
                    bool(
                        mean - critical * standard_error
                        <= theoretical
                        <= mean + critical * standard_error
                    )
                    if theoretical is not None
                    else None
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def _checkpoints(customers: int, requested: int) -> list[int]:
    start = min(100, customers)
    values = np.geomspace(start, customers, num=requested, dtype=int)
    return sorted(set([start, *values.tolist(), customers]))


def _events_frame(
    path: dict[str, np.ndarray],
    warmup_customers: int,
    customers: int,
    limit: int,
) -> pd.DataFrame:
    count = min(customers, limit)
    indices = np.arange(warmup_customers, warmup_customers + count)
    frame = pd.DataFrame(
        {
            "customer": np.arange(1, count + 1),
            "absolute_customer": indices + 1,
            **{name: values[indices] for name, values in path.items()},
        }
    )
    return frame


def _run_replications(
    config: dict, warmup_customers: int
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    simulation = config["simulation"]
    records = []
    first_path = None
    for index in range(simulation["replications"]):
        seed = (simulation["seed"] + index) % (2**32)
        path = _generate_path(
            config["arrival_rate"],
            config["service_rate"],
            simulation["customers"],
            warmup_customers,
            seed,
        )
        if first_path is None:
            first_path = path
        records.append(
            {
                "replication": index + 1,
                "seed": seed,
                "warmup_customers": warmup_customers,
                **_metrics_for_path(
                    path,
                    warmup_customers,
                    simulation["customers"],
                ),
            }
        )
    assert first_path is not None
    return pd.DataFrame.from_records(records), first_path


def run(input_path: Path, output_dir: Path) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    config = _validate_config(raw)
    simulation = config["simulation"]
    theory = _theory(config["arrival_rate"], config["service_rate"])

    replications, first_path = _run_replications(
        config, simulation["warmup_customers"]
    )
    summary = _confidence_summary(
        replications, theory, simulation["confidence_level"]
    )

    convergence_records = []
    for count in _checkpoints(
        simulation["customers"], simulation["convergence_points"]
    ):
        convergence_records.append(
            {
                "customers": count,
                **_metrics_for_path(
                    first_path, simulation["warmup_customers"], count
                ),
            }
        )

    no_warmup_replications, _ = _run_replications(config, 0)
    warmup_comparison = pd.DataFrame(
        [
            {
                "warmup_customers": warmup,
                **{
                    f"mean_{metric}": float(frame[metric].mean())
                    for metric in (
                        "mean_waiting_time",
                        "mean_system_time",
                        "time_average_queue_length",
                        "time_average_system_size",
                        "utilization",
                    )
                },
            }
            for warmup, frame in (
                (0, no_warmup_replications),
                (simulation["warmup_customers"], replications),
            )
        ]
    )

    event_count = min(
        simulation["customers"], simulation["event_output_limit"]
    )
    warnings = []
    if simulation["warmup_customers"] == 0:
        warnings.append(
            "warmup_customers is zero; empty-start transient bias is not removed"
        )
    if event_count < simulation["customers"]:
        warnings.append(
            f"queue_events.csv is truncated to the first {event_count} "
            f"of {simulation['customers']} observed customers"
        )
    if theory["utilization"] >= 0.9:
        warnings.append(
            "utilization is at least 0.9; waiting metrics converge slowly "
            "and require stronger run-length sensitivity"
        )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    replications.to_csv(output_dir / "replications.csv", index=False)
    summary.to_csv(output_dir / "summary.csv", index=False)
    pd.DataFrame(convergence_records).to_csv(
        output_dir / "convergence.csv", index=False
    )
    warmup_comparison.to_csv(
        output_dir / "warmup_comparison.csv", index=False
    )
    _events_frame(
        first_path,
        simulation["warmup_customers"],
        simulation["customers"],
        simulation["event_output_limit"],
    ).to_csv(output_dir / "queue_events.csv", index=False)

    summary_by_metric = {
        row["metric"]: {
            key: (None if pd.isna(value) else value)
            for key, value in row.items()
            if key != "metric"
        }
        for row in summary.to_dict(orient="records")
    }
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "model": config["model"],
        "discipline": config["discipline"],
        "capacity": config["capacity"],
        "time_unit": config["time_unit"],
        "arrival_rate": config["arrival_rate"],
        "service_rate": config["service_rate"],
        "arrival_rate_source": config["arrival_rate_source"],
        "service_rate_source": config["service_rate_source"],
        "stability_satisfied": True,
        "theory": theory,
        "simulation": simulation,
        "summary": summary_by_metric,
        "warnings": warnings,
        "outputs": [
            "summary.csv",
            "replications.csv",
            "convergence.csv",
            "warmup_comparison.csv",
            "queue_events.csv",
        ],
    }
    (output_dir / "run.json").write_text(
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.input, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
