#include "utils.as"
#include "files.as"

array<uint64> secret;
void crypto_init()
{
    // Load secret
    file secret_file;
    int r = secret_file.open("data/secret.bin", "r");
    assert(r >= 0, "failed to open secret.bin");
    for (int i = 0; i < 2; ++i)
    {
        secret.insertLast(secret_file.readUInt(8));
    }
}

void permute_columns(array<uint64> &inout data)
{
    int n = data.length();

    // Permutation step using coprime multiplication
    for (int i = 0; i < n; ++i)
    {
        data[i] *= 0x46e9b5e2c310c387;
    }
}

void lfsr_shift(array<uint64> &inout data)
{
    int n = data.length();

    // Shift part of LFSR
    for (int i = n - 1; i >= 0; --i)
    {
        // Apply shifted out bit to previous element if not first
        if (i < n - 1)
        {
            data[i + 1] |= (data[i] & 1) << 63;
        }
        data[i] >>= 1;
    }
}

void lfsr_feedback(array<uint64> &inout data, array<uint64> generator)
{
    int n = data.length();

    // Feedback part of LFSR
    // LSB set?
    int lsb = data[n - 1] & 1;
    if (lsb != 0)
    {
        for (int i = 0; i < n; ++i)
        {
            data[i] ^= generator[i];
        }
    }
}

array<uint64> MIXER_POLY = {
    // TODO: validate that this is a good polynomial
    0x8932d55b4ff96cb0, 0xa24db1aed50ef472, 0x25548fcf87afd090, 0x4fdb809199b0410c, 0xdca2478dd59ff050
};
int MIXER_ROUNDS = 320;

void mix_bits(array<uint64> &inout data)
{
    assert(data.length() == MIXER_POLY.length(), "mixer data/generator length mismatch");
    for (int i = 0; i < MIXER_ROUNDS; ++i)
    {
        permute_columns(data);
        lfsr_shift(data);
        lfsr_feedback(data, MIXER_POLY);
    }
}

void gen_iv(array<int> &inout iv, int chunk)
{
    assert(EXPERIMENT_CHUNK_SIZE % 16 == 0, "experiment chunk size is not multiple of AES block size");
    int blocks_per_chunk = EXPERIMENT_CHUNK_SIZE / 16;
    pack(iv, chunk * blocks_per_chunk, 12, 4);
}

void gen_key(array<int> &inout key, uint64 ex_id, uint64 gs_id)
{
    uint64 gs_pw = 0;
    bool r = gs_get_password(gs_id, gs_pw);
    assert(r, "failed to get G/S password");

    array<uint64> mixer;
    mixer.insertLast(secret[0]);
    mixer.insertLast(secret[1]);
    mixer.insertLast(gs_id);
    mixer.insertLast(gs_pw);
    mixer.insertLast(ex_id);
    mix_bits(mixer);

    // Extract how much key material is wanted
    assert(key.length() % 8 == 0, "requested key length is not multiple of 64 bits");
    assert(key.length() / 8 <= mixer.length(), "requested key length is larger than available entropy");
    for (int i = 0; i < int(key.length()) / 8; ++i)
    {
        pack(key, mixer[i], 8, i * 8);
    }
}