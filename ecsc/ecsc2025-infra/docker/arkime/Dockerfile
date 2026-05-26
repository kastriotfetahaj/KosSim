FROM ubuntu:22.04 AS build

ENV VERSION=5.3.0

RUN apt-get update && \
    apt-get install -y libwww-perl libjson-perl ethtool libyaml-dev liblua5.4-0 libmaxminddb0 libcurl4 libpcap0.8 libglib2.0-0 libnghttp2-14 libyara8 librdkafka1 curl

ADD --chmod=644 https://www.wireshark.org/download/automated/data/manuf /opt/arkime/etc/oui.txt
ADD --chmod=644 https://www.iana.org/assignments/ipv4-address-space/ipv4-address-space.csv /opt/arkime/etc/ipv4-address-space.csv

WORKDIR /EnoArkime
ADD https://github.com/arkime/arkime/releases/download/v$VERSION/arkime_$VERSION-1.ubuntu2204_amd64.deb .
RUN dpkg -i ./*.deb; apt-get install -fy && rm -rf /var/lib/apt/lists/* && rm *.deb

COPY elasticsearch_init.sh elasticsearch_init.sh
# Allow everyone (including user nobody) to access config files
RUN chmod a+x /opt/arkime /opt/arkime/etc
