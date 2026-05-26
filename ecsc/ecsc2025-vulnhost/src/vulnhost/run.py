import argparse
import time
from concurrent.futures import ThreadPoolExecutor

from .config_format import load_config
from .manager import VulnhostManager, DryRunExecutor
from .utils import setup_logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update the cloud status")
    parser.add_argument(
        "--dry-run", action="store_true", help="Display, but do not execute actions"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Number of threads that execute actions",
    )
    parser.add_argument(
        "--write-status-history",
        action="store_true",
        help="Store all intermediate status records in /tmp",
    )
    parser.add_argument(
        "status_file", type=str, help="a JSON file containing the desired status"
    )
    args = parser.parse_args()

    setup_logging()
    if args.dry_run:
        executor: ThreadPoolExecutor = DryRunExecutor()
    elif args.threads is not None:
        executor = ThreadPoolExecutor(max_workers=args.threads)
    else:
        executor = ThreadPoolExecutor()
    manager = VulnhostManager("status.json", executor)
    manager.load_backends("backends.json")
    if args.write_status_history:
        manager.dump_states = True

    manager.update_states()
    print("CURRENT STATE:")
    for vm in manager.current_state.vms:
        print("-", vm.str_minimal())
    print("-" * 80)

    ts = time.time()
    with open(args.status_file, "r") as f:
        config = load_config(f.read())
    manager.transform_to_target_status(config)
    ts = time.time() - ts

    print("-" * 80)
    print("NEW STATE:")
    for vm in manager.current_state.vms:
        print("-", vm.str_minimal())
    manager.save()
    executor.shutdown()
    print(f"[DONE]  Actions took {ts:.3f} seconds")
