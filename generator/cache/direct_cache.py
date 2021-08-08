# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
from cache_base import cache_base
from nmigen import *
from state import State


class direct_cache(cache_base):
    """
    This is the design module of direct-mapped cache.
    """

    def __init__(self, cache_config, name):

        super().__init__(cache_config, name)


    def add_memory_block(self, m):
        """ Add memory controller always block to cache design. """

        # In this block, cache communicates with memory components which are
        # tag array, data array, and main memory.

        # If rst is high, state switches to RESET.
        # Registers, which are reset only once, are reset here.
        # In the RESET state, cache will set all tag array lines to 0.
        with m.If(self.rst):
            m.d.comb += self.tag_write_csb.eq(0)
            m.d.comb += self.tag_write_addr.eq(0)
            m.d.comb += self.tag_write_din.eq(0)

        # If flush is high, state switches to FLUSH.
        # In the FLUSH state, cache will write all data lines back to main
        # memory.
        with m.Elif(self.flush):
            m.d.comb += self.tag_read_addr.eq(0)
            m.d.comb += self.data_read_addr.eq(0)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, cache sends write request to the tag array
                # to reset the current set.
                # set register is incremented by the Request Decode Block.
                # When set register reaches the end, state switches to IDLE.
                with m.Case(State.RESET):
                    m.d.comb += self.tag_write_csb.eq(0)
                    m.d.comb += self.tag_write_addr.eq(self.set)
                    m.d.comb += self.tag_write_din.eq(0)

                # In the FLUSH state, cache sends write request to main memory.
                # set register is incremented by the Request Decode Block.
                # When set register reaches the end, state switches to IDLE.
                with m.Case(State.FLUSH):
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    # Check if current set is clean or main memory is available
                    with m.If(~self.tag_read_dout.dirty() | ~self.main_stall):
                        # Request the next tag and data lines from SRAMs.
                        m.d.comb += self.tag_read_addr.eq(self.set + 1)
                        m.d.comb += self.data_read_addr.eq(self.set + 1)
                    # Check if current set is dirty and main memory is available
                    with m.If(self.tag_read_dout.dirty() & ~self.main_stall):
                        # Update dirty bits in the tag line.
                        m.d.comb += self.tag_write_csb.eq(0)
                        m.d.comb += self.tag_write_addr.eq(self.set)
                        m.d.comb += self.tag_write_din.eq(Cat(self.tag_read_dout.tag(), 0b10))
                        # Send the write request to main memory.
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_web.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag_read_dout.tag()))
                        m.d.comb += self.main_din.eq(self.data_read_dout)

                # In the IDLE state, cache waits for CPU to send a new request.
                # Until there is a new request from the cache, stall is low.
                # When there is a new request from the cache stall is asserted,
                # request is decoded and corresponding tag and data lines are
                # read from internal SRAM arrays.
                with m.Case(State.IDLE):
                    # Read next lines from SRAMs even though CPU is not
                    # sending a new request since read is non-destructive.
                    m.d.comb += self.tag_read_addr.eq(self.addr.parse_set())
                    m.d.comb += self.data_read_addr.eq(self.addr.parse_set())

                # In the WAIT_HAZARD state, cache waits in this state for 1 cycle.
                # Read requests are sent to tag and data arrays.
                with m.Case(State.WAIT_HAZARD):
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)

                # In the COMPARE state, cache compares tags.
                with m.Case(State.COMPARE):
                    # Assuming that current request is miss, check if it is dirty miss
                    with self.check_dirty_miss(m):
                        # If main memory is busy, switch to WRITE and wait for main
                        # memory to be available.
                        with m.If(self.main_stall):
                            m.d.comb += self.tag_read_addr.eq(self.set)
                            m.d.comb += self.data_read_addr.eq(self.set)
                        # If main memory is available, switch to WAIT_WRITE and wait
                        # for main memory to complete writing.
                        with m.Else():
                            m.d.comb += self.main_csb.eq(0)
                            m.d.comb += self.main_web.eq(0)
                            m.d.comb += self.main_addr.eq(Cat(self.set, self.tag_read_dout.tag()))
                            m.d.comb += self.main_din.eq(self.data_read_dout)
                    # Else, assume that current request is clean miss
                    with self.check_clean_miss(m):
                        # If main memory is busy, switch to WRITE and wait for main
                        # memory to be available.
                        # If main memory is available, switch to WAIT_WRITE and wait
                        # for main memory to complete writing.
                        with m.If(~self.main_stall):
                            m.d.comb += self.main_csb.eq(0)
                            m.d.comb += self.main_addr.eq(Cat(self.set, self.tag))
                    # Check if current request is hit
                    with self.check_hit(m):
                        # Set main memory's csb to 1 again since it could be set 0 above
                        m.d.comb += self.main_csb.eq(1)
                        # Perform the write request
                        with m.If(~self.web_reg):
                            m.d.comb += self.tag_write_csb.eq(0)
                            m.d.comb += self.tag_write_addr.eq(self.set)
                            m.d.comb += self.tag_write_din.eq(Cat(self.tag, 0b11))
                            m.d.comb += self.data_write_csb.eq(0)
                            m.d.comb += self.data_write_addr.eq(self.set)
                            m.d.comb += self.data_write_din.eq(self.data_read_dout)
                            # Write the word over the write mask
                            # NOTE: This switch statement is written manually (not only with
                            # word_select) because word_select fails to generate correct case
                            # statements if offset calculation is a bit complex.
                            for i in range(self.num_bytes):
                                with m.If(self.wmask_reg[i]):
                                    with m.Switch(self.offset):
                                        for j in range(self.words_per_line):
                                            with m.Case(j):
                                                m.d.comb += self.data_write_din.byte(i, j).eq(self.din_reg.byte(i))
                        # Read next lines from SRAMs even though the CPU is not
                        # sending a new request since read is non-destructive.
                        m.d.comb += self.tag_read_addr.eq(self.addr.parse_set())
                        m.d.comb += self.data_read_addr.eq(self.addr.parse_set())

                # In the WRITE state, cache waits for main memory to be available.
                # When main memory is available, write request is sent.
                with m.Case(State.WRITE):
                    m.d.comb += self.tag_read_addr.eq(self.set)
                    m.d.comb += self.data_read_addr.eq(self.set)
                    # If main memory is busy, wait in this state.
                    # If main memory is available, switch to WAIT_WRITE and wait for
                    # main memory to complete writing.
                    with m.If(~self.main_stall):
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_web.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag_read_dout.tag()))
                        m.d.comb += self.main_din.eq(self.data_read_dout)

                # In the WAIT_WRITE state, cache waits for main memory to complete
                # writing.
                # When main memory completes writing, read request is sent.
                with m.Case(State.WAIT_WRITE):
                    # If main memory is busy, wait in this state.
                    # If main memory completes writing, switch to WAIT_READ and wait
                    # for main memory to complete reading.
                    with m.If(~self.main_stall):
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag))

                # In the READ state, cache waits for main memory to be available.
                # When main memory is available, read request is sent.
                # TODO: Is this state really necessary? WAIT_WRITE state may be used instead.
                with m.Case(State.READ):
                    # If main memory is busy, wait in this state.
                    # If main memory completes writing, switch to WAIT_READ and wait
                    # for main memory to complete reading.
                    with m.If(~self.main_stall):
                        m.d.comb += self.main_csb.eq(0)
                        m.d.comb += self.main_addr.eq(Cat(self.set, self.tag))

                # In the WAIT_READ state, cache waits for main memory to complete
                # reading.
                # When main memory completes reading, request is completed.
                with m.Case(State.WAIT_READ):
                    # If main memory is busy, cache waits in this state.
                    # If main memory completes reading, cache switches to:
                    #   IDLE    if CPU isn't sending a new request
                    #   COMPARE if CPU is sending a new request
                    with m.If(~self.main_stall):
                        # TODO: Use wmask feature of OpenRAM.
                        m.d.comb += self.tag_write_csb.eq(0)
                        m.d.comb += self.tag_write_addr.eq(self.set)
                        m.d.comb += self.tag_write_din.eq(Cat(self.tag, ~self.web_reg, 0b1))
                        m.d.comb += self.data_write_csb.eq(0)
                        m.d.comb += self.data_write_addr.eq(self.set)
                        m.d.comb += self.data_write_din.eq(self.main_dout)
                        # Perform the write request
                        with m.If(~self.web_reg):
                            # Write the word over the write mask
                            # NOTE: This switch statement is written manually (not only with
                            # word_select) because word_select fails to generate correct case
                            # statements if offset calculation is a bit complex.
                            for i in range(self.num_bytes):
                                with m.If(self.wmask_reg[i]):
                                    with m.Switch(self.offset):
                                        for j in range(self.words_per_line):
                                            with m.Case(j):
                                                m.d.comb += self.data_write_din.byte(i, j).eq(self.din_reg.byte(i))
                        # Read next lines from SRAMs even though the CPU is not
                        # sending a new request since read is non-destructive.
                        m.d.comb += self.tag_read_addr.eq(self.addr.parse_set())
                        m.d.comb += self.data_read_addr.eq(self.addr.parse_set())


    def add_state_block(self, m):
        """ Add state controller always block to cache design. """

        # In this block, cache's state is controlled. state flip-flop
        # register is changed in order to switch between states.

        # If rst is high, state switches to RESET.
        with m.If(self.rst):
            m.d.comb += self.state.eq(State.RESET)

        # If flush is high, state switches to FLUSH.
        with m.Elif(self.flush):
            m.d.comb += self.state.eq(State.FLUSH)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, state switches to IDLE if reset is completed.
                with m.Case(State.RESET):
                    # When set reaches the limit, the last write request is sent
                    # to the tag array.
                    with m.If(self.set == self.num_rows - 1):
                        m.d.comb += self.state.eq(State.IDLE)

                # In the FLUSH state, state switches to IDLE if flush is completed.
                with m.Case(State.FLUSH):
                    # If the last set is clean or main memory will receive the last
                    # write request, flush is completed.
                    # FIXME: Cache switches to IDLE while main memory is still writing
                    # the last data line. This may cause a simulation mismatch.
                    # This is the behavior that we probably want, so fix sim_cache
                    # instead.
                    with m.If((~self.tag_read_dout.dirty() | ~self.main_stall) & (self.set == self.num_rows - 1)):
                        m.d.comb += self.state.eq(State.IDLE)

                # In the IDLE state, state switches to COMPARE if CPU is sending
                # a new request.
                with m.Case(State.IDLE):
                    with m.If(~self.csb):
                        m.d.comb += self.state.eq(State.COMPARE)

                # In the WAIT_HAZARD state, state switches to COMPARE.
                # This state is used to prevent data hazard.
                # Data hazard might occur when there are read and write
                # requests to the same address of SRAMs.
                # This state delays the cache request 1 cycle so that read
                # requests will be performed after write is completed.
                with m.Case(State.WAIT_HAZARD):
                    m.d.comb += self.state.eq(State.COMPARE)

                # In the COMPARE state, state switches to:
                #   IDLE        if current request is hit and CPU isn't sending a new request
                #   COMPARE     if current request is hit and CPU is sending a new request
                #   WAIT_HAZARD if current request is hit and data hazard is possible
                #   WRITE       if current request is dirty miss and main memory is busy
                #   WAIT_WRITE  if current request is dirty miss and main memory is available
                #   READ        if current request is clean miss and main memory is busy
                #   WAIT_READ   if current request is clean miss and main memory is available
                with m.Case(State.COMPARE):
                    # Assuming that current request is miss, check if it is dirty miss
                    with self.check_dirty_miss(m):
                        with m.If(self.main_stall):
                            m.d.comb += self.state.eq(State.WRITE)
                        with m.Else():
                            m.d.comb += self.state.eq(State.WAIT_WRITE)
                    # Else, assume that current request is clean miss
                    with self.check_clean_miss(m):
                        with m.If(self.main_stall):
                            m.d.comb += self.state.eq(State.READ)
                        with m.Else():
                            m.d.comb += self.state.eq(State.WAIT_READ)
                    # Check if current request is hit
                    with self.check_hit(m):
                        with m.If(self.csb):
                            m.d.comb += self.state.eq(State.IDLE)
                        with m.Else():
                            with m.If(~self.web_reg & (self.set == self.addr.parse_set())):
                                m.d.comb += self.state.eq(State.WAIT_HAZARD)
                            with m.Else():
                                m.d.comb += self.state.eq(State.COMPARE)

                # In the WRITE state, state switches to:
                #   WRITE      if main memory didn't respond yet
                #   WAIT_WRITE if main memory responded
                with m.Case(State.WRITE):
                    with m.If(~self.main_stall):
                        m.d.comb += self.state.eq(State.WAIT_WRITE)

                # In the WAIT_WRITE state, state switches to:
                #   WAIT_WRITE if main memory didn't respond yet
                #   WAIT_READ  if main memory responded
                with m.Case(State.WAIT_WRITE):
                    with m.If(~self.main_stall):
                        m.d.comb += self.state.eq(State.WAIT_READ)

                # In the READ state, state switches to:
                #   READ      if main memory didn't respond yet
                #   WAIT_READ if main memory responded
                with m.Case(State.READ):
                    with m.If(~self.main_stall):
                        m.d.comb += self.state.eq(State.WAIT_READ)

                # In the WAIT_READ state, state switches to:
                #   IDLE        if CPU isn't sending a new request
                #   WAIT_HAZARD if data hazard is possible
                #   COMPARE     if CPU is sending a new request
                with m.Case(State.WAIT_READ):
                    with m.If(~self.main_stall):
                        with m.If(self.csb):
                            m.d.comb += self.state.eq(State.IDLE)
                        with m.Else():
                            with m.If(self.set == self.addr.parse_set()):
                                m.d.comb += self.state.eq(State.WAIT_HAZARD)
                            with m.Else():
                                m.d.comb += self.state.eq(State.COMPARE)


    def add_request_block(self, m):
        """ Add request decode always block to cache design. """

        # In this block, CPU's request is decoded. Address is parsed
        # into tag, set and offset values, and write enable and data
        # input are saved in registers.

        # If rst is high, input registers are reset.
        # set register becomes 1 since it is going to be used to reset
        # all lines in the tag array.
        with m.If(self.rst):
            m.d.comb += self.tag.eq(0)
            m.d.comb += self.set.eq(1)
            m.d.comb += self.offset.eq(0)
            m.d.comb += self.web_reg.eq(1)
            m.d.comb += self.wmask_reg.eq(0)
            m.d.comb += self.din_reg.eq(0)

        # If flush is high, input registers are not reset.
        # However, set register becomes 0 since it is going to be used to
        # write dirty lines back to main memory.
        with m.Elif(self.flush):
            m.d.comb += self.set.eq(0)

        with m.Else():
            with m.Switch(self.state):

                # In the RESET state, set register is used to reset all lines in
                # the tag array.
                with m.Case(State.RESET):
                    m.d.comb += self.set.eq(self.set + 1)

                # In the FLUSH state, set register is used to write all dirty lines
                # back to main memory.
                with m.Case(State.FLUSH):
                    # If current set is clean or main memory is available, increment
                    # the set register.
                    with m.If((~self.tag_read_dout.dirty() | ~self.main_stall)):
                        m.d.comb += self.set.eq(self.set + 1)

                # In the IDLE state, the request is decoded.
                with m.Case(State.IDLE):
                    m.d.comb += self.tag.eq(self.addr.parse_tag())
                    m.d.comb += self.set.eq(self.addr.parse_set())
                    m.d.comb += self.offset.eq(self.addr.parse_offset())
                    m.d.comb += self.web_reg.eq(self.web)
                    m.d.comb += self.wmask_reg.eq(self.wmask)
                    m.d.comb += self.din_reg.eq(self.din)

                # In the COMPARE state, the request is decoded if current request
                # is hit.
                with m.Case(State.COMPARE):
                    with self.check_hit(m):
                        m.d.comb += self.tag.eq(self.addr.parse_tag())
                        m.d.comb += self.set.eq(self.addr.parse_set())
                        m.d.comb += self.offset.eq(self.addr.parse_offset())
                        m.d.comb += self.web_reg.eq(self.web)
                        m.d.comb += self.wmask_reg.eq(self.wmask)
                        m.d.comb += self.din_reg.eq(self.din)

                # In the COMPARE state, the request is decoded if main memory
                # completed read request.
                with m.Case(State.WAIT_READ):
                    with m.If(~self.main_stall):
                        m.d.comb += self.tag.eq(self.addr.parse_tag())
                        m.d.comb += self.set.eq(self.addr.parse_set())
                        m.d.comb += self.offset.eq(self.addr.parse_offset())
                        m.d.comb += self.web_reg.eq(self.web)
                        m.d.comb += self.wmask_reg.eq(self.wmask)
                        m.d.comb += self.din_reg.eq(self.din)


    def add_output_block(self, m):
        """ Add the output always block to cache design. """

        # In this block, cache's output signals, which are stall and
        # dout, are controlled.

        with m.Switch(self.state):

            # In the IDLE state, stall is low while there is no request from
            # the CPU. When there is a request, state switches to COMPARE and
            # stall becomes high in the next cycle.
            with m.Case(State.IDLE):
                m.d.comb += self.stall.eq(0)

            # In the COMPARE state, stall is low if the current request is hit.
            # Data output is valid if the request is hit and even if the current
            # request is write since read is non-destructive.
            with m.Case(State.COMPARE):
                # Check if current request is hit
                with self.check_hit(m):
                    m.d.comb += self.stall.eq(0)
                    m.d.comb += self.dout.eq(self.data_read_dout.word(self.offset))

            # In the WAIT_READ state, stall is low and data output is valid when
            # main memory completes the read request.
            # Data output is valid even if the current request is write since read
            # is non-destructive.
            with m.Case(State.WAIT_READ):
                # Check if main memory answers to the read request
                with m.If(~self.main_stall):
                    m.d.comb += self.stall.eq(0)
                    m.d.comb += self.dout.eq(self.main_dout.word(self.offset))