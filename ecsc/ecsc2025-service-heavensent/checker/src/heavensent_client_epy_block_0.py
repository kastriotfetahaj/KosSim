# SPDX-License-Identifier: GPL-3.0

import numpy as np
from gnuradio import gr
import pmt


class hs_startup_sync(gr.sync_block):
    def __init__(self):
        gr.sync_block.__init__(
            self,
            name='HeavenSent Startup Sync',
            in_sig=None,
            out_sig=None
        )
        self.message_port_register_in(pmt.intern("in"))
        self.set_msg_handler(pmt.intern("in"), self.msg_handler)

        self.message_port_register_out(pmt.intern("out"))
        self.message_port_register_out(pmt.intern("loopback"))

        self.synchronized = False

    def msg_handler(self, msg):
        if not self.synchronized:
            # Not synchronized yet, receiving sync requests instead of packets
            if not pmt.is_pdu(msg):
                gr.log.warn(f"HS Sync: input message {repr(msg)} is not a PDU, dropping")
                return

            data = pmt.to_python(pmt.cdr(msg))

            # We assume that the connection could go "live" at any byte boundary.
            # Therefore the synchronization protocol must only use single byte commands.

            # Protect against multiple packets being merged because this is TCP
            # For this to work there has to be a guarantee that the transition from
            # unsynchronized to synchronized does not happen within a PDU.
            # We can guarantee this because we will enter synchronized state when
            # we send our own "sync ack" PDU which the client must wait for.
            if len(data) > 1:
                gr.log.warn(f"HS Sync: received {len(data)} bytes at a time while waiting for sync (data={repr(data)})")
            for request_code in data:
                if self.synchronized:
                    gr.log.warn(f"HS Sync: received sync requests while already synchronized, this data will end up dropped!")
                    break

                self.sync_action(request_code)
        else:
            # Pass message through
            self.message_port_pub(pmt.intern("out"), msg)

    def sync_action(self, request_code):
        if request_code == ord("W"):
            # Client is waiting for sync, let it know we are ready
            response_code = ord("R")
        elif request_code == ord("S"):
            # Client wants to start now, acknowledge
            response_code = ord("A")
            self.synchronized = True
        else:
            gr.log.warn(f"HS Sync: received bad sync request {request_code}, dropping")
            return

        # Respond
        response_vec = pmt.to_pmt(np.array([response_code], dtype=np.uint8))
        response_msg = pmt.cons(pmt.PMT_NIL, response_vec)
        self.message_port_pub(pmt.intern("loopback"), response_msg)