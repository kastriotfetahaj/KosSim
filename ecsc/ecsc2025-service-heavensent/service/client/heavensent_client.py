#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: Not titled yet
# Author: PistonMiner
# GNU Radio version: 3.10.10.0

from gnuradio import analog
import math
from gnuradio import blocks
from gnuradio import digital
from gnuradio import filter
from gnuradio.filter import firdes
from gnuradio import gr
from gnuradio.fft import window
import sys
import signal
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import gr, pdu
from gnuradio import network
from gnuradio import pdu
import pmt, numpy as np
import heavensent_client_epy_block_0 as epy_block_0  # embedded python block
import heavensent_client_util as util  # embedded python module
import satellites
import satellites.grtypes




class heavensent_client(gr.top_block):

    def __init__(self, client_port='9502', doppler_hz=0.0, service_host='localhost'):
        gr.top_block.__init__(self, "Not titled yet", catch_exceptions=True)

        ##################################################
        # Parameters
        ##################################################
        self.client_port = client_port
        self.doppler_hz = doppler_hz
        self.service_host = service_host

        ##################################################
        # Variables
        ##################################################
        self.CONTENT_BYTE_COUNT = CONTENT_BYTE_COUNT = 64
        self.SYM_PER_BYTE = SYM_PER_BYTE = 2
        self.FRAME_SYNC_SYMBOLS = FRAME_SYNC_SYMBOLS = [0x0, 0x0, 0x0, 0xf, 0xf, 0x0, 0xf, 0x0, 0xf, 0xf, 0x0, 0x0, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0x0, 0x0, 0x0, 0x0, 0x0, 0xf, 0xf, 0xf, 0x0, 0xf]
        self.FRAME_BYTE_COUNT = FRAME_BYTE_COUNT = CONTENT_BYTE_COUNT + 4
        self.sym_rate = sym_rate = 4800
        self.samp_rate = samp_rate = int(48e3)
        self.frame_preamble = frame_preamble = FRAME_SYNC_SYMBOLS
        self.FRAME_SYMBOL_COUNT = FRAME_SYMBOL_COUNT = FRAME_BYTE_COUNT * SYM_PER_BYTE
        self.sps = sps = samp_rate/sym_rate
        self.num_frame_symbols = num_frame_symbols = len(frame_preamble)+FRAME_SYMBOL_COUNT
        self.frame_sync_bytes = frame_sync_bytes = util.pack_symbols(FRAME_SYNC_SYMBOLS)
        self.sync_bits = sync_bits = np.unpackbits(np.array(frame_sync_bytes, dtype="uint8")).astype('int')
        self.sym_base_bits = sym_base_bits = 4
        self.samp_size_bytes = samp_size_bytes = 8
        self.num_frame_samples = num_frame_samples = int(num_frame_symbols*sps)
        self.margin = margin = 1.5
        self.block_num_samples = block_num_samples = samp_rate//16
        self.SYM_BASE = SYM_BASE = 16
        self.BANDWIDTH_HZ = BANDWIDTH_HZ = 1800
        self.service_port = service_port = "9501"
        self.post_frame_idle_samples = post_frame_idle_samples = ((int(num_frame_samples*margin) + block_num_samples - 1) // block_num_samples) * block_num_samples - num_frame_samples
        self.hz_per_lsb = hz_per_lsb = BANDWIDTH_HZ/(SYM_BASE - 1)
        self.fsk16_constellation = fsk16_constellation = digital.constellation_calcdist(list(np.linspace(-1, 1, SYM_BASE)), list(range(SYM_BASE)),
        4, 1, digital.constellation.AMPLITUDE_NORMALIZATION).base()
        self.fsk16_constellation.set_npwr(1.0)
        self.frame_size_bits = frame_size_bits = FRAME_SYMBOL_COUNT * sym_base_bits
        self.block_time = block_time = block_num_samples/samp_rate
        self.block_size_bytes = block_size_bytes = block_num_samples * samp_size_bytes
        self.access_code = access_code = "".join(map(str, sync_bits))

        ##################################################
        # Blocks
        ##################################################

        self.satellites_fixedlen_to_pdu_0 = satellites.fixedlen_to_pdu(satellites.grtypes.byte_t, 'syncword', frame_size_bits, True)
        self.pdu_take_skip_to_pdu_1 = pdu.take_skip_to_pdu_b(block_size_bytes, 0)
        self.pdu_take_skip_to_pdu_0_0 = pdu.take_skip_to_pdu_b(CONTENT_BYTE_COUNT, 0)
        self.pdu_take_skip_to_pdu_0 = pdu.take_skip_to_pdu_c(block_num_samples, 0)
        self.pdu_pdu_to_tagged_stream_1 = pdu.pdu_to_tagged_stream(gr.types.byte_t, 'packet_len')
        self.pdu_pdu_to_stream_x_1 = pdu.pdu_to_stream_b(pdu.EARLY_BURST_APPEND, 64)
        self.pdu_pdu_to_stream_x_0_0 = pdu.pdu_to_stream_b(pdu.EARLY_BURST_APPEND, 64)
        self.pdu_pdu_to_stream_x_0 = pdu.pdu_to_stream_c(pdu.EARLY_BURST_APPEND, 64)
        self.pdu_pdu_lambda_1_0 = pdu.pdu_lambda(lambda a: np.concatenate((np.array(frame_preamble,dtype="uint8"),a)), "UVEC", pmt.intern("key"))
        self.pdu_pdu_lambda_1 = pdu.pdu_lambda(lambda a: np.array(util.unpack_symbols(a),dtype="uint8"), "UVEC", pmt.intern("key"))
        self.pdu_pdu_lambda_0 = pdu.pdu_lambda(lambda a: np.frombuffer(a, dtype=np.complex64), "UVEC", pmt.intern("key"))
        self.network_socket_pdu_0_0 = network.socket_pdu('TCP_SERVER', '', client_port, CONTENT_BYTE_COUNT, True)
        self.network_socket_pdu_0 = network.socket_pdu('TCP_CLIENT', service_host, service_port, block_size_bytes, True)
        self.fir_filter_xxx_0 = filter.fir_filter_fff(1, np.array(np.ones(int(sps-2)))/int(sps-2))
        self.fir_filter_xxx_0.declare_sample_delay(0)
        self.epy_block_0 = epy_block_0.hs_startup_sync()
        self.digital_symbol_sync_xx_0 = digital.symbol_sync_ff(
            digital.TED_SIGNAL_TIMES_SLOPE_ML,
            sps,
            0,
            1.0,
            1,
            0.001,
            1,
            fsk16_constellation,
            digital.IR_MMSE_8TAP,
            128,
            [])
        self.digital_crc_check_0 = digital.crc_check(32, 0x4C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True, True, False, True, 0)
        self.digital_crc_append_0 = digital.crc_append(32, 0x4C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True, True, False, 0)
        self.digital_correlate_access_code_tag_xx_0 = digital.correlate_access_code_tag_bb(access_code[-64:], 0, 'syncword')
        self.digital_corr_est_cc_0 = digital.corr_est_cc(util.modulate_symbols(FRAME_SYNC_SYMBOLS, sps, hz_per_lsb, SYM_BASE, samp_rate), sps-1, 0, 0.9, digital.THRESHOLD_ABSOLUTE)
        self.blocks_vco_c_0 = blocks.vco_c(samp_rate, (2*np.pi), 1)
        self.blocks_uchar_to_float_0 = blocks.uchar_to_float()
        self.blocks_tag_gate_0 = blocks.tag_gate(gr.sizeof_gr_complex * 1, False)
        self.blocks_tag_gate_0.set_single_key("")
        self.blocks_stream_mux_1 = blocks.stream_mux(gr.sizeof_gr_complex*1, (num_frame_samples, post_frame_idle_samples))
        self.blocks_repeat_0 = blocks.repeat(gr.sizeof_char*1, int(sps))
        self.blocks_repack_bits_bb_1 = blocks.repack_bits_bb(sym_base_bits, 1, "", False, gr.GR_MSB_FIRST)
        self.blocks_multiply_const_vxx_0_2 = blocks.multiply_const_ff(((SYM_BASE - 1) / 2))
        self.blocks_multiply_const_vxx_0_0 = blocks.multiply_const_ff(hz_per_lsb)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_ff((1/(hz_per_lsb * (SYM_BASE - 1)/2)))
        self.blocks_freqshift_cc_0_0 = blocks.rotator_cc(2.0*math.pi*doppler_hz/samp_rate)
        self.blocks_freqshift_cc_0 = blocks.rotator_cc(2.0*math.pi*doppler_hz/samp_rate)
        self.blocks_float_to_uchar_0 = blocks.float_to_uchar(1, 1, 0)
        self.blocks_add_const_vxx_0_2 = blocks.add_const_ff(((SYM_BASE - 1) / 2))
        self.blocks_add_const_vxx_0_0 = blocks.add_const_ff((-BANDWIDTH_HZ / 2))
        self.analog_quadrature_demod_cf_1 = analog.quadrature_demod_cf((samp_rate/(2*math.pi)))
        self.analog_const_source_x_0 = analog.sig_source_c(0, analog.GR_CONST_WAVE, 0, 0, 0)


        ##################################################
        # Connections
        ##################################################
        self.msg_connect((self.digital_crc_append_0, 'out'), (self.pdu_pdu_lambda_1, 'pdu'))
        self.msg_connect((self.digital_crc_check_0, 'ok'), (self.network_socket_pdu_0_0, 'pdus'))
        self.msg_connect((self.epy_block_0, 'loopback'), (self.network_socket_pdu_0_0, 'pdus'))
        self.msg_connect((self.epy_block_0, 'out'), (self.pdu_pdu_to_stream_x_1, 'pdus'))
        self.msg_connect((self.network_socket_pdu_0, 'pdus'), (self.pdu_pdu_to_stream_x_0_0, 'pdus'))
        self.msg_connect((self.network_socket_pdu_0_0, 'pdus'), (self.epy_block_0, 'in'))
        self.msg_connect((self.pdu_pdu_lambda_0, 'pdu'), (self.pdu_pdu_to_stream_x_0, 'pdus'))
        self.msg_connect((self.pdu_pdu_lambda_1, 'pdu'), (self.pdu_pdu_lambda_1_0, 'pdu'))
        self.msg_connect((self.pdu_pdu_lambda_1_0, 'pdu'), (self.pdu_pdu_to_tagged_stream_1, 'pdus'))
        self.msg_connect((self.pdu_take_skip_to_pdu_0, 'pdus'), (self.network_socket_pdu_0, 'pdus'))
        self.msg_connect((self.pdu_take_skip_to_pdu_0_0, 'pdus'), (self.digital_crc_append_0, 'in'))
        self.msg_connect((self.pdu_take_skip_to_pdu_1, 'pdus'), (self.pdu_pdu_lambda_0, 'pdu'))
        self.msg_connect((self.satellites_fixedlen_to_pdu_0, 'pdus'), (self.digital_crc_check_0, 'in'))
        self.connect((self.analog_const_source_x_0, 0), (self.blocks_stream_mux_1, 1))
        self.connect((self.analog_quadrature_demod_cf_1, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.blocks_add_const_vxx_0_0, 0), (self.blocks_vco_c_0, 0))
        self.connect((self.blocks_add_const_vxx_0_2, 0), (self.blocks_float_to_uchar_0, 0))
        self.connect((self.blocks_float_to_uchar_0, 0), (self.blocks_repack_bits_bb_1, 0))
        self.connect((self.blocks_freqshift_cc_0, 0), (self.digital_corr_est_cc_0, 0))
        self.connect((self.blocks_freqshift_cc_0_0, 0), (self.pdu_take_skip_to_pdu_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.fir_filter_xxx_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0_0, 0), (self.blocks_add_const_vxx_0_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0_2, 0), (self.blocks_add_const_vxx_0_2, 0))
        self.connect((self.blocks_repack_bits_bb_1, 0), (self.digital_correlate_access_code_tag_xx_0, 0))
        self.connect((self.blocks_repeat_0, 0), (self.blocks_uchar_to_float_0, 0))
        self.connect((self.blocks_stream_mux_1, 0), (self.blocks_freqshift_cc_0_0, 0))
        self.connect((self.blocks_tag_gate_0, 0), (self.blocks_freqshift_cc_0, 0))
        self.connect((self.blocks_uchar_to_float_0, 0), (self.blocks_multiply_const_vxx_0_0, 0))
        self.connect((self.blocks_vco_c_0, 0), (self.blocks_stream_mux_1, 0))
        self.connect((self.digital_corr_est_cc_0, 0), (self.analog_quadrature_demod_cf_1, 0))
        self.connect((self.digital_correlate_access_code_tag_xx_0, 0), (self.satellites_fixedlen_to_pdu_0, 0))
        self.connect((self.digital_symbol_sync_xx_0, 0), (self.blocks_multiply_const_vxx_0_2, 0))
        self.connect((self.fir_filter_xxx_0, 0), (self.digital_symbol_sync_xx_0, 0))
        self.connect((self.pdu_pdu_to_stream_x_0, 0), (self.blocks_tag_gate_0, 0))
        self.connect((self.pdu_pdu_to_stream_x_0_0, 0), (self.pdu_take_skip_to_pdu_1, 0))
        self.connect((self.pdu_pdu_to_stream_x_1, 0), (self.pdu_take_skip_to_pdu_0_0, 0))
        self.connect((self.pdu_pdu_to_tagged_stream_1, 0), (self.blocks_repeat_0, 0))


    def get_client_port(self):
        return self.client_port

    def set_client_port(self, client_port):
        self.client_port = client_port

    def get_doppler_hz(self):
        return self.doppler_hz

    def set_doppler_hz(self, doppler_hz):
        self.doppler_hz = doppler_hz
        self.blocks_freqshift_cc_0.set_phase_inc(2.0*math.pi*self.doppler_hz/self.samp_rate)
        self.blocks_freqshift_cc_0_0.set_phase_inc(2.0*math.pi*self.doppler_hz/self.samp_rate)

    def get_service_host(self):
        return self.service_host

    def set_service_host(self, service_host):
        self.service_host = service_host

    def get_CONTENT_BYTE_COUNT(self):
        return self.CONTENT_BYTE_COUNT

    def set_CONTENT_BYTE_COUNT(self, CONTENT_BYTE_COUNT):
        self.CONTENT_BYTE_COUNT = CONTENT_BYTE_COUNT
        self.set_FRAME_BYTE_COUNT(self.CONTENT_BYTE_COUNT + 4)
        self.pdu_take_skip_to_pdu_0_0.set_take(self.CONTENT_BYTE_COUNT)

    def get_SYM_PER_BYTE(self):
        return self.SYM_PER_BYTE

    def set_SYM_PER_BYTE(self, SYM_PER_BYTE):
        self.SYM_PER_BYTE = SYM_PER_BYTE
        self.set_FRAME_SYMBOL_COUNT(self.FRAME_BYTE_COUNT * self.SYM_PER_BYTE)

    def get_FRAME_SYNC_SYMBOLS(self):
        return self.FRAME_SYNC_SYMBOLS

    def set_FRAME_SYNC_SYMBOLS(self, FRAME_SYNC_SYMBOLS):
        self.FRAME_SYNC_SYMBOLS = FRAME_SYNC_SYMBOLS
        self.set_frame_preamble(self.FRAME_SYNC_SYMBOLS)
        self.set_frame_sync_bytes(util.pack_symbols(self.FRAME_SYNC_SYMBOLS))

    def get_FRAME_BYTE_COUNT(self):
        return self.FRAME_BYTE_COUNT

    def set_FRAME_BYTE_COUNT(self, FRAME_BYTE_COUNT):
        self.FRAME_BYTE_COUNT = FRAME_BYTE_COUNT
        self.set_FRAME_SYMBOL_COUNT(self.FRAME_BYTE_COUNT * self.SYM_PER_BYTE)

    def get_sym_rate(self):
        return self.sym_rate

    def set_sym_rate(self, sym_rate):
        self.sym_rate = sym_rate
        self.set_sps(self.samp_rate/self.sym_rate)

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.set_block_num_samples(self.samp_rate//16)
        self.set_block_time(self.block_num_samples/self.samp_rate)
        self.set_sps(self.samp_rate/self.sym_rate)
        self.analog_quadrature_demod_cf_1.set_gain((self.samp_rate/(2*math.pi)))
        self.blocks_freqshift_cc_0.set_phase_inc(2.0*math.pi*self.doppler_hz/self.samp_rate)
        self.blocks_freqshift_cc_0_0.set_phase_inc(2.0*math.pi*self.doppler_hz/self.samp_rate)
        self.blocks_throttle2_0.set_sample_rate(self.samp_rate)

    def get_frame_preamble(self):
        return self.frame_preamble

    def set_frame_preamble(self, frame_preamble):
        self.frame_preamble = frame_preamble
        self.set_num_frame_symbols(len(self.frame_preamble)+self.FRAME_SYMBOL_COUNT)
        self.pdu_pdu_lambda_1_0.set_fn(lambda a: np.concatenate((np.array(self.frame_preamble,dtype="uint8"),a)))

    def get_FRAME_SYMBOL_COUNT(self):
        return self.FRAME_SYMBOL_COUNT

    def set_FRAME_SYMBOL_COUNT(self, FRAME_SYMBOL_COUNT):
        self.FRAME_SYMBOL_COUNT = FRAME_SYMBOL_COUNT
        self.set_frame_size_bits(self.FRAME_SYMBOL_COUNT * self.sym_base_bits)
        self.set_num_frame_symbols(len(self.frame_preamble)+self.FRAME_SYMBOL_COUNT)

    def get_sps(self):
        return self.sps

    def set_sps(self, sps):
        self.sps = sps
        self.set_num_frame_samples(int(self.num_frame_symbols*self.sps))
        self.blocks_repeat_0.set_interpolation(int(self.sps))
        self.digital_symbol_sync_xx_0.set_sps(self.sps)
        self.fir_filter_xxx_0.set_taps(np.array(np.ones(int(self.sps-2)))/int(self.sps-2))

    def get_num_frame_symbols(self):
        return self.num_frame_symbols

    def set_num_frame_symbols(self, num_frame_symbols):
        self.num_frame_symbols = num_frame_symbols
        self.set_num_frame_samples(int(self.num_frame_symbols*self.sps))

    def get_frame_sync_bytes(self):
        return self.frame_sync_bytes

    def set_frame_sync_bytes(self, frame_sync_bytes):
        self.frame_sync_bytes = frame_sync_bytes
        self.set_sync_bits(np.unpackbits(np.array(self.frame_sync_bytes, dtype="uint8")).astype('int'))

    def get_sync_bits(self):
        return self.sync_bits

    def set_sync_bits(self, sync_bits):
        self.sync_bits = sync_bits
        self.set_access_code("".join(map(str, self.sync_bits)))

    def get_sym_base_bits(self):
        return self.sym_base_bits

    def set_sym_base_bits(self, sym_base_bits):
        self.sym_base_bits = sym_base_bits
        self.set_frame_size_bits(self.FRAME_SYMBOL_COUNT * self.sym_base_bits)
        self.blocks_repack_bits_bb_1.set_k_and_l(self.sym_base_bits,1)

    def get_samp_size_bytes(self):
        return self.samp_size_bytes

    def set_samp_size_bytes(self, samp_size_bytes):
        self.samp_size_bytes = samp_size_bytes
        self.set_block_size_bytes(self.block_num_samples * self.samp_size_bytes)

    def get_num_frame_samples(self):
        return self.num_frame_samples

    def set_num_frame_samples(self, num_frame_samples):
        self.num_frame_samples = num_frame_samples
        self.set_post_frame_idle_samples(((int(self.num_frame_samples*self.margin) + self.block_num_samples - 1) // self.block_num_samples) * self.block_num_samples - self.num_frame_samples)

    def get_margin(self):
        return self.margin

    def set_margin(self, margin):
        self.margin = margin
        self.set_post_frame_idle_samples(((int(self.num_frame_samples*self.margin) + self.block_num_samples - 1) // self.block_num_samples) * self.block_num_samples - self.num_frame_samples)

    def get_block_num_samples(self):
        return self.block_num_samples

    def set_block_num_samples(self, block_num_samples):
        self.block_num_samples = block_num_samples
        self.set_block_size_bytes(self.block_num_samples * self.samp_size_bytes)
        self.set_block_time(self.block_num_samples/self.samp_rate)
        self.set_post_frame_idle_samples(((int(self.num_frame_samples*self.margin) + self.block_num_samples - 1) // self.block_num_samples) * self.block_num_samples - self.num_frame_samples)
        self.pdu_take_skip_to_pdu_0.set_take(self.block_num_samples)

    def get_SYM_BASE(self):
        return self.SYM_BASE

    def set_SYM_BASE(self, SYM_BASE):
        self.SYM_BASE = SYM_BASE
        self.set_hz_per_lsb(self.BANDWIDTH_HZ/(self.SYM_BASE - 1))
        self.blocks_add_const_vxx_0_2.set_k(((self.SYM_BASE - 1) / 2))
        self.blocks_multiply_const_vxx_0.set_k((1/(self.hz_per_lsb * (self.SYM_BASE - 1)/2)))
        self.blocks_multiply_const_vxx_0_2.set_k(((self.SYM_BASE - 1) / 2))

    def get_BANDWIDTH_HZ(self):
        return self.BANDWIDTH_HZ

    def set_BANDWIDTH_HZ(self, BANDWIDTH_HZ):
        self.BANDWIDTH_HZ = BANDWIDTH_HZ
        self.set_hz_per_lsb(self.BANDWIDTH_HZ/(self.SYM_BASE - 1))
        self.blocks_add_const_vxx_0_0.set_k((-self.BANDWIDTH_HZ / 2))

    def get_service_port(self):
        return self.service_port

    def set_service_port(self, service_port):
        self.service_port = service_port

    def get_post_frame_idle_samples(self):
        return self.post_frame_idle_samples

    def set_post_frame_idle_samples(self, post_frame_idle_samples):
        self.post_frame_idle_samples = post_frame_idle_samples

    def get_hz_per_lsb(self):
        return self.hz_per_lsb

    def set_hz_per_lsb(self, hz_per_lsb):
        self.hz_per_lsb = hz_per_lsb
        self.blocks_multiply_const_vxx_0.set_k((1/(self.hz_per_lsb * (self.SYM_BASE - 1)/2)))
        self.blocks_multiply_const_vxx_0_0.set_k(self.hz_per_lsb)

    def get_fsk16_constellation(self):
        return self.fsk16_constellation

    def set_fsk16_constellation(self, fsk16_constellation):
        self.fsk16_constellation = fsk16_constellation

    def get_frame_size_bits(self):
        return self.frame_size_bits

    def set_frame_size_bits(self, frame_size_bits):
        self.frame_size_bits = frame_size_bits

    def get_block_time(self):
        return self.block_time

    def set_block_time(self, block_time):
        self.block_time = block_time

    def get_block_size_bytes(self):
        return self.block_size_bytes

    def set_block_size_bytes(self, block_size_bytes):
        self.block_size_bytes = block_size_bytes
        self.pdu_take_skip_to_pdu_1.set_take(self.block_size_bytes)

    def get_access_code(self):
        return self.access_code

    def set_access_code(self, access_code):
        self.access_code = access_code
        self.digital_correlate_access_code_tag_xx_0.set_access_code(self.access_code[-64:])



def argument_parser():
    parser = ArgumentParser()
    parser.add_argument(
        "--client-port", dest="client_port", type=str, default='9502',
        help="Set client-port [default=%(default)r]")
    parser.add_argument(
        "--doppler-hz", dest="doppler_hz", type=eng_float, default=eng_notation.num_to_str(float(0.0)),
        help="Set doppler-hz [default=%(default)r]")
    parser.add_argument(
        "--service-host", dest="service_host", type=str, default='localhost',
        help="Set service-host [default=%(default)r]")
    return parser


def main(top_block_cls=heavensent_client, options=None):
    if options is None:
        options = argument_parser().parse_args()
    tb = top_block_cls(client_port=options.client_port, doppler_hz=options.doppler_hz, service_host=options.service_host)

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    tb.start()

    tb.wait()


if __name__ == '__main__':
    main()
