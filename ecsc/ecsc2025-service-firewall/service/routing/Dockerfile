ARG ETHTOOL_VERSION=6.15
ARG IPROUTE2_VERSION=6.16.0
ARG LIBCAP2_VERSION=2.76

FROM alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1 AS base-builder
RUN apk add --no-cache bash bison flex gcc libmnl-static libmnl-dev make musl-dev wget


FROM base-builder AS ethtool-builder
ARG ETHTOOL_VERSION
RUN wget https://www.kernel.org/pub/software/network/ethtool/ethtool-${ETHTOOL_VERSION}.tar.xz && \
    tar -xf ethtool-${ETHTOOL_VERSION}.tar.xz && \
    rm ethtool-${ETHTOOL_VERSION}.tar.xz && \
    mv ethtool-${ETHTOOL_VERSION} ethtool
WORKDIR /ethtool/
RUN ./configure LDFLAGS=-static && \
    make -j


FROM base-builder AS iproute2-builder
ARG IPROUTE2_VERSION
RUN wget https://mirrors.edge.kernel.org/pub/linux/utils/net/iproute2/iproute2-${IPROUTE2_VERSION}.tar.xz && \
    tar -xf iproute2-${IPROUTE2_VERSION}.tar.xz && \
    rm iproute2-${IPROUTE2_VERSION}.tar.xz && \
    mv iproute2-${IPROUTE2_VERSION} iproute2
WORKDIR /iproute2/
RUN make -j SHARED_LIBS=n LDFLAGS=-static


FROM base-builder AS libcap2-builder
ARG LIBCAP2_VERSION
RUN wget https://www.kernel.org/pub/linux/libs/security/linux-privs/libcap2/libcap-${LIBCAP2_VERSION}.tar.xz && \
    tar -xf libcap-${LIBCAP2_VERSION}.tar.xz && \
    rm libcap-${LIBCAP2_VERSION}.tar.xz && \
    mv libcap-${LIBCAP2_VERSION} libcap
WORKDIR /libcap/
RUN make GOLANG=no DYNAMIC=no LIBCSTATIC=yes


FROM scratch
WORKDIR /sbin/
COPY --from=ethtool-builder  --chown=root:root --chmod=0500 /ethtool/ethtool    ethtool
COPY --from=iproute2-builder --chown=root:root --chmod=0500 /iproute2/ip/ip     ip
COPY --from=libcap2-builder  --chown=root:root --chmod=0500 /libcap/progs/capsh capsh
COPY --chown=root:root --chmod=0500 routing.sh routing
