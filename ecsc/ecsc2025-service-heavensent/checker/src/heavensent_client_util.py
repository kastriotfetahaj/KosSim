# SPDX-License-Identifier: GPL-3.0

def unpack_symbols(data):
	syms = []
	for b in data:
		syms.append((b >> 4) & 0xf)
		syms.append((b >> 0) & 0xf)
	return syms

def pack_symbols(syms):
	assert len(syms) % 2 == 0
	byte_count = len(syms) // 2
	data = bytearray(byte_count)
	for i in range(byte_count):
		hi_sym = syms[2*i+0]
		lo_sym = syms[2*i+1]
		data[i] = (hi_sym << 4) | lo_sym
	return data

def modulate_symbols(syms, sps, hz_per_lsb, SYM_BASE, samp_rate):
	import numpy as np
	sym_freqs = (np.array(syms) - (SYM_BASE - 1) / 2) * hz_per_lsb
	sample_freqs = np.repeat(sym_freqs, int(sps))
	sample_omega = 2 * np.pi / samp_rate * sample_freqs
	sample_phase = np.cumsum(sample_omega)
	iq_samples = np.exp(1j * sample_phase)
	return iq_samples