import asyncio
import logging
import os
import time
from hashlib import sha256
from typing import Iterable

from enochecker3 import PutflagCheckerTaskMessage, GetflagCheckerTaskMessage, ExploitCheckerTaskMessage, \
    PutnoiseCheckerTaskMessage, GetnoiseCheckerTaskMessage, HavocCheckerTaskMessage, BaseCheckerTaskMessage

from checker import checker

os.environ['MONGO_USER'] = os.environ.get('MONGO_USER', 'jitterish_checker')
os.environ['MONGO_PASSWORD'] = os.environ.get('MONGO_PASSWORD', 'jitterish_checker')


class DemoRunner:
    def __init__(self):
        self.responses = []

    @classmethod
    async def setup(cls) -> None:
        # setup code
        logging.basicConfig(format=f'[%(asctime)s.%(msecs)03d] %(levelname)-9.9s: %(message)s', level=logging.INFO)
        await checker._init()

    async def run(self, task):
        response = await getattr(checker, f'_call_{task.method.value}')(task)
        print("====================")
        print(response)
        print("====================\n\n")
        self.responses.append((task, response))
        return response

    def report(self) -> None:
        print("\n\n====================")
        for t, r in self.responses:
            print(f'{t.method.value:8s} {t.variant_id}  {r}')

    def clear(self) -> None:
        self.responses.clear()

    async def demo(self) -> None:
        """what a mess"""

        task: BaseCheckerTaskMessage
        params = {
            'task_id': 1,
            'address': '127.0.0.1',
            'team_id': 1,
            'team_name': 'test',
            'current_round_id': 1,
            'variant_id': 0,
            'timeout': 30000,
            'round_length': 120,
            'task_chain_id': '',
        }
        flag = 'FLAG{TESTFLAG}'

        # whatever you want to test
        # r'''
        task = PutflagCheckerTaskMessage(flag=flag, **params)
        put_response = await self.run(task)
        task = GetflagCheckerTaskMessage(flag=flag, related_round_id=1, **params)
        await self.run(task)
        task = ExploitCheckerTaskMessage(flag_regex=r'FLAG\{.+?\}',
                                         flag_hash=sha256(flag.encode()).hexdigest(),
                                         attack_info=put_response.attack_info,
                                         **params)
        await self.run(task)
        # '''

        if params['variant_id'] < 2:
            await self.run(PutnoiseCheckerTaskMessage(**params))
            await self.run(GetnoiseCheckerTaskMessage(related_round_id=1, **params))
            await self.run(HavocCheckerTaskMessage(**params))

        self.report()

    async def demo_tick(self, tick: int, with_exploits: bool = False) -> None:
        params = {
            'task_id': tick * 1000,
            'address': '127.0.0.1',
            'team_id': 1,
            'team_name': 'test',
            'current_round_id': tick,
            # 'variant_id': 0,
            'timeout': 30000,
            'round_length': 60,
            'task_chain_id': '',
        }
        flag_variants = 3
        noise_variants = 2
        havoc_variants = 2
        exploit_variants = 4
        flags = [f'FLAG{{testflag{tick}{v}}}' for v in range(flag_variants)]

        # store flags/noises
        tasks = []
        for v in range(flag_variants):
            tasks.append(self.run(PutflagCheckerTaskMessage(flag=flags[v], variant_id=v, **params)))
        for v in range(noise_variants):
            tasks.append(self.run(PutnoiseCheckerTaskMessage(variant_id=v, **params)))
        put_responses = await asyncio.gather(*tasks)

        # retrieve flags/noises + havoc
        tasks = []
        for v in range(flag_variants):
            tasks.append(self.run(GetflagCheckerTaskMessage(flag=flags[v], related_round_id=tick, variant_id=v, **params)))
        for v in range(noise_variants):
            tasks.append(self.run(GetnoiseCheckerTaskMessage(related_round_id=tick, variant_id=v, **params)))
        for v in range(havoc_variants):
            tasks.append(self.run(HavocCheckerTaskMessage(variant_id=v, **params)))
        await asyncio.gather(*tasks)

        # exploits
        if with_exploits:
            tasks = []
            for v in range(exploit_variants):
                flag_index = v % flag_variants
                tasks.append(self.run(ExploitCheckerTaskMessage(flag_regex=r'FLAG\{.+?\}',
                                                                flag_hash=sha256(flags[flag_index].encode()).hexdigest(),
                                                                attack_info=put_responses[flag_index].attack_info,
                                                                variant_id=v, **params)))
            await asyncio.gather(*tasks)

        self.report()

    async def demo_many(self, rng: Iterable[int]) -> None:
        errors = []
        times = []
        try:
            for tick in rng:
                t = time.monotonic()
                await self.demo_tick(tick)
                dt = time.monotonic() - t
                for t, r in self.responses:
                    if "'OK'" not in str(r):
                        errors.append((tick, f'{t.method.name} {t.variant_id} {r}'))
                self.clear()
                logging.info(f'tick {tick}: {dt:.3f} s')
                times.append((tick, dt))
                with open('times.csv', 'a+') as f:
                    f.write(f'{tick},{dt*1000:.0f}\n')
        finally:
            logging.info(f'{len(errors)} failed requests:')
            for tick, e in errors:
                logging.info(f'tick={tick} {e}')
            if len(times) > 0:
                dts = [dt for _, dt in times]
                logging.info(f'Times per tick: {min(dts):.3f}s - {max(dts):.3f} (avg. {sum(dts) / len(dts):.3f}s)')
                #with open('times.csv', 'a+') as f:
                #    f.write(''.join(f'{tick},{dt}\n' for tick, dt in times))


async def main() -> None:
    await DemoRunner.setup()
    # await DemoRunner().demo_tick(1, with_exploits=True)
    await DemoRunner().demo_many(range(1, 1001))


if __name__ == '__main__':
    asyncio.run(main())
