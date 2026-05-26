#include "utils.as"
#include "random.as"
#include "crypto.as"

const string data_dir = "/service/data/";
const string gs_dir = data_dir + "gs/";
const string op_dir = data_dir + "op/";
const string ex_dir = data_dir + "experiment/";

const uint64 MESSAGE_COUNT = 256;
const uint64 MESSAGE_SIZE = 32;

const uint64 F_PASSWORD_OFFSET = 0;
const uint64 F_MESSAGE_OFFSET = F_PASSWORD_OFFSET + 8;
const uint64 F_OP_ID_OFFSET = MESSAGE_SIZE * MESSAGE_COUNT + F_MESSAGE_OFFSET;

const uint64 EXPERIMENT_CHUNK_SIZE = 32;

bool gs_exists(uint64 gs_id) {
    filesystem fs;
    return fs.getSize(gs_dir + hex(gs_id, 8)) > -1;
}

bool op_exists(uint64 op_id) {
    filesystem fs;
    return fs.getSize(op_dir + hex(op_id, 8)) > -1;
}

bool ex_exists(uint64 experiment_id, uint64 gs_id) {
    filesystem fs;
    return fs.getSize(ex_dir + hex(gs_id, 8) + "/" + hex(experiment_id, 8)) > -1;
}

bool gs_create(uint64 gs_id, uint64 password) {
    string file_path = gs_dir + hex(gs_id, 8);
    file f;
    filesystem fs;

    if (f.open(file_path, "w") < 0) {
        return false;
    }

    if (f.writeUInt(password, 8) <= 0) {
        f.close();
        fs.deleteFile(file_path);
        return false;
    }

    // Fill broadcast slots
    string empty_message = "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0";
    for (int i = 0; i < 256; i++) {
        if (f.writeString(empty_message) != 32) {
            f.close();
            fs.deleteFile(file_path);
            return false;
        }
    }

    // Fill operator ID
    if (f.writeUInt(0, 8) <= 0) {
        f.close();
        fs.deleteFile(file_path);
        return false;
    }

    f.close();
    return true;
}

bool gs_get_password(uint64 gs_id, uint64 &out password) {
    string file_path = gs_dir + hex(gs_id, 8);
    file f;

    if (f.open(file_path, "r") < 0)
        return false;

    if (f.setPos(F_PASSWORD_OFFSET) < 0) {
        f.close();
        return false;
    }

    password = f.readUInt(8);
    f.close();
    return true;
}

bool gs_check(uint64 gs_id, uint64 password) {
    uint64 expected_password;
    bool ret = gs_get_password(gs_id, expected_password);
    if (!ret)
    {
        return false;
    }

    return (password == expected_password);
}

bool gs_check_same_op(uint64 gs_id, uint64 ogs_id) {
    string gs_file_path = gs_dir + hex(gs_id, 8);
    string ogs_file_path = gs_dir + hex(ogs_id, 8);
    file gs_f;
    file ogs_f;

    if (gs_f.open(gs_file_path, "r") < 0)
        return false;

    if (gs_f.setPos(F_OP_ID_OFFSET) < 0) {
        gs_f.close();
        return false;
    }

    if (ogs_f.open(ogs_file_path, "r") < 0) {
        gs_f.close();
        return false;
    }

    if (ogs_f.setPos(F_OP_ID_OFFSET) < 0) {
        gs_f.close();
        ogs_f.close();
        return false;
    }

    bool ret = gs_f.readUInt(8) == ogs_f.readUInt(8);
    gs_f.close();
    ogs_f.close();
    return ret;
}

bool gs_set_message(uint64 gs_id, int slot, array<int> message) {
    string file_path = gs_dir + hex(gs_id, 8);
    file f;

    if (f.open(file_path, "r+") < 0)
        return false;

    if (f.setPos(F_MESSAGE_OFFSET + MESSAGE_SIZE * slot) < 0) {
        f.close();
        return false;
    }

    for (uint i = 0; i < MESSAGE_SIZE; i++) {
        if (i >= message.length()) {
            if (f.writeUInt(0, 1) < 0) {
                return false;
            };
        } else {
            if (f.writeUInt(message[i], 1) < 0) {
                return false;
            }
        }
    }

    f.close();
    return true;
}

bool gs_get_message(uint64 gs_id, int slot, array<int> &inout message, uint64 offset) {
    string file_path = gs_dir + hex(gs_id, 8);
    file f;

    if (offset + MESSAGE_SIZE > message.length()) {
        return false;
    }

    if (f.open(file_path, "r+") < 0)
        return false;

    if (f.setPos(F_MESSAGE_OFFSET + MESSAGE_SIZE * slot) < 0) {
        f.close();
        return false;
    }

    for (uint i = 0; i < MESSAGE_SIZE; i++) {
        message[offset + i] = f.readUInt(1);
    }

    f.close();
    return true;
}

bool op_create(uint64 op_id, uint64 op_secret) {
    string file_path = op_dir + hex(op_id, 8);
    file f;
    filesystem fs;

    if (f.open(file_path, "w") < 0)
        return false;

    if (f.writeUInt(op_secret, 8) <= 0) {
        f.close();
        fs.deleteFile(file_path);
        return false;
    }

    f.close();
    return true;
}

bool op_check(uint64 op_id, uint64 op_secret) {
    string file_path = op_dir + hex(op_id, 8);
    file f;

    if (f.open(file_path, "r") < 0)
        return false;

    bool ret = f.readUInt(8) == op_secret;
    f.close();
    return ret;
}

bool op_register_gs(uint64 op_id, uint64 gs_id) {
    string file_path = gs_dir + hex(gs_id, 8);
    file f;

    if (f.open(file_path, "r+") < 0)
        return false;

    if (f.setPos(F_OP_ID_OFFSET) < 0) {
        f.close();
        return false;
    }

    if (f.writeUInt(op_id, 8) <= 0) {
        f.close();
        return false;
    }

    f.close();
    return true;
}

bool ex_create(uint64 experiment_id, uint64 gs_id, array<int> &in frame) {
    filesystem fs;

    string gs_path = ex_dir + hex(gs_id, 8) + "/";

    if (!fs.isDir(gs_path)) {
        fs.makeDir(gs_path);
    }

    string file_path = gs_path + hex(experiment_id, 8);
    file f;

    if (f.open(file_path, "w") < 0)
        return false;

    if (f.writeUInt(gs_id, 8) <= 0) {
        f.close();
        fs.deleteFile(file_path);
        return false;
    }

    for (int i = 0; i < 10; i++) {
        if (f.writeUInt(rand_u64(), 8) <= 0) {
            f.close();
            fs.deleteFile(file_path);
            return false;
        }
    }

    return true;
}

uint64 ex_size(uint64 experiment_id, uint64 gs_id) {
    filesystem fs;
    return fs.getSize(ex_dir + hex(gs_id, 8) + "/" + hex(experiment_id, 8));
}

bool ex_check(uint64 experiment_id, uint64 gs_id) {
    string gs_path = ex_dir + hex(gs_id, 8) + "/";
    string file_path = gs_path + hex(experiment_id, 8);
    file f;

    if (f.open(file_path, "r") < 0)
        return false;

    bool ret = f.readUInt(8) == gs_id;
    f.close();
    return ret;
}

bool ex_tag(uint64 experiment_id, uint64 gs_id, array<int> &in data) {
    string gs_path = ex_dir + hex(gs_id, 8) + "/";
    string file_path = gs_path + hex(experiment_id, 8);
    file f;

    if (f.open(file_path, "a") < 0)
        return false;

    for (uint i = 0; i < data.length(); i++) {
        if (f.writeUInt(uint8(data[i]), 1) <= 0)
            return false;
    }

    return true;
}

bool ex_get_chunk(uint64 experiment_id, uint64 gs_id, int32 chunk, array<int> &inout ret, bool is_assisted) {
    string gs_path = ex_dir + hex(gs_id, 8) + "/";
    string file_path = gs_path + hex(experiment_id, 8);
    uint64 size = ex_size(experiment_id, gs_id);
    file f;

    f.open(file_path, "r");

    f.setPos(8 + chunk * EXPERIMENT_CHUNK_SIZE);
    uint64 file_offset = 8 + chunk * EXPERIMENT_CHUNK_SIZE;
    uint64 idx = 0;
    array<int> data(EXPERIMENT_CHUNK_SIZE, 0);

    while (file_offset < size && idx < EXPERIMENT_CHUNK_SIZE) {
        data[idx] = uint8(f.readUInt(1));
        file_offset++;
        idx++;
    }

    if (is_assisted)
    {
        array<int> iv(16);
        gen_iv(iv, chunk);

        array<int> key(16);
        gen_key(key, experiment_id, gs_id);

        data = encrypt(data, iv, key);
    }

    for (uint i = 0; i < data.length(); i++)
    {
        pack(ret, data[i], 1, ERROR_OFFSET + 5 + i);
    }

    f.close();
    return true;
}
