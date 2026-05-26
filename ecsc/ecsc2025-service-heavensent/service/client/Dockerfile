FROM attackinglab/heavensent-gnuradio

ENV OPENBLAS_THREAD_TIMEOUT=4

RUN python3 -m pip install --break-system-packages PyCryptodome==3.23.0 websocket-client==1.8.0 numpy==2.3.2

WORKDIR /client
COPY *.py .
RUN chmod 0755 ./client.py

ENTRYPOINT [ "python3", "./client.py" ]
