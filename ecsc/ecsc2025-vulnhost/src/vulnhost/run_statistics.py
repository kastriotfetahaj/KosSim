from concurrent.futures.thread import ThreadPoolExecutor

from .remote_api import RemoteApi
from .manager import VulnhostManager


def main() -> None:
    executor = ThreadPoolExecutor()
    manager = VulnhostManager("status.json", executor)
    manager.load_backends("backends.json")
    manager.update_states()
    stats = manager.retrieve_statistics()
    print("Stats:", len(stats))
    for line in stats:
        print(line)
    if manager.statistics_url:
        api = RemoteApi(manager)
        api.send_statistics(stats)


if __name__ == "__main__":
    main()
