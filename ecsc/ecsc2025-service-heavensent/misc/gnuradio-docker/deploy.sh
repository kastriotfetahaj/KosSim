#!/bin/bash
docker tag heavensent-gnuradio ci.attacking-lab.com/ecsc2025/service-heavensent/gnuradio
docker login https://ci.attacking-lab.com
docker push ci.attacking-lab.com/ecsc2025/service-heavensent/gnuradio