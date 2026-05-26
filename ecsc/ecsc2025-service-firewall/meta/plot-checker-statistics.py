#!/usr/bin/env python3
"""
script to plot the statstics from a checker loadtest with some filters

examples:
    print all stats
    plot-checker-statistics.py stats.csv

    print only variant 0 and 1 of for getflag and putflag
    plot-checker-statistics.py stats.csv -o getflag -o putflag -v 0 -v 1
"""

import argparse
import csv
import collections
import matplotlib.pyplot as plt

from pathlib import Path

default_operations = ["putflag", "putnoise", "getflag", "getnoise", "havoc", "exploit"]

parser = argparse.ArgumentParser(description="plot checker loadtest timings")
parser.add_argument("stats_file", type=Path, help="CSV file with the checker timings")
parser.add_argument("--max", action="store_true", help="Plot maximum instead of average over repeats")
parser.add_argument("-o", "--operations", action="append", default=[], help=f"The operations to plot, default: {default_operations}")
parser.add_argument("-v", "--variants", action="append", default=[], help="The variants to plot, default: all")
args = parser.parse_args()

if not args.operations:
    operations = default_operations
else:
    operations = args.operations

rounds = []
variants = collections.defaultdict(lambda: 0)
max_repeats = collections.defaultdict(lambda: 0)

with open(args.stats_file, newline="") as f:
    reader = csv.reader(f)
    # skipp header
    next(reader)
    last_round_id = None
    round = {}

    for row in reader:
        round_id, operation, variant_id, repeat, team, time_taken = row

        # save last round
        if round_id != last_round_id:
            if last_round_id is not None:
                rounds.append(round)
                round = {}
            last_round_id = round_id

        if operation == "exploit":
            repeat = team
            if repeat == "":
                repeat = 0

        variant_id = int(variant_id)
        repeat = int(repeat)

        if variants[operation] < variant_id + 1:
            variants[operation] = variant_id + 1
        if max_repeats[operation] < repeat + 1:
            max_repeats[operation] = repeat + 1

        round[(operation, variant_id, repeat)] = float(time_taken)

    rounds.append(round)

for operation in operations:
    if args.variants:
        variants[operation] = list(map(int, args.variants))
    else:
        variants[operation] = list(range(variants[operation]))

plot_max = True
plot_data = []

for round in rounds:
    plots = []
    for operation in operations:
        for variant_id in variants[operation]:
            repeats = []
            for repeat in range(max_repeats[operation]):
                repeats.append(round.get((operation, variant_id, repeat), 0))
            if plot_max:
                time_taken = max(repeats)
            else:
                time_taken = sum(repeats) / max_repeats[operation]
            plots.append(time_taken)
    plot_data.append(plots)

legends = []
for operation in operations:
    for variant_id in variants[operation]:
        print(variant_id)
        legends.append(f"{operation}-{variant_id:02}")

ax = plt.subplot()
pl = ax.plot(plot_data, label=legends)
legend = ax.legend()
plt.ylabel('time_taken')
plt.show()
