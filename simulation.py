"""SimPy 기반 5단계 공정 시뮬레이션.

단계: 입고/하역 → 선별/압착 → 장입/용해 → 하이브리드 주조 → 출하.
"""

from __future__ import annotations

import random
from collections.abc import Callable

import simpy

from config import SimulationConfig
from metrics import Metrics

ProgressFn = Callable[[float, float], None]


def run_simulation(cfg: SimulationConfig, progress: ProgressFn | None = None) -> Metrics:
    rng = random.Random(cfg.random_seed)
    env = simpy.Environment()
    metrics = Metrics()

    weighbridge = simpy.Resource(env, capacity=cfg.inbound.weighbridges)
    unloading_bays = simpy.Resource(env, capacity=cfg.inbound.unloading_bays)
    sort_queue: simpy.Store = simpy.Store(env)
    sorters = simpy.Resource(env, capacity=cfg.sorting.sorters)
    press_queue: simpy.Store = simpy.Store(env)
    presses = simpy.Resource(env, capacity=cfg.sorting.presses)
    pallet_buffer: simpy.Store = simpy.Store(env, capacity=cfg.sorting.pallet_buffer_cap)
    elevator = simpy.Resource(env, capacity=1)
    furnaces = simpy.Resource(env, capacity=cfg.melting.furnace_count)
    flake_line = simpy.Resource(env, capacity=1)
    scr_line = simpy.Resource(env, capacity=1)
    flake_buffer: simpy.Store = simpy.Store(env, capacity=cfg.casting.flake_buffer_cap)
    scr_buffer: simpy.Store = simpy.Store(env, capacity=cfg.casting.scr_buffer_cap)

    metrics.resource_capacity = {
        "weighbridge": cfg.inbound.weighbridges,
        "unloading_bay": cfg.inbound.unloading_bays,
        "sorter": cfg.sorting.sorters,
        "press": cfg.sorting.presses,
        "elevator": 1,
        "furnace": cfg.melting.furnace_count,
        "flake_line": 1,
        "scr_line": 1,
    }

    metrics.sample_buffer(0.0, "pallet_buffer", 0)
    metrics.sample_buffer(0.0, "flake_buffer", 0)
    metrics.sample_buffer(0.0, "scr_buffer", 0)

    arrivals = _schedule_inbound(cfg, rng)
    env.process(_inbound_dispatcher(env, cfg, metrics, weighbridge, unloading_bays, sort_queue, arrivals))

    for _ in range(cfg.sorting.sorters):
        env.process(_sort_worker(env, cfg, metrics, sort_queue, sorters, press_queue))
    for _ in range(cfg.sorting.presses):
        env.process(_press_worker(env, cfg, metrics, press_queue, presses, pallet_buffer))
    for f_id in range(cfg.melting.furnace_count):
        env.process(
            _furnace_worker(
                env, cfg, metrics, pallet_buffer, elevator, furnaces,
                flake_line, scr_line, flake_buffer, scr_buffer, f_id,
            )
        )
    env.process(_outbound_dispatcher(env, cfg, metrics, weighbridge, flake_buffer, scr_buffer, rng))

    if progress is not None:
        env.process(_progress_ticker(env, cfg, progress))

    env.run(until=cfg.sim_horizon_min)

    if progress is not None:
        progress(1.0, float(cfg.sim_horizon_min))

    return metrics


def _progress_ticker(env: simpy.Environment, cfg: SimulationConfig, progress: ProgressFn):
    horizon = cfg.sim_horizon_min
    step = max(60, horizon // 200)
    while env.now < horizon:
        yield env.timeout(step)
        progress(min(1.0, env.now / horizon), env.now)


def _schedule_inbound(cfg: SimulationConfig, rng: random.Random) -> list[float]:
    arrivals: list[float] = []
    morning_start = cfg.inbound.arrival_start_min
    morning_end = cfg.inbound.morning_cutoff_min
    afternoon_end = cfg.inbound.arrival_end_min
    for day in range(cfg.sim_days):
        day_offset = day * 24 * 60
        for _ in range(cfg.inbound.trucks_per_day):
            if rng.random() < cfg.inbound.morning_share:
                t = rng.uniform(morning_start, morning_end)
            else:
                t = rng.uniform(morning_end, afternoon_end)
            arrivals.append(day_offset + t)
    arrivals.sort()
    return arrivals


def _inbound_dispatcher(env, cfg, metrics, weighbridge, unloading_bays, sort_queue, arrivals):
    for idx, arrival in enumerate(arrivals):
        wait = arrival - env.now
        if wait > 0:
            yield env.timeout(wait)
        env.process(
            _handle_inbound_truck(env, cfg, metrics, idx, weighbridge, unloading_bays, sort_queue)
        )


def _handle_inbound_truck(env, cfg, metrics, idx, weighbridge, unloading_bays, sort_queue):
    arrived = env.now
    metrics.inbound_truck_count += 1
    metrics.log(env.now, "inbound_arrive", truck_id=idx)

    with weighbridge.request() as req:
        yield req
        yield env.timeout(cfg.inbound.weigh_in_min)
        metrics.add_busy("weighbridge", cfg.inbound.weigh_in_min)

    with unloading_bays.request() as req:
        yield req
        yield env.timeout(cfg.inbound.unload_min)
        metrics.add_busy("unloading_bay", cfg.inbound.unload_min)

    yield sort_queue.put({"truck_id": idx, "ton": cfg.inbound.truck_load_ton})

    with weighbridge.request() as req:
        yield req
        yield env.timeout(cfg.inbound.weigh_out_min)
        metrics.add_busy("weighbridge", cfg.inbound.weigh_out_min)

    dur = env.now - arrived
    metrics.inbound_truck_durations.append(dur)
    metrics.log(env.now, "inbound_leave", truck_id=idx, duration_min=dur)


def _sort_worker(env, cfg, metrics, sort_queue, sorters, press_queue):
    while True:
        truckload = yield sort_queue.get()
        with sorters.request() as req:
            yield req
            yield env.timeout(cfg.sorting.sort_min_per_truck)
            metrics.add_busy("sorter", cfg.sorting.sort_min_per_truck)
        for i in range(cfg.sorting.subpiles_per_truck):
            yield press_queue.put({"truck_id": truckload["truck_id"], "subpile_id": i})


def _press_worker(env, cfg, metrics, press_queue, presses, pallet_buffer):
    block_cycle = (
        cfg.sorting.forklift_min_per_block
        + cfg.sorting.press_min_per_block
        + cfg.sorting.pallet_load_min_per_block
    )
    while True:
        subpile = yield press_queue.get()
        for _ in range(cfg.sorting.blocks_per_subpile):
            with presses.request() as req:
                yield req
                yield env.timeout(block_cycle)
                metrics.add_busy("press", block_cycle)
        yield pallet_buffer.put({"ton": cfg.sorting.subpile_ton, "truck_id": subpile["truck_id"]})
        metrics.sample_buffer(env.now, "pallet_buffer", len(pallet_buffer.items))


def _furnace_worker(
    env, cfg, metrics, pallet_buffer, elevator, furnaces,
    flake_line, scr_line, flake_buffer, scr_buffer, furnace_id: int = 0,
):
    while True:
        batch_pallets = []
        for _ in range(cfg.melting.pallets_per_batch):
            pallet = yield pallet_buffer.get()
            batch_pallets.append(pallet)
            metrics.sample_buffer(env.now, "pallet_buffer", len(pallet_buffer.items))

        batch_id = metrics.next_batch_id()
        batch_start = env.now
        metrics.log(env.now, "batch_start", batch_id=batch_id, furnace_id=furnace_id, pallets=len(batch_pallets))

        with furnaces.request() as freq:
            yield freq

            trips = cfg.melting.pallets_per_batch // cfg.melting.elevator_pallets_per_trip
            for _ in range(trips):
                with elevator.request() as ereq:
                    yield ereq
                    yield env.timeout(cfg.melting.elevator_cycle_min)
                    metrics.add_busy("elevator", cfg.melting.elevator_cycle_min)

            yield env.timeout(cfg.melting.setup_min)
            metrics.add_busy("furnace", cfg.melting.setup_min)

            yield env.timeout(cfg.melting.melting_min)
            metrics.add_busy("furnace", cfg.melting.melting_min)

            yield env.timeout(cfg.casting.holding_setup_min)
            metrics.add_busy("furnace", cfg.casting.holding_setup_min)

            batch_ton = cfg.melting.batch_ton
            flake_ton = batch_ton * cfg.casting.flake_ratio
            scr_ton = batch_ton - flake_ton

            flake_proc = env.process(_cast_flake(env, cfg, metrics, flake_line, flake_buffer, flake_ton))
            scr_proc = env.process(_cast_scr(env, cfg, metrics, scr_line, scr_buffer, scr_ton))
            yield env.all_of([flake_proc, scr_proc])

        batch_dur = env.now - batch_start
        metrics.batch_durations.append(batch_dur)
        metrics.batches_completed += 1
        metrics.log(env.now, "batch_complete", batch_id=batch_id, furnace_id=furnace_id, duration_min=batch_dur)


def _cast_flake(env, cfg, metrics, flake_line, flake_buffer, total_ton):
    with flake_line.request() as req:
        yield req
        units = int(total_ton / cfg.casting.flake_unit_ton)
        for _ in range(units):
            yield env.timeout(cfg.casting.flake_min_per_unit)
            metrics.add_busy("flake_line", cfg.casting.flake_min_per_unit)
            yield flake_buffer.put({"ton": cfg.casting.flake_unit_ton})
            metrics.flake_produced_ton += cfg.casting.flake_unit_ton
            metrics.daily_production[int(env.now // (24 * 60))]["flake"] += cfg.casting.flake_unit_ton
            metrics.sample_buffer(env.now, "flake_buffer", len(flake_buffer.items))


def _cast_scr(env, cfg, metrics, scr_line, scr_buffer, total_ton):
    with scr_line.request() as req:
        yield req
        units = int(total_ton / cfg.casting.scr_unit_ton)
        for _ in range(units):
            yield env.timeout(cfg.casting.scr_min_per_unit)
            metrics.add_busy("scr_line", cfg.casting.scr_min_per_unit)
            yield scr_buffer.put({"ton": cfg.casting.scr_unit_ton})
            metrics.scr_produced_ton += cfg.casting.scr_unit_ton
            metrics.daily_production[int(env.now // (24 * 60))]["scr"] += cfg.casting.scr_unit_ton
            metrics.sample_buffer(env.now, "scr_buffer", len(scr_buffer.items))


def _outbound_dispatcher(env, cfg, metrics, weighbridge, flake_buffer, scr_buffer, rng):
    horizon = cfg.sim_horizon_min
    while env.now < horizon:
        yield env.timeout(rng.expovariate(1.0 / cfg.outbound.truck_interval_min))
        if env.now >= horizon:
            break
        is_flake = rng.random() < cfg.outbound.flake_truck_prob
        target = flake_buffer if is_flake else scr_buffer
        name = "flake_buffer" if is_flake else "scr_buffer"
        unit_ton = cfg.casting.flake_unit_ton if is_flake else cfg.casting.scr_unit_ton
        env.process(_handle_outbound_truck(env, cfg, metrics, weighbridge, target, name, unit_ton))


def _handle_outbound_truck(env, cfg, metrics, weighbridge, buffer, buffer_name, unit_ton):
    arrived = env.now
    units_needed = max(1, int(cfg.outbound.truck_capacity_ton / unit_ton))

    deadline = env.now + cfg.outbound.max_wait_min
    while not buffer.items and env.now < deadline:
        yield env.timeout(min(15.0, deadline - env.now))

    if not buffer.items:
        metrics.aborted_outbound += 1
        metrics.log(env.now, "outbound_abort", buffer=buffer_name)
        return

    with weighbridge.request() as req:
        yield req
        yield env.timeout(cfg.outbound.weigh_in_min)
        metrics.add_busy("weighbridge", cfg.outbound.weigh_in_min)

    take = min(units_needed, len(buffer.items))
    units = []
    for _ in range(take):
        unit = yield buffer.get()
        units.append(unit)
        metrics.sample_buffer(env.now, buffer_name, len(buffer.items))

    yield env.timeout(cfg.outbound.load_min)

    with weighbridge.request() as req:
        yield req
        yield env.timeout(cfg.outbound.weigh_out_min)
        metrics.add_busy("weighbridge", cfg.outbound.weigh_out_min)

    dur = env.now - arrived
    metrics.outbound_truck_durations.append(dur)
    metrics.outbound_truck_count += 1
    loaded = sum(u["ton"] for u in units)
    metrics.log(env.now, "outbound_leave", buffer=buffer_name, ton=loaded, duration_min=dur)
