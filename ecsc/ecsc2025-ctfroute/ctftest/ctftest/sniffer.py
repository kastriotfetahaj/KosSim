import asyncio

import scapy.all
import scapy.sendrecv


def sniff(*args, **kwargs):
    loop = asyncio.get_event_loop()

    future = loop.create_future()
    sniffer = None

    def started_callback():
        if not future.done():
            future.set_result(sniffer)

    sniffer = scapy.all.AsyncSniffer(
        *args,
        **kwargs,
        iface=scapy.all.get_if_list(),
        started_callback=started_callback,
    )

    sniffer.start()

    async def wait_for_exception():
        while True:
            await asyncio.sleep(1)
            if not future.done():
                if sniffer.exception:
                    future.set_exception(sniffer.exception)
            else:
                break

    loop.create_task(wait_for_exception())

    return future


async def main():
    print("Hello from pcap-test!")
    sniffer = await sniff()
    input("Press enter to show sniffed packages")
    print("count is:", sniffer.count)
    input("Press enter to stop sniffing")
    results = sniffer.stop(
        join=True
    )  # can throw Exception "Unsupported (offline or unsupported socket)"

    print(len(results) if results else "no results")


if __name__ == "__main__":
    asyncio.run(main())
