heavensent
============

Authors:
* Liikt
* PistonMiner

Categories:
* rev
* radio/sdr
* cry
* pwn

Overview
--------

heavensent is a service written in [AngelScript](https://www.angelcode.com/angelscript/) simulating a multi-user satellite system. Communication happens via a simulated RF link, pushing I/Q data over a TCP socket. Behind this interface is a backend letting users register themselves as ground stations, join operator networks of ground stations and share broadcast messages with them, create and tag payload data, and assist other ground stations by downlinking encrypted experiment data for them which can then be sent to the owning ground station out of band and be decrypted by the original ground station requesting a key from the satellite.

#### SDR

A custom physical layer based on 64-byte packets sent via a 16-FSK modulation with two symbols per byte is implemented. Communication is largely symmetric between uplink and downlink. Ground stations transmit at fixed frequency to minimize G/S complexity, with the satellite performing Doppler correction for both uplink and downlink. Synchronization in symbol and frame timing as well as frequency for the uplink is accomplished using one-shot feedforward correlation against a known synchronization word prepended to each packet. To protect against bit errors, packets are suffixed with a CRC-32.

### Flag Store 1

Ground stations can register and join "operator" networks protected by a secret. Ground stations can uplink short 32 byte "broadcast messages" which can be read by other ground stations in the same operator network. Flags are stored as a set of these broadcast messages in an inaccessible operator ID.

Attack info is the ground station and operator ID of the target.

### Flag Store 2

Ground stations can also run experiments with the on-board payload, tag them with user-provided data, and then downlink them. If one ground station does not have enough data budget available for experiment downlink, another ground station can perform an "assisted downlink", receiving an encrypted version of the data. The idea is that this data can then be communicated to the original owner of the experiment out of band and the original owner can then request just the key from the satellite and decrypt the data. To avoid storing large amounts of encryption keys, the key is generated statelessly by the satellite. Flags are stored as user-provided tags on an experiment.

Attack info is the ground station and experiment ID.

Vulnerabilities
---------------

### Flag Store 1, Vuln 1

After synchronizing in frequency using the feedforward correlator, the satellite-side receiver uses quadrature demodulation to detect the instantaneous frequency of each sample and transforms this into a symbol value by remapping the received frequency range into [0; 15] using simple arithmetic. Since the bandwidth of the spectrum is much wider though to account for Doppler shift, it is possible that symbol values outside of this range could be generated. In this case, the SDR attempts to clamp these symbols into inbounds ranges, however due to the data type of the argument of the `symbol_is_valid` function being `int8`, there is an integer overflow issue where not only the symbols `[0;15]`, but also `[256;271]`, ... are accepted as valid symbols.

While the corresponding frequencies would lie outside of the Nyquist limit of the 48 kHz complex sample rate at a center frequency of 0 Hz, it is possible to shift these frequencies into being valid by abusing the Doppler-tolerance of the satellite-side receiver by manually shifting the transmitted message down in frequency to bring these high tones into range, and manually Doppler correcting the response from the satellite. Because symbols are transformed into bytes simply using the formula `a << 4 | b`, this allows transmitting packets with byte values outside of the normal range of [0; 255].

This can be exploited by sending a `SetBroadcastMessage` request with slot ID 256. Because the ground station's operator ID is stored after the broadcast message slots in the ground station's data file, and because the broadcast message slot number is not otherwise validated as it is unpacked from a single byte and thus assumed to fall within the valid [0; 255] slot range, this allows overwriting the operator ID without using a `RegisterAtOperator` request which would require the operator secret. This allows joining the target ground station's operator and simply reading the flag broadcast message.

* Category: rev, radio, pwn
* Difficulty: hard
* Discoverability: hard
* Patchability: medium

### Flag Store 2, Vuln 1

The assisted downlink functionality does not require authentication as it is supposed to be secure without the satellite-generated key being available, which is only available with authentication. However the key is generated in a known fashion as a combination of a server side secret generated at startup, the ground station ID, password, and experiment ID. To reduce these 320 bits of entropy down to 256 bits suitable for AES, a custom hashing algorithm based on some entropy-preserving transformations using modular multiplication with odd 64 bit integers and a linear feedback shift register is used.

However, in the implementation of this LFSR, a bug exists where the least significant bit is first shifted out and then the feedback is applied based on the new value of the least significant bit, as opposed to the other way round. This causes a predictable loss of one bit of entropy in the lowest bit of the input data, which is where the experiment ID is stored. This creates a second preimage experiment ID, where the two experiment IDs which differ only in the lowest bit following the modular multiplication step will generate the same key.

Because AES-CTR mode is used and there are no checks that an experiment has to exist to attempt to downlink it, this allows downlinking both the target experiment ID and its second preimage experiment ID which will contain zero bytes as its plaintext as it doesn't exist, and XORing the two together to obtain the plaintext target experiment.

* Category: rev, cry
* Difficulty: medium
* Discoverability: medium
* Patchability: easy/medium

Patches
-------

[comment]: # (For each of the vulnerabilities reported in the previous section, outline a possible fix, can use diff files here to visualize changes but a text explanation is also required)

### Flag Store 1, Vuln 1

The issue can be patched by fixing the `symbol_is_valid` check. One way to achieve this is by swapping the `iTOb` and `CpyVtoV4` instructions at the callsite of `symbol_is_valid` and both pairs of `sbTOi` and `CpyVtoV4` within `symbol_is_valid` to effectively change the argument type from `int8` to `int`, which fixes the check.

### Flag Store 2, Vuln 1

The issue can be patched by swapping the calls to the `lfsr_shift` and `lfsr_feedback` functions in the `mix_bits` function, which eliminates the entropy loss.