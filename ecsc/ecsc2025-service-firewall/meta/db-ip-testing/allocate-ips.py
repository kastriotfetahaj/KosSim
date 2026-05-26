#!/usr/bin/env python3
import psycopg
import multiprocessing

PASSWORD = "authentication"
WORKERS = 5
ALLOCATIONS_PER_WORKER = 5000
SPLIT = True
IPv4_RANGE = ["10.0.1.0", "10.255.255.254"]
IPv6_RANGE = ["fd00:ec5c::1:0", "fd00:ec5c::ffff:ffff:fffe"]

def init_pool(event: multiprocessing.Event):
    global error_event
    error_event = event


def query_combined(cursor):
    cursor.execute('SELECT ip_allocate_from_range(%s, %s), ip_allocate_from_range(%s, %s)', (
        *IPv4_RANGE, *IPv6_RANGE
    ))
    row = cursor.fetchone()
    if row is None:
        raise Exception('Database did not return allocated IP addresses')

    return row

def query_split(cursor):
    cursor.execute('SELECT ip_allocate_from_range(%s, %s)', IPv4_RANGE)
    row = cursor.fetchone()
    if row is None:
        raise Exception('Database did not return allocated IP addresses')
    ipv4, = row

    cursor.execute('SELECT ip_allocate_from_range(%s, %s)', IPv6_RANGE)
    row = cursor.fetchone()
    if row is None:
        raise Exception('Database did not return allocated IP addresses')
    ipv6, = row

    return ipv4, ipv6


def allocate_ips(idx: int, n: int):
    interval = ALLOCATIONS_PER_WORKER // 100
    try:
        with psycopg.connect(f'postgresql://authentication:{PASSWORD}@127.0.0.1:5432/firewall?sslmode=prefer') as db:
            with db.cursor() as cursor:
                for i in range(n):
                    if error_event is not None and error_event.is_set():
                        break
                    query = query_split if SPLIT else query_combined
                    ipv4, ipv6 = query(cursor)
                    db.commit()

                    if ipv4 is None or ipv6 is None:
                        print(f"worker {idx} need to retry with addresses: {ipv4} {ipv6}")
                        cursor.execute('LOCK TABLE ip_ranges IN ACCESS EXCLUSIVE MODE')
                        if ipv4 is None:
                            cursor.execute('SELECT ip_allocate_from_range(%s, %s)', IPv4_RANGE)
                            row = cursor.fetchone()
                            if row is None:
                                db.rollback()
                                raise Exception('Database did not return allocated IP addresses')
                            ipv4, = row

                        if ipv6 is None:
                            cursor.execute('SELECT ip_allocate_from_range(%s, %s)', IPv6_RANGE)
                            row = cursor.fetchone()
                            if row is None:
                                db.rollback()
                                raise Exception('Database did not return allocated IP addresses')
                            ipv6, = row
                        db.commit()

                    if ipv4 is None:
                        raise Exception('No IPv4 address available')

                    if ipv6 is None:
                        raise Exception('No IPv6 address available')

                    #print(f"worker: {idx}, {ipv4}, {ipv6}")
                    if i % interval == 0:
                        print(f"worker {idx}: {i}/{n}")
    except Exception as e:
        if error_event is not None:
            error_event.set()
        raise e

if WORKERS == 1:
    error_event = None
    allocate_ips(1, ALLOCATIONS_PER_WORKER)
else:
    error_event = multiprocessing.Event()
    with multiprocessing.Pool(WORKERS, initializer=init_pool, initargs=(error_event,)) as pool:
        results = [pool.apply_async(allocate_ips, (i, ALLOCATIONS_PER_WORKER)) for i in range(WORKERS)]
        print([res.get() for res in results])
