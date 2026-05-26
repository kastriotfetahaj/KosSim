//! This file contains all the conversion and handeling functions for everything protocol related.
//! Every packet must start with the ground_station_id followed by a byte to indicate which function
//! is to be executed. Unless noted otherwise, all functionality requires the ground station to be
//! tied to an operator.

#include "sdr.as"
#include "utils.as"

const int TYPE_OFFSET = 0;
const int MESSAGEID_OFFSET = 1;
const int GSID_OFFSET = 3;
const int ERROR_OFFSET = 3;

// Define the size of the frame here and dependend on the FRAME_SYMBOL_COUNT so we only have to
// change it in the "sdr.as".
const int FRAME_SIZE = FRAME_SYMBOL_COUNT / 2;

/// All error codes that can be send back as a response
enum ErrorCode {
    /// Catchall
    UnknownError = 0xff,

    /// Everything worked
    Success = 0,

    /// When registering for an operator with an ID that does not exist
    OperatorDoesNotExist,
    /// When sending a request that requires an operator id but the one provided is wrong
    OperatorIDMissing,
    /// When regestering for an operator and the operator secret is wrong
    OperatorSecretWrong,

    /// When sending a packet with a ground station id that does not exist
    GroundStationDoesNotExist,
    /// When sending a packet without the ground station id
    GroundStationIDMissing,
    /// When sending a packet which needs a password for the ground station and that password is 
    /// wrong
    GroundStationPasswordWrong,
    /// When the ground station is not allowed to perform the requested action
    NotAuthorized,

    /// When the experiment id does not exist
    ExperimentDoesNotExist,

    /// When sending a broken function id
    BrokenRequest
}

/// SatelliteFunction encodes all functionality of the satellite
enum SatelliteFunction {
    /// ErroroneousFunction indicates a wrong function id and should never be used.
    ErroroneousFunction = 0xff,

    /// RegisterOperator is a functionality to create a new operator. This also automatically
    /// registers the ground station for the operator.
    /// 
    /// Request: |0<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|
    /// Reply: |0x80<uint8>|MessageID<uint16>|ErrorCode<uint8>|OPID<uint64>|OPSecret<uint64>|
    RegisterOperator = 0,

    /// RegisterAtOperator registers a ground station at an operator iff the provided operator key
    /// is correct. If not an error is returned.
    ///
    /// Request: |1<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|OPID<uint64>|OPSecret<uint64>|
    /// Reply: |0x81<uint8>|MessageID<uint16>|ErrorCode<uint8>|
    RegisterAtOperator,

    /// RegisterGroundStation generates a random ID for the ground station and creates a profile for
    /// it on disk.
    ///
    /// Request: |2<uint8>|MessageID<uint16>|Password<uint64>|
    /// Reply: |0x82<uint8>|MessageID<uint16>|ErrorCode<uint8>|GSID<uint64>|
    RegisterGroundStation,

    /// SetBroadcastMessage records a message for all ground stations registered with the same
    /// operator.
    ///
    /// Request: |3<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|Slot<uint8>|Message<char[32]>|
    /// Reply: |0x83<uint8>|MessageID<uint16>|ErrorCode<uint8>|
    SetBroadcastMessage,

    /// ReadBroadcastMessage sends, iff the password is correct and the ground station is authorized
    /// to read the broadcast, the message saved in the slot from a different ground station.
    ///
    /// Request: |4<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|OGSID<uint64>|Slot<uint8>|
    /// Reply: |0x84<uint8>|MessageID<uint16>|ErrorCode<uint8>|Message<char[32]>|
    ReadBroadcastMessage,

    /// RequestChunkAmount sends, given the experiment id and other groundstation id, the amount of
    /// chunks this experiment data has to be split into.
    ///
    /// Request: |5<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|OGSID<uint64>|EID<uint64>|
    /// Response: |0x85<uint8>|MessageID<uint16>|ErrorCode<uint8>|NumberChunks<uint8>|
    RequestChunkAmount,

    /// RequestDownlink can send, given the measurement ID, sends back down the data of a
    /// measurement. The first reply packet contains the errorcode, the tag is applicable and the
    /// amount of following packets.
    ///
    /// The request should start with a chunk id of -1, which indicates metadata for the encrypted
    /// data. Starting at 0 all chunks are then parts of the requested data.
    ///
    /// Request: |6<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|EID<uint64>|ChunkID<uint32>|
    /// Reply: |0x86<uint8>|MessageID<uint16>|ErrorCode<uint8>|ChunkID<int32>|Data[ChunkID*32:(N+1)*32]<char[32]>|
    RequestDownlink,

    /// RequestAssistedDownlink triggeres the "assisted download" operation. Here the satellite 
    /// sends the encrypted data to the requesting ground station together with a tag to identify
    /// the recipient. The requesting ground station can then send the data together with the tag to
    /// the assisted ground station, which in turn can contact the satellite with the tag and
    /// receive the decryption key.
    ///
    /// The request should start with a chunk id of -1, which indicates metadata for the encrypted
    /// data. Starting at 0 all chunks are then parts of the requested data.
    ///
    /// Request: |7<uint8>|MessageID<uint16>|GSID<uint64>|OGSID<uint64>|EID<uint64>|ChunkID<int32>|
    /// Reply: |0x87<uint8>|MessageID<uint16>|ErrorCode<uint8>|ChunkID<int32>|Data[ChunkID*32:(ChunkID+1)*32]<char[32]>|
    RequestAssistedDownlink,

    /// RequestAssistedDownlinkKey returns, provided the correct tag and authentication, the key to
    /// decrypt the data identified by the tag.
    ///
    /// Request: |8<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|EID<uint64>|
    /// Reply: |0x88<uint8>|MessageID<uint16>|ErrorCode<uint8>|DecKey<char[16]>|
    RequestAssistedDownlinkKey,

    /// UsePayload creates a fake mesurement from the satellite (be it an image, floats, who 
    /// knows).
    ///
    /// Request: |9<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|
    /// Reply: |0x89<uint8>|MessageID<uint16>|ErrorCode<uint8>|EID<uint64>|
    UsePayload,

    /// TagExperiment appends the provided data to the tag of the experiment, which will be 
    /// included in the downlink in the end.
    ///
    /// Request: |10<uint8>|MessageID<uint16>|GSID<uint64>|Password<uint64>|EID<uint64>|Tag<char[32]>|
    /// Reply: |0x8a<uint8>|MessageID<uint16>|ErrorCode<uint8>|
    TagExperiment,

    /// This is to mark the last satellite function
    _NOT_USED,

    /// Response IDs for the corresponding requests
    RegisterOperatorResponse = 0x80,
    RegisterAtOperatorResponse,
    RegisterGroundStationResponse,
    SetBroadcastMessageResponse,
    ReadBroadcastMessageResponse,
    RequestChunkAmountResponse,
    DownlinkChunkResponse,
    DownlinkAssistedChunkResponse,
    AssistedDownlinkKeyResponse,
    UsePayloadResponse,
    TagExperimentResponse,

    /// Request IDs for the chunked data
}

uint64 ground_station_id(const array<int> &in frame) {
    return unpack(frame, GSID_OFFSET, 8);
}

uint16 message_id(const array<int> &in frame) {
    return unpack(frame, MESSAGEID_OFFSET, 2);
}

array<int> empty_reply(uint16 message_id, uint64 id) {
    array<int> reply(FRAME_SIZE, 0);
    pack(reply, uint8(ErroroneousFunction), 1, TYPE_OFFSET);
    pack(reply, uint8(UnknownError), 1, ERROR_OFFSET);
    pack(reply, message_id, 2, MESSAGEID_OFFSET);
    return reply;
}

SatelliteFunction get_function(const array<int> &in frame) {
    int id = frame[TYPE_OFFSET];
    if (id < 0 || id > _NOT_USED) {
        return ErroroneousFunction;
    }
    return SatelliteFunction(id);
}
