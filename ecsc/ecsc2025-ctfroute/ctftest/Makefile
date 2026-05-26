RUN=uv run
AGENT_DIR=ctftest/agent

.PHONY: all

all: protos

protos:
	${RUN} python -m grpc_tools.protoc --python_out=${AGENT_DIR} --grpc_python_out=${AGENT_DIR} --pyi_out=${AGENT_DIR} -I ./ctftest/protos ./ctftest/protos/ctftest.proto
	sed -i 's/^import ctftest_pb2/import ctftest.agent.ctftest_pb2/' ${AGENT_DIR}/ctftest_pb2_grpc.py