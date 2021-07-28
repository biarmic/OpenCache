# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
from cache_base import cache_base
from nmigen import *
from nmigen.utils import log2_int
from rtl import get_ff_signals, State
from globals import OPTS


class n_way_lru_cache(cache_base):
    """
    This is the design module of N-way set associative cache
    with LRU replacement policy.
    """

    def __init__(self, cache_config, name):

        super().__init__(cache_config, name)


    def add_internal_signals(self):
        """ Add internal registers and wires to cache design. """

        super().add_internal_signals()

        # Keep way chosen to be evicted in an FF
        self.way, self.way_next = get_ff_signals("way", self.way_size)

        # Bypass FF for use array
        if self.data_hazard:
            self.new_use, self.new_use_next = get_ff_signals("new_use", self.way_size * self.num_ways)


    def add_srams(self, m):
        """ Add internal SRAM array instances to cache design. """

        super().add_srams(m)

        # Use array
        word_size = self.way_size * self.num_ways
        self.use_write_csb  = Signal(reset_less=True, reset=1)
        self.use_write_addr = Signal(self.set_size, reset_less=True)
        self.use_write_din  = Signal(word_size, reset_less=True)
        self.use_read_csb   = Signal(reset_less=True)
        self.use_read_addr  = Signal(self.set_size, reset_less=True)
        self.use_read_dout  = Signal(word_size)
        m.submodules += Instance(OPTS.use_array_name,
            ("i", "clk0",  self.clk),
            ("i", "csb0",  self.use_write_csb),
            ("i", "addr0", self.use_write_addr),
            ("i", "din0",  self.use_write_din),
            ("i", "clk1",  self.clk),
            ("i", "csb1",  self.use_read_csb),
            ("i", "addr1", self.use_read_addr),
            ("o", "dout1", self.use_read_dout),
        )


    def add_memory_controller_block(self, m):
        """ Add memory controller always block to cache design. """

        # In this block, cache communicates with memory components which
        # are tag array, data array, use array, and main memory.

        # If rst is high, state switches to RESET.
        # Registers, which are reset only once, are reset here.
        # In the RESET state, cache will set all tag and use array lines
        # to 0.
        with m.If(self.rst):
            m.d.comb += self.tag_write_csb.eq(0)
            m.d.comb += self.tag_write_addr.eq(0)
            m.d.comb += self.tag_write_din.eq(0)

        # If flush is high, state switches to FLUSH.
        # In the FLUSH state, cache will write all data lines back to
        # main memory.
        # TODO: Cache should write only dirty lines back.
        with m.Elif(self.flush):
            m.d.comb += self.tag_read_csb.eq(0)
            m.d.comb += self.tag_read_addr.eq(0)
            m.d.comb += self.data_read_csb.eq(0)
            m.d.comb += self.data_read_addr.eq(0)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, cache sends write request to tag and use
                # arrays to reset the current set.
                # set register is incremented by the Request Decode Block.
                # When set register reaches the end, state switches to IDLE.
                with m.Case(State.RESET):
                    m.d.comb += self.tag_write_csb.eq(0)
                    m.d.comb += self.tag_write_addr.eq(self.set)
                    m.d.comb += self.tag_write_din.eq(0)

                # In the FLUSH state, cache sends write request to main memory.
                # set register is incremented by the Request Decode Block.
                # way register is incremented by the Replacement Block.
                # When set and way registers reach the end, state switches
                # to IDLE.
                # TODO: Cache should write only dirty lines back.
                with m.Case(State.FLUSH):
                    m.d.comb += self.tag_read_csb.eq(0)
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_csb.eq(0)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    m.d.comb += self.main_csb.eq(0)
                    m.d.comb += self.main_web.eq(0)
                    m.d.comb += self.main_addr.eq(Cat(self.set, self.tag_read_dout.bit_select(self.way * (self.tag_size + 2), self.tag_size)))
                    m.d.comb += self.main_din.eq(self.data_read_dout.word_select(self.way, self.line_size))
                    with m.If(~self.main_stall & (self.way == self.num_ways - 1)):
                        m.d.comb += self.tag_read_addr.eq(self.set + 1)
                        m.d.comb += self.data_read_addr.eq(self.set + 1)

                # In the IDLE state, cache waits for CPU to send a new request.
                # Until there is a new request from the cache, stall is low.
                # When there is a new request from the cache stall is asserted,
                # request is decoded and corresponding tag, data, and use lines
                # are read from internal SRAM arrays.
                with m.Case(State.IDLE):
                    with m.If(~self.csb):
                        m.d.comb += self.tag_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))
                        m.d.comb += self.data_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))
                        # FIXME: Don't write 0 in testbench (might result in missed errors).
                        m.d.comb += self.data_write_din.eq(0)

                # In the COMPARE state, cache compares tags.
                # Stall and dout are driven by the Output Block.
                with m.Case(State.COMPARE):
                    for i in range(self.num_ways):
                        # Find the least recently used way (the way having 0 use number)
                        with m.If(
                            (self.bypass & (self.new_use.word_select(i, self.way_size) == 0)) |
                            (~self.bypass & (self.use_read_dout.word_select(i, self.way_size) == 0))
                        ):
                            # Assuming that current request is miss, check if it is a dirty miss
                            with m.If(
                                (self.bypass & (self.new_tag.bit_select(i * (self.tag_size + 2) + self.tag_size, 2) == Const(3, 2))) |
                                (~self.bypass & (self.tag_read_dout.bit_select(i * (self.tag_size + 2) + self.tag_size, 2) == Const(3, 2)))
                            ):
                                # If main memory is busy, switch to WRITE and wait for
                                # main memory to be available.
                                with m.If(self.main_stall):
                                    m.d.comb += self.tag_read_addr.eq(self.set)
                                    m.d.comb += self.data_read_addr.eq(self.set)
                                # If main memory is available, switch to WAIT_WRITE and
                                # wait for main memory to complete writing.
                                with m.Else():
                                    m.d.comb += self.main_csb.eq(0)
                                    m.d.comb += self.main_web.eq(0)
                                    with m.If(self.bypass):
                                        m.d.comb += self.main_addr.eq(Cat(self.set, self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size)))
                                        m.d.comb += self.main_din.eq(self.new_data.word_select(i, self.line_size))
                                    with m.Else():
                                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size)))
                                        m.d.comb += self.main_din.eq(self.data_read_dout.word_select(i, self.line_size))
                            # Else, assume that current request is a clean miss
                            with m.Else():
                                with m.If(~self.main_stall):
                                    m.d.comb += self.tag_read_addr.eq(self.set)
                                    m.d.comb += self.data_read_addr.eq(self.set)
                                    m.d.comb += self.main_csb.eq(0)
                                    m.d.comb += self.main_addr.eq(Cat(self.set, self.tag))
                    # Check if current request is hit
                    # Compare all ways' tags to find a hit. Since each way has a different
                    # tag, only one of them can match at most.
                    # NOTE: This for loop should not be merged with the one above since hit
                    # should be checked after all miss assumptions are done.
                    for i in range(self.num_ways):
                        with m.If(
                            (self.bypass & self.new_tag[i * (self.tag_size + 2) + self.tag_size + 1] & (self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag)) |
                            (~self.bypass & self.tag_read_dout[i * (self.tag_size + 2) + self.tag_size + 1] & (self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag))
                        ):
                            # Set main memory's csb to 1 again since it could be set 0 above
                            m.d.comb += self.main_csb.eq(1)
                            # Perform the write request
                            with m.If(~self.web_reg):
                                m.d.comb += self.tag_write_csb.eq(0)
                                m.d.comb += self.tag_write_addr.eq(self.set)
                                m.d.comb += self.data_write_csb.eq(0)
                                m.d.comb += self.data_write_addr.eq(self.set)
                                with m.If(self.bypass):
                                    m.d.comb += self.tag_write_din.eq(self.new_tag)
                                    m.d.comb += self.data_write_din.eq(self.new_data)
                                with m.Else():
                                    m.d.comb += self.tag_write_din.eq(self.tag_read_dout)
                                    m.d.comb += self.data_write_din.eq(self.data_read_dout)
                                # Update dirty bit in the tag line
                                m.d.comb += self.tag_write_din[i * (self.tag_size + 2) + self.tag_size].eq(1)
                                # Write the word over the write mask
                                num_bytes_per_word = Const(self.num_bytes, log2_int(self.words_per_line))
                                num_bytes_per_line = Const(self.num_bytes * self.words_per_line, log2_int(self.num_ways * self.words_per_line))
                                for j in range(self.num_bytes):
                                    with m.If(self.wmask_reg[j]):
                                        m.d.comb += self.data_write_din.word_select(i * num_bytes_per_line + self.offset * num_bytes_per_word + j, 8).eq(self.din_reg.word_select(j, 8))
                            # If CPU is sending a new request, read next lines from SRAMs.
                            # Even if bypass registers are going to be used, read requests
                            # are sent to SRAMs since read is non-destructive (hopefully?).
                            with m.If(~self.csb):
                                m.d.comb += self.tag_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))
                                m.d.comb += self.data_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))

                # In the WRITE state, cache waits for main memory to be
                # available.
                # When main memory is available, write request is sent.
                with m.Case(State.WRITE):
                    # If main memory is busy, wait in this state.
                    # If main memory is available, switch to WAIT_WRITE and
                    # wait for main memory to complete writing.
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    with m.If(~self.main_stall):
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_web.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag_read_dout.bit_select(self.way * (self.tag_size + 2), self.tag_size)))
                        m.d.comb += self.main_din.eq(self.data_read_dout.word_select(self.way, self.line_size))

                # In the WAIT_WRITE state, cache waits for main memory to
                # complete writing.
                # When main memory completes writing, read request is sent.
                with m.Case(State.WAIT_WRITE):
                    # If main memory is busy, wait in this state.
                    # If main memory completes writing, switch to WAIT_READ
                    # and wait for main memory to complete reading.
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    with m.If(~self.main_stall):
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag))

                # In the READ state, cache waits for main memory to be
                # available.
                # When main memory is available, read request is sent.
                # TODO: Is this state really necessary? WAIT_WRITE state may be used instead.
                with m.Case(State.READ):
                    # If main memory is busy, wait in this state.
                    # If main memory completes writing, switch to WAIT_READ
                    # and wait for main memory to complete reading.
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    with m.If(~self.main_stall):
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag))

                # In the WAIT_READ state, cache waits for main memory to
                # complete reading.
                # When main memory completes reading, request is completed.
                with m.Case(State.WAIT_READ):
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    # If main memory is busy, wait in this state.
                    # If main memory completes reading, cache switches to:
                    #   IDLE    if CPU isn't sending a new request
                    #   COMPARE if CPU is sending a new request
                    with m.If(~self.main_stall):
                        # TODO: Use wmask feature of OpenRAM.
                        m.d.comb += self.tag_write_csb.eq(0)
                        m.d.comb += self.tag_write_addr.eq(self.set)
                        m.d.comb += self.tag_write_din.eq(self.tag_read_dout)
                        # TODO: Optimize the below case statement.
                        with m.Switch(self.way):
                            for i in range(self.num_ways):
                                with m.Case(i):
                                    m.d.comb += self.tag_write_din.word_select(i, self.tag_size + 2).eq(Cat(self.tag, ~self.web_reg, Const(1, 1)))
                        m.d.comb += self.data_write_csb.eq(0)
                        m.d.comb += self.data_write_addr.eq(self.set)
                        m.d.comb += self.data_write_din.eq(self.data_read_dout)
                        # TODO: Optimize the below case statement.
                        with m.Switch(self.way):
                            for i in range(self.num_ways):
                                with m.Case(i):
                                    m.d.comb += self.data_write_din.word_select(i, self.line_size).eq(self.main_dout)
                        # Perform the write request
                        with m.If(~self.web_reg):
                            # Write the word over the write mask
                            num_bytes_per_word = Const(self.num_bytes, log2_int(self.words_per_line))
                            num_bytes_per_line = Const(self.num_bytes * self.words_per_line, log2_int(self.num_ways * self.words_per_line))
                            for j in range(self.num_bytes):
                                with m.If(self.wmask_reg[j]):
                                    m.d.comb += self.data_write_din.word_select(self.way * num_bytes_per_line + self.offset * num_bytes_per_word + j, 8).eq(self.din_reg.word_select(j, 8))
                        # If CPU is sending a new request, read next lines from SRAMs
                        # Even if bypass registers are going to be used, read requests
                        # are sent to SRAMs since read is non-destructive (hopefully?).
                        with m.If(~self.csb):
                            m.d.comb += self.tag_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))
                            m.d.comb += self.data_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))


    def add_state_block(self, m):
        """ Add state controller always block to cache design. """

        # In this block, cache's state is controlled. state flip-flop
        # register is changed in order to switch between states.

        m.d.comb += self.state_next.eq(self.state)

        # If rst is high, state switches to RESET.
        with m.If(self.rst):
            m.d.comb += self.state_next.eq(State.RESET)

        # If flush is high, state switches to FLUSH.
        with m.If(self.flush):
            m.d.comb += self.state_next.eq(State.FLUSH)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, state switches to IDLE if reset is completed.
                with m.Case(State.RESET):
                    # When set reaches the limit, the last write request to the
                    # tag array is sent.
                    with m.If(self.set == self.num_rows - 1):
                        m.d.comb += self.state_next.eq(State.IDLE)

                # In the FLUSH state, state switches to IDLE if flush is completed.
                with m.Case(State.FLUSH):
                    # If main memory completes the last write request, flush is
                    # completed.
                    with m.If(~self.main_stall & (self.way == self.num_ways - 1) & (self.set == self.num_rows - 1)):
                        m.d.comb += self.state_next.eq(State.IDLE)

                # In the IDLE state, state switches to COMPARE if CPU is sending
                # a new request.
                with m.Case(State.IDLE):
                    with m.If(~self.csb):
                        m.d.comb += self.state_next.eq(State.COMPARE)

                # In the COMPARE state, state switches to:
                #   IDLE       if current request is hit and CPU isn't sending a new request
                #   COMPARE    if current request is hit and CPU is sending a new request
                #   WRITE      if current request is dirty miss and main memory is busy
                #   WAIT_WRITE if current request is dirty miss and main memory is available
                #   READ       if current request is clean miss and main memory is busy
                #   WAIT_READ  if current request is clean miss and main memory is available
                with m.Case(State.COMPARE):
                    for i in range(self.num_ways):
                        # Find the least recently used way (the way having 0 use number)
                        with m.If(
                            (self.bypass & (self.new_use.word_select(i, self.way_size) == 0)) |
                            (~self.bypass & (self.use_read_dout.word_select(i, self.way_size) == 0))
                        ):
                            # Assuming that current request is miss, check if it is a dirty miss
                            with m.If(
                                (self.bypass & (self.new_tag.bit_select(i * (self.tag_size + 2) + self.tag_size, 2) == Const(3, 2))) |
                                (~self.bypass & (self.tag_read_dout.bit_select(i * (self.tag_size + 2) + self.tag_size, 2) == Const(3, 2)))
                            ):
                                with m.If(self.main_stall):
                                    m.d.comb += self.state_next.eq(State.WRITE)
                                with m.Else():
                                    m.d.comb += self.state_next.eq(State.WAIT_WRITE)
                            # Else, current request is a clean miss
                            with m.Else():
                                with m.If(self.main_stall):
                                    m.d.comb += self.state_next.eq(State.READ)
                                with m.Else():
                                    m.d.comb += self.state_next.eq(State.WAIT_READ)
                    # Find the least recently used way (the way having 0 use number)
                    # Compare all ways' tags to find a hit. Since each way has a different
                    # tag, only one of them can match at most.
                    # NOTE: This for loop should not be merged with the one above since hit
                    # should be checked after all miss assumptions are done.
                    # TODO: This should be optimized.
                    for i in range(self.num_ways):
                        with m.If(
                            (self.bypass & self.new_tag[i * (self.tag_size + 2) + self.tag_size + 1] & (self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag)) |
                            (~self.bypass & self.tag_read_dout[i * (self.tag_size + 2) + self.tag_size + 1] & (self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag))
                        ):
                            with m.If(self.csb):
                                m.d.comb += self.state_next.eq(State.IDLE)
                            with m.Else():
                                m.d.comb += self.state_next.eq(State.COMPARE)

                # In the WRITE state, state switches to:
                #   WRITE      if main memory didn't respond yet
                #   WAIT_WRITE if main memory responded
                with m.Case(State.WRITE):
                    with m.If(~self.main_stall):
                        m.d.comb += self.state_next.eq(State.WAIT_WRITE)

                # In the WAIT_WRITE state, state switches to:
                #   WAIT_WRITE if main memory didn't respond yet
                #   WAIT_READ  if main memory responded
                with m.Case(State.WAIT_WRITE):
                    with m.If(~self.main_stall):
                        m.d.comb += self.state_next.eq(State.WAIT_READ)

                # In the READ state, state switches to:
                #   READ      if main memory didn't respond yet
                #   WAIT_READ if main memory responded
                with m.Case(State.READ):
                    with m.If(~self.main_stall):
                        m.d.comb += self.state_next.eq(State.WAIT_READ)

                # In the WAIT_READ state, state switches to:
                #   IDLE    if CPU isn't sending a request
                #   COMPARE if CPU is sending a request
                with m.Case(State.WAIT_READ):
                    with m.If(~self.main_stall):
                        with m.If(self.csb):
                            m.d.comb += self.state_next.eq(State.IDLE)
                        with m.Else():
                            m.d.comb += self.state_next.eq(State.COMPARE)


    def add_request_block(self, m):
        """ Add request decode always block to cache design. """

        # In this block, CPU's request is decoded. Address is parsed
        # into tag, set and offset values, and write enable and data
        # input are saved in registers.

        m.d.comb += self.tag_next.eq(self.tag)
        m.d.comb += self.set_next.eq(self.set)
        m.d.comb += self.offset_next.eq(self.offset)
        m.d.comb += self.web_reg_next.eq(self.web_reg)
        m.d.comb += self.wmask_reg_next.eq(self.wmask_reg)
        m.d.comb += self.din_reg_next.eq(self.din_reg)

        # If rst is high, input registers are reset.
        # set register becomes 1 since it is going to be used to reset all
        # lines in the tag and use arrays.
        # way register becomes 0 since it is going to be used to reset all
        # ways in a tag line.
        with m.If(self.rst):
            m.d.comb += self.tag_next.eq(0)
            m.d.comb += self.set_next.eq(1)
            m.d.comb += self.offset_next.eq(0)
            m.d.comb += self.web_reg_next.eq(1)
            m.d.comb += self.wmask_reg_next.eq(0)
            m.d.comb += self.din_reg_next.eq(0)

        # If flush is high, input registers are not reset.
        # However, way and set registers becomes 0 since it is going
        # to be used to write dirty lines back to main memory.
        with m.Elif(self.flush):
            m.d.comb += self.set_next.eq(0)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, set register is used to reset all lines in
                # the tag and use arrays.
                with m.Case(State.RESET):
                    m.d.comb += self.set_next.eq(self.set + 1)

                # In the FLUSH state, set register is used to write all dirty lines
                # back to main memory.
                with m.Case(State.FLUSH):
                    with m.If(~self.main_stall & (self.way == self.num_ways - 1)):
                        m.d.comb += self.set_next.eq(self.set + 1)

                # In the IDLE state, the request is decoded.
                with m.Case(State.IDLE):
                    m.d.comb += self.tag_next.eq(self.addr[-self.tag_size:])
                    m.d.comb += self.set_next.eq(self.addr.bit_select(self.offset_size, self.set_size))
                    m.d.comb += self.offset_next.eq(self.addr[:self.offset_size+1])
                    m.d.comb += self.web_reg_next.eq(self.web)
                    m.d.comb += self.wmask_reg_next.eq(self.wmask)
                    m.d.comb += self.din_reg_next.eq(self.din)

                # In the COMPARE state, the request is decoded if current request
                # is hit.
                with m.Case(State.COMPARE):
                    for i in range(self.num_ways):
                        with m.If(
                            (self.bypass & self.new_tag[i * (self.tag_size + 2) + self.tag_size + 1] & (self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag)) |
                            (~self.bypass & self.tag_read_dout[i * (self.tag_size + 2) + self.tag_size + 1] & (self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag))
                        ):
                            m.d.comb += self.tag_next.eq(self.addr[-self.tag_size:])
                            m.d.comb += self.set_next.eq(self.addr.bit_select(self.offset_size, self.set_size))
                            m.d.comb += self.offset_next.eq(self.addr[:self.offset_size+1])
                            m.d.comb += self.web_reg_next.eq(self.web)
                            m.d.comb += self.wmask_reg_next.eq(self.wmask)
                            m.d.comb += self.din_reg_next.eq(self.din)

                # In the COMPARE state, the request is decoded if main memory
                # completed read request.
                with m.Case(State.WAIT_READ):
                    with m.If(~self.main_stall):
                        m.d.comb += self.tag_next.eq(self.addr[-self.tag_size:])
                        m.d.comb += self.set_next.eq(self.addr.bit_select(self.offset_size, self.set_size))
                        m.d.comb += self.offset_next.eq(self.addr[:self.offset_size+1])
                        m.d.comb += self.web_reg_next.eq(self.web)
                        m.d.comb += self.wmask_reg_next.eq(self.wmask)
                        m.d.comb += self.din_reg_next.eq(self.din)


    def add_output_block(self, m):
        """ Add output always block to cache design. """

        # In this block, cache's output signals, which are
        # stall and dout, are controlled.

        m.d.comb += self.stall.eq(1)
        # FIXME: Don't write 0 in testbench (might result in missed errors).
        m.d.comb += self.dout.eq(0)

        with m.Switch(self.state):

            # In the IDLE state, stall is low while there is no request from
            # the CPU.
            with m.Case(State.IDLE):
                m.d.comb += self.stall.eq(0)

            # In the COMPARE state, stall is low if the current request is hit.
            # Data output is valid if the request is hit and even if the current
            # request is write since read is non-destructive.
            with m.Case(State.COMPARE):
                # Check if current request is hit
                for i in range(self.num_ways):
                    with m.If(
                        (self.bypass & self.new_tag[i * (self.tag_size + 2) + self.tag_size + 1] & (self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag)) |
                        (~self.bypass & self.tag_read_dout[i * (self.tag_size + 2) + self.tag_size + 1] & (self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag))
                    ):
                        m.d.comb += self.stall.eq(0)
                        words_per_line = Const(self.words_per_line)
                        with m.If(self.bypass):
                            m.d.comb += self.dout.eq(self.new_data.word_select(i * words_per_line + self.offset, self.word_size))
                        with m.Else():
                            m.d.comb += self.dout.eq(self.data_read_dout.word_select(i * words_per_line + self.offset, self.word_size))

            # In the WAIT_READ state, stall is low and data output is valid main
            # memory answers the read request.
            # Data output is valid even if the current request is write since read
            # is non-destructive.
            # NOTE: No need to use bypass registers here since data hazard is not
            # possible.
            with m.Case(State.WAIT_READ):
                # Check if main memory answers to the read request
                with m.If(~self.main_stall):
                    m.d.comb += self.stall.eq(0)
                    m.d.comb += self.dout.eq(self.main_dout.word_select(self.offset, self.word_size))


    def add_replacement_block(self, m):
        """ Add replacement always block to cache design. """

        # In this block, use numbers are updated and evicted way
        # is selected according to LRU replacement policy.

        m.d.comb += self.way_next.eq(self.way)

        # If rst is high, way is reset and use numbers are reset.
        # way register becomes 0 since it is going to be used to reset all
        # ways in tag and use lines.
        with m.If(self.rst):
            m.d.comb += self.way_next.eq(0)
            m.d.comb += self.use_write_csb.eq(0)
            m.d.comb += self.use_write_addr.eq(0)
            m.d.comb += self.use_write_din.eq(0)

        # If flush is high, way is reset.
        # way register becomes 0 since it is going to be used to write all
        # data lines back to main memory.
        with m.Elif(self.flush):
            m.d.comb += self.way_next.eq(0)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, way register is used to reset all ways in tag
                # and use lines.
                with m.Case(State.RESET):
                    m.d.comb += self.use_write_csb.eq(0)
                    m.d.comb += self.use_write_addr.eq(self.set)
                    m.d.comb += self.use_write_din.eq(0)

                # In the FLUSH state, way register is used to write all data lines
                # back to main memory.
                # TODO: Flush should only write dirty lines back.
                with m.Case(State.FLUSH):
                    with m.If(~self.main_stall):
                        m.d.comb += self.way_next.eq(self.way + 1)

                # In the IDLE state, way is reset and the corresponding line from the
                # use array is requested.
                with m.Case(State.IDLE):
                    with m.If(~self.csb):
                        m.d.comb += self.way_next.eq(0)
                        m.d.comb += self.use_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))

                # In the COMPARE state, way is selected according to the replacement
                # policy of the cache.
                # Also use numbers are updated if current request is hit.
                with m.Case(State.COMPARE):
                    for i in range(self.num_ways):
                        # Find the least recently used way (the way having 0 use number)
                        with m.If(
                            (self.bypass & (self.new_use.word_select(i, self.way_size) == 0)) |
                            (~self.bypass & (self.use_read_dout.word_select(i, self.way_size) == 0))
                        ):
                            # Check if current request is a clean miss
                            m.d.comb += self.way_next.eq(i)
                            with m.If(
                                (self.bypass & (self.new_tag.bit_select(i * (self.tag_size + 2) + self.tag_size, 2) == Const(3, 2))) |
                                (~self.bypass & (self.tag_read_dout.bit_select(i * (self.tag_size + 2) + self.tag_size, 2) == Const(3, 2)))
                            ):
                                m.d.comb += self.use_read_addr.eq(self.set)
                    # Check if current request is a hit
                    for i in range(self.num_ways):
                        with m.If(
                            (self.bypass & self.new_tag[i * (self.tag_size + 2) + self.tag_size + 1] & (self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag)) |
                            (~self.bypass & self.tag_read_dout[i * (self.tag_size + 2) + self.tag_size + 1] & (self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag))
                        ):
                            m.d.comb += self.use_write_csb.eq(0)
                            m.d.comb += self.use_write_addr.eq(self.set)
                            # Each way in a set has its own use numbers. These numbers
                            # start from 0. Every time a way is needed to be evicted,
                            # the way having 0 use number is chosen.
                            # Every time a way is accessed (read or write), its corresponding
                            # use number is increased to the maximum value and other ways which
                            # have use numbers more than accessed way's use number are decremented
                            # by 1.
                            with m.If(self.bypass):
                                for j in range(self.num_ways):
                                    m.d.comb += self.use_write_din.word_select(j, self.way_size).eq(
                                        self.use_read_dout.word_select(j, self.way_size) - (self.use_read_dout.word_select(j, self.way_size) > self.use_read_dout.word_select(i, self.way_size))
                                    )
                                m.d.comb += self.use_write_din.word_select(i, self.way_size).eq(self.num_ways - 1)
                            with m.Else():
                                for j in range(self.num_ways):
                                    m.d.comb += self.use_write_din.word_select(j, self.way_size).eq(
                                        self.new_use.word_select(j, self.way_size) - (self.new_use.word_select(j, self.way_size) > self.new_use.word_select(i, self.way_size))
                                    )
                                m.d.comb += self.use_write_din.word_select(i, self.way_size).eq(self.num_ways - 1)
                            with m.If(~self.csb):
                                m.d.comb += self.use_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))

                # In the WAIT_WRITE and READ states, use line is read to update it
                # in the WAIT_READ state.
                with m.Case(State.WAIT_WRITE, State.READ):
                    m.d.comb += self.use_read_addr.eq(self.set)

                # In the WAIT_READ state, use numbers are updated.
                with m.Case(State.WAIT_READ):
                    m.d.comb += self.use_read_addr.eq(self.set)
                    with m.If(~self.main_stall):
                        # Each way in a set has its own use numbers. These numbers
                        # start from 0. Every time a way is needed to be evicted,
                        # the way having 0 use number is chosen.
                        # Every time a way is accessed (read or write), its corresponding
                        # use number is increased to the maximum value and other ways which
                        # have use numbers more than accessed way's use number are decremented
                        # by 1.
                        m.d.comb += self.use_write_csb.eq(0)
                        m.d.comb += self.use_write_addr.eq(self.set)
                        for i in range(self.num_ways):
                            m.d.comb += self.use_write_din.word_select(i, self.way_size).eq(
                                self.new_use.word_select(i, self.way_size) - (self.new_use.word_select(i, self.way_size) > self.new_use.word_select(self.way, self.way_size))
                            )
                        m.d.comb += self.use_write_din.word_select(self.way, self.way_size).eq(self.num_ways - 1)
                        with m.If(~self.csb):
                            m.d.comb += self.use_read_addr.eq(self.addr.bit_select(self.offset_size, self.set_size))


    def add_bypass_block(self, m):
        """ Add bypass register always block to cache design. """

        # In this block, bypass registers are controlled. Bypass
        # registers are used to prevent data hazard from SRAMs.
        # Data hazard can occur when there are read and write
        # requests to the same row at the same cycle.

        m.d.comb += self.bypass_next.eq(0)
        m.d.comb += self.new_tag_next.eq(0)
        m.d.comb += self.new_data_next.eq(0)
        m.d.comb += self.new_use_next.eq(0)

        with m.Switch(self.state):

            # In the COMPARE state, bypass registers can be used in the next
            # cycle if the current request is hit.
            # Otherwise, bypass registers won't probably be used; therefore,
            # will be reset.
            with m.Case(State.COMPARE):
                # Check if:
                #   CPU is sending a new request
                #   Current request is hit
                #   Next address is in the same set
                with m.If(~self.csb & (self.set == self.addr.bit_select(self.offset_size, self.set_size))):
                    for i in range(self.num_ways):
                        with m.If(
                            (self.bypass & self.new_tag[i * (self.tag_size + 2) + self.tag_size + 1] & (self.new_tag.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag)) |
                            (~self.bypass & self.tag_read_dout[i * (self.tag_size + 2) + self.tag_size + 1] & (self.tag_read_dout.bit_select(i * (self.tag_size + 2), self.tag_size) == self.tag))
                        ):
                            m.d.comb += self.bypass_next.eq(1)
                            with m.If(self.bypass):
                                m.d.comb += self.new_tag_next.eq(self.new_tag)
                                m.d.comb += self.new_data_next.eq(self.new_data)
                                for j in range(self.num_ways):
                                    m.d.comb += self.new_use_next.word_select(j, self.way_size).eq(
                                        self.new_use.word_select(j, self.way_size) - (self.new_use.word_select(j, self.way_size) > self.new_use.word_select(i, self.way_size))
                                    )
                                m.d.comb += self.new_use_next.word_select(i, self.way_size).eq(self.num_ways - 1)
                            with m.Else():
                                m.d.comb += self.new_tag_next.eq(self.tag_read_dout)
                                m.d.comb += self.new_data_next.eq(self.data_read_dout)
                                for j in range(self.num_ways):
                                    m.d.comb += self.new_use_next.word_select(j, self.way_size).eq(
                                        self.use_read_dout.word_select(j, self.way_size) - (self.use_read_dout.word_select(j, self.way_size) > self.use_read_dout.word_select(i, self.way_size))
                                    )
                                m.d.comb += self.new_use_next.word_select(i, self.way_size).eq(self.num_ways - 1)
                            # Update dirty bit in the tag line
                            m.d.comb += self.new_tag_next.word_select(i, self.tag_size + 2).eq(Cat(self.tag, Const(3, 2)))
                            # Perform the write request
                            # Write the word over the write mask
                            num_bytes_per_word = Const(self.num_bytes)
                            num_bytes_per_line = Const(self.num_bytes * self.words_per_line)
                            for j in range(self.num_bytes):
                                with m.If(self.wmask_reg[j]):
                                    m.d.comb += self.new_data_next.word_select(i * num_bytes_per_line + self.offset * num_bytes_per_word + j, 8).eq(self.din_reg.word_select(j, 8))

            # In the WAIT_READ state, bypass registers will be used in the next
            # cycle if the next request is in the same set.
            # Otherwise, bypass registers won't probably be used; therefore,
            # will be reset.
            # NOTE: No need to use bypass registers here since data hazard is not
            # possible.
            with m.Case(State.WAIT_READ):
                # Main memory is answering to the read request
                with m.If(~self.main_stall & ~self.csb & (self.set == self.addr.bit_select(self.offset_size, self.set_size))):
                    m.d.comb += self.bypass_next.eq(1)
                    m.d.comb += self.new_tag_next.eq(self.tag_read_dout)
                    # Check if:
                    #   CPU is sending a new request
                    #   Next address is in the same set
                    with m.Switch(self.way):
                        for i in range(self.num_ways):
                            with m.Case(i):
                                m.d.comb += self.new_tag_next.word_select(i, self.tag_size + 2).eq(Cat(self.tag, ~self.web_reg, Const(1, 1)))
                    m.d.comb += self.new_data_next.eq(self.data_read_dout)
                    with m.Switch(self.way):
                        for i in range(self.num_ways):
                            with m.Case(i):
                                m.d.comb += self.new_data_next.word_select(i, self.line_size).eq(self.main_dout)
                    for i in range(self.num_ways):
                        m.d.comb += self.new_use_next.word_select(i, self.way_size).eq(
                            self.use_read_dout.word_select(i, self.way_size) - (self.use_read_dout.word_select(i, self.way_size) > self.use_read_dout.word_select(self.way, self.way_size))
                        )
                    m.d.comb += self.new_use_next.word_select(self.way, self.way_size).eq(self.num_ways - 1)
                    # Perform the write request
                    with m.If(~self.web_reg):
                        # Write the word over the write mask
                        for i in range(self.num_bytes):
                            with m.If(self.wmask_reg[i]):
                                m.d.comb += self.new_data_next.word_select(self.way * num_bytes_per_line + self.offset * num_bytes_per_word + i, 8).eq(self.din_reg.word_select(i, 8))