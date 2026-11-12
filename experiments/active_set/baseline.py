"""Thin, subprocess-isolated adapter for the upstream path-based OnlineTE.

No LP is used here. Worker splits are exported directly. The coordinator and
worker updates, original logging and timer boundaries are left unchanged.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def run_baseline(case, output_dir, timeout=300, max_outer=1000, mode="initialization", max_workers=4):
    """Return raw flattened flow/splits and provenance, never a replacement LP.

    ``mode='regression'`` keeps upstream parameters/tolerances. Initialization
    tightens only the residual-based stopping threshold (0.05 -> 0.00005). Both modes have the
    documented external time/iteration safety caps, including cold start.
    """
    if not isinstance(max_workers, int) or not 1 <= max_workers <= 4:
        raise ValueError("max_workers must be an integer between 1 and 4")
    if mode not in {"initialization", "regression"}:
        raise ValueError(mode)
    if not isinstance(max_outer, int) or not 1 <= max_outer <= 1000:
        raise ValueError("max_outer must be between 1 and 1000")
    if not 0 < timeout <= 300:
        raise ValueError("timeout must be in (0, 300]")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "case.json").write_text(json.dumps(case, allow_nan=False))
    result_path = output_dir / "baseline.json"
    result_path.unlink(missing_ok=True)
    for previous in output_dir.glob("worker-*.npz"):
        previous.unlink()
    cmd = [sys.executable, "-m", "experiments.active_set.baseline", "--child",
           "--directory", str(output_dir), "--max-outer", str(max_outer), "--mode", mode,
           "--max-workers", str(max_workers)]
    env = dict(os.environ)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        env[name] = "1"
    started = time.perf_counter_ns()
    with (output_dir / "baseline.log").open("w") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        timed_out = False
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            code = 124
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    result.update(wall_total_ns=time.perf_counter_ns()-started, exit_code=code,
                  log_path=str(output_dir / "baseline.log"), mode=mode,
                  timeout_seconds=timeout, max_outer_iterations=max_outer,
                  timing_unit="ns", source="original_onlinete_worker_path_splits")
    if timed_out:
        result["status"] = "timeout"
    elif code != 0:
        result["status"] = "baseline_execution_failed"
    result_path.write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def _worker_main(params, directory):
    import numpy as np
    from te.algorithms.formulations.path_based.distributed.worker import OnlineTEWorkerNode

    class ExportingWorker(OnlineTEWorkerNode):
        def __init__(self, params):
            self.update_wall_ns = 0
            self.update_cpu_ns = 0
            self.update_count = 0
            self.started_cpu_ns = time.process_time_ns()
            super().__init__(params)

        def do_inner_loop_pgd_update(self, epoch):
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            out = super().do_inner_loop_pgd_update(epoch)
            self.update_wall_ns += time.perf_counter_ns()-wall
            self.update_cpu_ns += time.process_time_ns()-cpu
            self.update_count += 1
            return out

        def report_chunk(self):
            # RequestChunk is called by upstream after solving. Do not alter the
            # RPC response or infer path splits from aggregate edge assignments.
            np.savez(Path(directory) / f"worker-{self.worker_id}.npz",
                     splits=self._dense_solver._Y_tk,
                     demands=self._dense_solver._demands,
                     start=self.assigned_commodity_start_id,
                     update_wall_ns=self.update_wall_ns,
                     update_cpu_ns=self.update_cpu_ns,
                     process_cpu_ns=time.process_time_ns()-self.started_cpu_ns,
                     update_count=self.update_count)
            return super().report_chunk()

    worker = ExportingWorker(params)
    try:
        worker.initialize()
        worker.run()
    finally:
        worker.close()


def _child(directory, max_outer, mode, max_workers=4):
    import asyncio
    import dataclasses
    import multiprocessing
    import socket
    import numpy as np
    import networkx as nx
    from te.algorithms.base import TEProblemDescription, TEObjective, TEEvaluationParams
    from te.algorithms.communication.base import DistributedSolverNodeParams
    from te.algorithms.communication.grpc.asynchronous_coordinator_backend import (
        AsynchronousgRPCCoordinatorBackend, AsynchronousgRPCCoordinatorBackendParams)
    from te.algorithms.communication.grpc.worker_backend import gRPCWorkerBackend, gRPCWorkerBackendParams
    from te.algorithms.formulations.path_based.distributed.coordinator import OnlineTECoordinator
    from te.algorithms.formulations.path_based.distributed.solver_params import PathBasedOnlineTEParameters
    from te.algorithms.sub_algorithms.mlu_backends.pdlp_mlu import PDLPMLU, PDLPMLUParams
    from te.path_providers.base import PathProvider
    from utils.exceptions import SolutionInterrupted

    directory = Path(directory)
    case = json.loads((directory / "case.json").read_text())
    graph = nx.DiGraph()
    graph.add_nodes_from(case["nodes"])
    for (s, t), capacity in zip(case["edges"], case["capacities"]):
        graph.add_edge(s, t, capacity=float(capacity))
    # NetworkX traverses edges grouped by source, independent of insertion order.
    edge_index = {edge: i for i, edge in enumerate(graph.edges())}
    k, n = len(case["ods"]), len(case["nodes"])
    expected_ods = [[s, t] for s in range(n) for t in range(n) if s != t]
    if case["ods"] != expected_ods:
        raise ValueError("Original OnlineTE requires sorted contiguous OD identifiers")
    workers = max(w for w in range(1, max_workers + 1) if k % w == 0)
    chunk = k // workers
    tmax = max(map(len, case["paths"]))
    path_file = directory / "paths.pkl"
    for w in range(workers):
        rows, cols, beta = [], [], []
        for paths in case["paths"][w*chunk:(w+1)*chunk]:
            row, col = [], []
            for t, path in enumerate(paths):
                for edge in zip(path, path[1:]):
                    row.append(edge_index[edge]); col.append(t)
            rows.append(np.asarray(row, dtype=np.int32))
            cols.append(np.asarray(col, dtype=np.int32))
            beta.append(len(paths))
        provider = PathProvider((chunk, len(edge_index), tmax), rows, cols, np.asarray(beta, dtype=np.int32))
        name, ext = os.path.splitext(path_file)
        provider.save(f"{name}_{w}_{chunk}{ext}")
    tm = np.zeros((n, n), dtype=np.float64)
    for (s, t), d in zip(case["ods"], case["demands"]):
        tm[s, t] = d
    evaluation = TEEvaluationParams()
    problem = TEProblemDescription(TEObjective.MLU, evaluation, graph, [tm])
    params = PathBasedOnlineTEParameters(PathFile=str(path_file), NumberOfPathsPerCommodity=tmax)
    sockets = []
    for _ in range(workers + 1):
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sockets.append(sock)
    ports = [s.getsockname()[1] for s in sockets]
    peers = tuple(("127.0.0.1", p) for p in ports[1:])
    rpc = AsynchronousgRPCCoordinatorBackendParams(Peers=(("127.0.0.1", ports[0]),), Workers=peers)
    for sock in sockets: sock.close()
    processes = []
    context = multiprocessing.get_context("spawn")
    for w in range(workers):
        worker_params = DistributedSolverNodeParams(gRPCWorkerBackend,
            gRPCWorkerBackendParams(PeerIndex=w, Peers=peers))
        proc = context.Process(target=_worker_main, args=(worker_params, str(directory)))
        proc.start(); processes.append(proc)

    class CappedCoordinator(OnlineTECoordinator):
        outer_iterations = 0
        reached_iteration_cap = False
        def _outer_inf_bound(self):
            return super()._outer_inf_bound() * (0.001 if mode == "initialization" else 1.0)
        def _do_network_update(self, epoch):
            if epoch >= max_outer:
                self.reached_iteration_cap = True
                raise SolutionInterrupted
            self.outer_iterations = max(self.outer_iterations, epoch+1)
            return super()._do_network_update(epoch)

    coordinator = None
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
        coordinator = CappedCoordinator(problem, params,
            DistributedSolverNodeParams(AsynchronousgRPCCoordinatorBackend, rpc),
            PDLPMLU, PDLPMLUParams(Threads=1))
        initialized_wall = time.perf_counter_ns()
        coordinator.make_lp()
        solve_start_wall = time.perf_counter_ns()
        coordinator.solve()
        solve_wall_ns = time.perf_counter_ns()-solve_start_wall
        splits, flows, worker_stats = [], [], []
        for w in range(workers):
            raw = np.load(directory / f"worker-{w}.npz")
            for j, paths in enumerate(case["paths"][w*chunk:(w+1)*chunk]):
                values = raw["splits"][:len(paths), j].astype(float)
                splits.extend(values.tolist())
                flows.extend((values * float(raw["demands"][j])).tolist())
            worker_stats.append({key: int(raw[key]) for key in
                ("update_wall_ns", "update_cpu_ns", "process_cpu_ns", "update_count")})
        coordinator_cpu_ns = time.process_time_ns()-started_cpu
        result = dict(cpu_total_ns=coordinator_cpu_ns + sum(w["process_cpu_ns"] for w in worker_stats),
                      cpu_scope="coordinator construction/solve plus each worker construction/update through export; excludes Python imports and shutdown",
                      status="iteration_limit" if coordinator.reached_iteration_cap else "solved",
                      flows=flows, splits=splits, workers=workers,
                      worker_stats=worker_stats, coordinator_cpu_ns=coordinator_cpu_ns,
                      startup_wall_ns=initialized_wall-started_wall,
                      make_lp_wall_ns=solve_start_wall-initialized_wall,
                      startup_jit_combined_ns=solve_start_wall-started_wall,
                      jit_timing="combined with startup and make_lp; JIT not separately measured; lazy solve-time JIT remains in solve_wall_ns",
                      solve_wall_ns=solve_wall_ns,
                      outer_iterations=coordinator.outer_iterations,
                      solver_parameters=dataclasses.asdict(params),
                      evaluation_parameters=dataclasses.asdict(evaluation),
                      original_stop_test="2 * outer_infeasibility / outer_inf_bound < 0.05",
                      deviations=["external time cap; cold-start outer iteration cap"] +
                         (["residual stopping threshold tightened from 0.05 to 0.00005 via bound scaling; QP parameters unchanged"] if mode == "initialization" else []))
        (directory / "baseline.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    finally:
        if coordinator is not None:
            coordinator.close()
        for proc in processes:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate(); proc.join(timeout=3)
            if proc.is_alive(): proc.kill(); proc.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--max-outer", type=int, default=1000)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--mode", choices=["initialization", "regression"], default="initialization")
    args = parser.parse_args()
    _child(args.directory, args.max_outer, args.mode, args.max_workers)
