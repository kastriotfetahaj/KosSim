#include "utils.as"
#include "protocol.as"
#include "files.as"
#include "logger.as"
#include "random.as"

const int BACKEND_LOG_LEVEL = 2;
logger@ sat_logger = new_logger("bck", BACKEND_LOG_LEVEL);

void handle_register_operator(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(RegisterOperatorResponse), 1, TYPE_OFFSET);
    log_trace(sat_logger, "Handle register operator");

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);

    if (!gs_exists(gs_id)) {
        log_debug(sat_logger, "Ground station " + hex(gs_id, 8) + " does not exist");
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    uint64 op_id = rand_u64();
    while (op_exists(op_id))
        op_id = rand_u64();

    uint64 op_secret = rand_u64();
    if (!op_create(op_id, op_secret)) {
        log_debug(sat_logger, "Could not create operator. ID: " + hex(op_id, 8) + " Secret: " + hex(op_secret, 8));
        return;
    }

    if (!op_register_gs(op_id, gs_id)) {
        log_debug(sat_logger, "Could not register GS " + hex(gs_id, 8) + " with OP " + hex(op_id, 8));
        return;
    }

    log_info(sat_logger, "Registered OPID " + hex(op_id, 8) + " with secret " + hex(op_secret, 8));

    pack(ret, op_id, 8, 4);
    pack(ret, op_secret, 8, 12);

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_register_at_operator(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(RegisterAtOperatorResponse), 1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    uint64 op_id = unpack(frame, 19, 8);
    uint64 op_secret = unpack(frame, 27, 8);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (op_id == 0) {
        pack(ret, uint8(OperatorIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!op_exists(op_id)) {
        pack(ret, uint8(OperatorDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!op_check(op_id, op_secret)) {
        pack(ret, uint8(OperatorSecretWrong), 1, ERROR_OFFSET);
        return;
    }

    if (!op_register_gs(op_id, gs_id)) {
        return;
    }

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_register_ground_station(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(RegisterGroundStationResponse), 1, TYPE_OFFSET);

    uint64 gs_id = rand_u64();
    while (gs_exists(gs_id))
        gs_id = rand_u64();

    uint64 password = unpack(frame, 3, 8);
    if (!gs_create(gs_id, password))
        return;

    pack(ret, gs_id, 8, 4);
    log_info(sat_logger, "Registered GSID " + hex(gs_id, 8) + " with password " + hex(password, 8) + "\n");

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_set_broadcast_message(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(SetBroadcastMessageResponse), 1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    int slot = unpack(frame, 19, 1);
    array<int> message = memslice(frame, 20, MESSAGE_SIZE);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_set_message(gs_id, slot, message)) {
        return;
    }

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_read_broadcast_message(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(ReadBroadcastMessageResponse), 1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    uint64 ogs_id = unpack(frame, 19, 8);
    int slot = unpack(frame, 27, 1);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (ogs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(ogs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check_same_op(gs_id, ogs_id)) {
        pack(ret, uint8(NotAuthorized), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_get_message(ogs_id, slot, ret, ERROR_OFFSET + 1)) {
        return;
    }

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_use_payload(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(UsePayloadResponse), 1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    uint64 experiment_id = rand_u64();
    while (ex_exists(experiment_id, gs_id))
        experiment_id = rand_u64();

    if (!ex_create(experiment_id, gs_id, frame)) {
        return;
    }

    pack(ret, uint64(experiment_id), 8, ERROR_OFFSET + 1);
    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_tag_experiment(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(TagExperimentResponse), 1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    uint64 exp_id = unpack(frame, 19, 8);
    array<int> message = memslice(frame, 27, 32);

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (!ex_exists(exp_id, gs_id)) {
        pack(ret, uint8(ExperimentDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!ex_check(exp_id, gs_id)) {
        pack(ret, uint8(NotAuthorized), 1, ERROR_OFFSET);
        return;
    }

    if (!ex_tag(exp_id, gs_id, message)) {
        return;
    }

    log_debug(sat_logger, "data: " + hexlify(message));

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_request_chunk_amount(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(RequestChunkAmountResponse), 1, TYPE_OFFSET);
    pack(ret, 0xffffffff, 4, ERROR_OFFSET + 1);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    uint64 ogs_id = unpack(frame, 19, 8);
    uint64 exp_id = unpack(frame, 27, 8);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (ogs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(ogs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    log_debug(sat_logger, "OGSID: " + hex(ogs_id, 8) + " EXPID: " + hex(exp_id, 8));
    log_debug(sat_logger, "Exists: " + ex_exists(exp_id,ogs_id));

    if (!ex_exists(exp_id, ogs_id)) {
        pack(ret, uint8(ExperimentDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    pack(ret, uint8((ex_size(exp_id, ogs_id) + EXPERIMENT_CHUNK_SIZE - 1)/EXPERIMENT_CHUNK_SIZE), 1, ERROR_OFFSET + 1);
    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_request_downlink(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(DownlinkChunkResponse),  1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    uint64 exp_id = unpack(frame, 19, 8);
    uint32 chunk = unpack(frame, 27, 4);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (!ex_exists(exp_id, gs_id)) {
        pack(ret, uint8(ExperimentDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    pack(ret, int32(chunk), 4, ERROR_OFFSET + 1);

    if (!ex_get_chunk(exp_id, gs_id, chunk, ret, false)) {
        return;
    }

    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_request_assisted_downlink(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(DownlinkAssistedChunkResponse),  1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 other_gs_id = unpack(frame, 11, 8);
    uint64 exp_id = unpack(frame, 19, 8);
    uint32 chunk = unpack(frame, 27, 4);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(other_gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!ex_get_chunk(exp_id, other_gs_id, chunk, ret, true)) {
        return;
    }

    log_debug(sat_logger, "Num Chunks: " + chunk + "\n");

    pack(ret, int32(chunk), 4, ERROR_OFFSET + 1);
    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

void handle_request_assisted_downlink_key(array<int> &in frame, array<int> &inout ret) {
    pack(ret, uint8(AssistedDownlinkKeyResponse), 1, TYPE_OFFSET);

    uint64 gs_id = unpack(frame, 3, 8);
    uint64 password = unpack(frame, 11, 8);
    uint64 exp_id = unpack(frame, 19, 8);

    if (gs_id == 0) {
        pack(ret, uint8(GroundStationIDMissing), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_exists(gs_id)) {
        pack(ret, uint8(GroundStationDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    if (!gs_check(gs_id, password)) {
        pack(ret, uint8(GroundStationPasswordWrong), 1, ERROR_OFFSET);
        return;
    }

    if (!ex_exists(exp_id, gs_id)) {
        pack(ret, uint8(ExperimentDoesNotExist), 1, ERROR_OFFSET);
        return;
    }

    array<int> key(16);
    gen_key(key, exp_id, gs_id);

    for (int i = 0; i < 16; i++) {
        pack(ret, uint8(key[i]), 1, 4 + i);
    }
    pack(ret, uint8(Success), 1, ERROR_OFFSET);
}

array<int> handle_frame(array<int> &in frame) {
    uint64 gs_id = ground_station_id(frame);
    uint8 func = get_function(frame);

    log_debug(sat_logger, "Function: " + func);
    uint16 ms_id = message_id(frame);
    log_debug(sat_logger, "Message ID: " + ms_id);

    array<int> ret = empty_reply(ms_id, gs_id);

    switch(func) {
        case RegisterOperator:
            handle_register_operator(frame, ret);
            break;
        case RegisterAtOperator:
            handle_register_at_operator(frame, ret);
            break;
        case RegisterGroundStation:
            handle_register_ground_station(frame, ret);
            break;
        case SetBroadcastMessage:
            handle_set_broadcast_message(frame, ret);
            break;
        case ReadBroadcastMessage:
            handle_read_broadcast_message(frame, ret);
            break;
        case UsePayload:
            handle_use_payload(frame, ret);
            break;
        case TagExperiment:
            handle_tag_experiment(frame, ret);
            break;
        case RequestChunkAmount:
            handle_request_chunk_amount(frame, ret);
            break;
        case RequestDownlink:
            handle_request_downlink(frame, ret);
            break;
        case RequestAssistedDownlink:
            handle_request_assisted_downlink(frame, ret);
            break;
        case RequestAssistedDownlinkKey:
            handle_request_assisted_downlink_key(frame, ret);
            break;
        default:
            pack(ret, uint8(BrokenRequest), 1, ERROR_OFFSET);
    }
    return ret;
}

