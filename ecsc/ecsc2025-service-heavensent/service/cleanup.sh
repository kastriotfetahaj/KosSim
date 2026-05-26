#!/bin/bash

for x in experiment op gs; do
	find /service/data/$x -type f -cmin +30 -delete
done
