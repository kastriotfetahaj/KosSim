FROM ubuntu:24.04@sha256:353675e2a41babd526e2b837d7ec780c2a05bca0164f7ea5dbbd433d21d166fc
ENV DEBIAN_FRONTEND=noninteractive
ADD https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/d15cf12b26395b857b24fba223b108aff1c91b26/repro-sources-list.sh /var/lib/repro-sources-list.sh
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  bash /var/lib/repro-sources-list.sh && \
  apt-get update && \
  apt-get install -y python3 python3-pip git cmake libboost-dev libboost-date-time-dev inetutils-ping build-essential clang libspdlog-dev pkg-config libgmp10-dev pybind11-dev doxygen python3-dev libboost-program-options-dev libboost-system-dev libboost-regex-dev libboost-thread-dev libsndfile1-dev libgsl-dev libfftw3-dev && \
  rm -rf /var/lib/repro-sources-list.sh /var/log/* /var/cache/ldconfig/aux-cache

RUN echo "/usr/lib/python3/dist-packages" > /usr/local/lib/python3.12/dist-packages/gr.pth
RUN python3 -m pip install --break-system-packages --upgrade construct==2.10.70 requests==2.32.5 mako==1.3.10 packaging==25.0 pygccxml==3.0.2 numpy==2.3.3 scipy==1.16.2 pyzmq==27.1.0

WORKDIR /git
RUN git clone --recursive https://github.com/gnuradio/volk.git

WORKDIR /git/volk
RUN git checkout v3.2.0

WORKDIR /git/volk/build
RUN cmake -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python3 ../
RUN make -j`nproc` && make install && make clean
RUN ldconfig

WORKDIR /git
RUN git clone https://github.com/gnuradio/gnuradio.git

WORKDIR /git/gnuradio/
RUN git checkout v3.10.10.0

WORKDIR /git/gnuradio/build
RUN cmake -DENABLE_GR_ANALOG=ON -DENABLE_GR_FILTER=ON -DENABLE_GR_BLOCKS=ON -DENABLE_GR_FFT=ON -DENABLE_GR_DIGITAL=ON -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python3 ../
RUN make -j`nproc` && make install && make clean
RUN ldconfig

WORKDIR /git
RUN git clone https://github.com/daniestevez/gr-satellites.git

WORKDIR /git/gr-satellites
RUN git checkout v5.8.0

WORKDIR /git/gr-satellites/build
RUN cmake ..
RUN make -j`nproc` && make install && make clean
RUN ldconfig
