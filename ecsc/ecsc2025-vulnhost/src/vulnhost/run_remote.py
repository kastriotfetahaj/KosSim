import argparse
import logging
import signal
import time
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Callable, Any

from .manager import VulnhostManager, DryRunExecutor
from .remote_api import RemoteApi
from .utils import setup_logging


class Iterations:
    def __init__(self) -> None:
        self.interrupted = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def register_signals(self) -> None:
        def handler(signal: int, frametype: Any) -> None:
            if self.interrupted:
                raise Exception("Cold shutdown")
            else:
                self.interrupted = True
                self.logger.info("Warm shutdown ...")

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGQUIT, handler)
        signal.signal(signal.SIGHUP, handler)

    def loop(self, func: Callable[[], None]) -> None:
        while not self.interrupted:
            ts = time.monotonic()
            try:
                func()
            except:
                logging.exception("Iteration failed")
            dt = time.monotonic() - ts
            self.logger.info(f"completed iteration in {dt:.1f} seconds")
            if not self.interrupted:
                for _ in range(max(3, 20 - int(dt))):
                    time.sleep(1)
                    if self.interrupted:
                        break


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update the cloud status, take desired status from HTTP endpoint"
    )
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
        "--no-statistics",
        action="store_true",
        help="Ignore statistics, even if configured",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("main")
    iterator = Iterations()
    iterator.register_signals()

    if args.dry_run:
        executor: ThreadPoolExecutor = DryRunExecutor()
    elif args.threads is not None:
        executor = ThreadPoolExecutor(max_workers=args.threads)
    else:
        executor = ThreadPoolExecutor(max_workers=1)
    manager = VulnhostManager("status.json", executor)
    manager.load_backends("backends.json")
    if not manager.config_url:
        raise ValueError("backends.config_url missing")
    if not manager.status_url:
        raise ValueError("backends.status_url missing")
    api = RemoteApi(manager)
    last_statistics_time: float = 0

    def loop() -> None:
        nonlocal last_statistics_time
        loop_start = time.monotonic()

        manager.update_states()
        config = api.get_remote_config()
        if config:
            logger.info("transforming status if necessary...")
            manager.transform_to_target_status(config)
            manager.save()
        api.set_remote_status(manager.current_state.dump())
        if (
            manager.statistics_url
            and manager.statistics_interval is not None
            and not args.no_statistics
        ):
            if last_statistics_time + manager.statistics_interval <= time.monotonic():
                last_statistics_time = time.monotonic()
                short: bool = time.monotonic() - loop_start > 20
                logger.info(
                    "statistics preparing..."
                    if not short
                    else "statistics preparing (no details)..."
                )
                stats = manager.retrieve_statistics(short=short)
                api.send_statistics(stats)
                logger.info("statistics completed.")

    logger.info("Start working on remote status...")
    iterator.loop(loop)

    executor.shutdown()


if __name__ == "__main__":
    main()
