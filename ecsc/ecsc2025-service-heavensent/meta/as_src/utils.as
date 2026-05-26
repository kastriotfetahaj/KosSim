#include "sdr.as"

const string[] HEX_ALPHA = {
    "0", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", "a", "b", "c", "d", "e", "f"
};

string hex(uint64 val, uint8 size) {
    string ret = "";
    for (uint i = 0; i < size; i++) {
		ret = HEX_ALPHA[(val & 0xff) & 0xf] + ret;
		ret = HEX_ALPHA[(val & 0xff) >> 4] + ret;
        val >>= 8;
    }
    return ret;
}

string hexlify(const array<int> &in arr) {
	string ret = "";
	for (uint i = 0; i < arr.length(); i++) {
		ret += hex(arr[i], 1);
	}
	return ret;
}

void print_arr(array<int> &in arr) {
    for (uint i = 0; i < arr.length(); i++) {
        print(hex(arr[i], 1));
    }
    print("\n");
}

void pack(array<int> &inout arr, uint64 val, int size, int offset) {
    for (int i = size - 1; i >= 0; i--) {
        arr[i + offset] = val & 0xff;
        val >>= 8;
    }
}

uint64 unpack(array<int> &in arr, int offset, int size) {
    uint64 ret = 0;
    for (int i = offset; i < offset + size; i++) {
        ret <<= 8;
        ret |= arr[i];
    }
    return ret;
}

array<int> memslice(array<int> &in src, uint64 offset, uint64 len) {
    array<int> ret(len);
    if (offset + len > src.length()) {
        return ret;
    }

    for (uint i = 0; i < len; i++) {
        ret[i] = src[offset + i];
    }

    return ret;
}

string format_arr(array<float> &in arr)
{
    string result = "";
    result += "[";
    for (int i = 0; i < int(arr.length()); ++i)
    {
        result += arr[i] + ", ";
    }
    result += " ]";
    return result;
}

string format_arr(array<complex> &in arr)
{
    string result = "";
    result += "[";
    for (int i = 0; i < int(arr.length()); ++i)
    {
        result += "{r=" + arr[i].r + ", i=" + arr[i].i + "}, ";
    }
    result += " ]";
    return result;
}

void assert(bool cond, string msg)
{
    if (!cond)
    {
        print("AngelScript assertion failed: " + msg + "\n");
        // Exit in a way that gets us a stack trace
        // TODO: should do this with an API call honestly.
        array<int> f;
        f[0] = 0;
    }
}