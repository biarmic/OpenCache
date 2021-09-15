# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
from random import randrange
from policy import ReplacementPolicy as RP
from .sim_dram import DRAM_DELAY
from globals import OPTS


class sim_cache:
    """
    This is an high level cache design used for simulation.
    """

    def __init__(self, cache_config):

        cache_config.set_local_config(self)

        self.reset()
        self.reset_dram()


    def reset(self):
        """ Reset the cache and return the number of stall cycles. """

        # These arrays are multi-dimensional.
        # First dimension is for sets.
        # Second dimension is for ways.
        # Third dimension is for words (for data array).
        self.valid_array = [[0] * self.num_ways for _ in range(self.num_rows)]
        self.dirty_array = [[0] * self.num_ways for _ in range(self.num_rows)]
        self.tag_array   = [[0] * self.num_ways for _ in range(self.num_rows)]
        self.data_array  = [[[0] * self.words_per_line for _ in range(self.num_ways)] for _ in range(self.num_rows)]

        # Previous request is used to detect data hazard
        self.prev_hit = False
        self.prev_web = 1
        self.prev_set = None

        if OPTS.replacement_policy == RP.FIFO:
            self.fifo_array = [0] * self.num_rows

        if OPTS.replacement_policy == RP.LRU:
            self.lru_array = [[0] * self.num_ways for _ in range(self.num_rows)]

        if OPTS.replacement_policy == RP.RANDOM:
            # Random register is reset when rst is high.
            # During the RESET state, it keeps getting incremented.
            # It starts with unknown. Cache sets it 0 first, then increments.
            # Therefore, random is equal to num_rows when the first request is
            # in the COMPARE state.
            self.random = 0
            self.update_random(self.num_rows + 1)

        # Normally we would return 1 less stall cycles since test_data.v waits
        # for 1 cycle in order to submit the request. However, cache spends 1
        # more cycle when switching to the RESET state.
        return self.num_rows + 1 - 1


    def reset_dram(self):
        """ Reset the DRAM. """

        # DRAM list has a line in each row
        self.dram = [[0] * self.words_per_line for _ in range((2 ** self.dram_address_size))]

        # Initialize DRAM with random data
        for line_i in range(2 ** self.dram_address_size):
            for word_i in range(self.words_per_line):
                self.dram[line_i][word_i] = randrange(1 << self.word_size)

        # Remaining DRAM stall cycles.
        # This is used to calculate how many cycles are needed to calculate
        # the stall after a flush is completed (maybe other cases as well?).
        self.dram_stalls = 0


    def flush(self):
        """
        Write dirty data lines back to DRAM and return the number of stall
        cycles.
        """

        # Start with 1 stall cycle if cache enters FLUSH_HAZARD
        stalls = int(OPTS.data_hazard and self.prev_set == 0)
        for row_i in range(self.num_rows):
            for way_i in range(self.num_ways):
                stalls += 1
                self.dram_stalls = max(self.dram_stalls - 1, 0)
                if self.valid_array[row_i][way_i] and self.dirty_array[row_i][way_i]:
                    tag  = self.tag_array[row_i][way_i]
                    data = self.data_array[row_i][way_i].copy()
                    self.dirty_array[row_i][way_i] = 0
                    self.dram[(tag << self.set_size) + row_i] = data

                    # Cache will wait in the FLUSH state if DRAM hasn't completed
                    # the last write request.
                    stalls += self.dram_stalls
                    self.dram_stalls = DRAM_DELAY + 1

        # Add 1 more cycle for switching to IDLE
        stalls += 1
        self.dram_stalls = max(self.dram_stalls - 1, 0)
        self.update_random(stalls)

        # Reset previous request
        self.prev_hit = False
        self.prev_web = 1
        self.prev_set = None

        # Return 1 less stall cycles since test_data.v waits for 1 cycle
        # in order to submit the request.
        return stalls - 1


    def merge_address(self, tag_decimal, set_decimal, offset_decimal):
        """ Create the address consists of given tag, set, and offset values. """

        tag_binary    = "{0:0{1}b}".format(tag_decimal, self.tag_size)
        set_binary    = "{0:0{1}b}".format(set_decimal, self.set_size)
        offset_binary = "{0:0{1}b}".format(offset_decimal, self.offset_size)

        address_binary  = tag_binary + set_binary + offset_binary
        address_decimal = int(address_binary, 2)

        return address_decimal


    def parse_address(self, address):
        """ Parse the given address into tag, set, and offset values. """

        address_binary = "{0:0{1}b}".format(address, self.address_size)
        tag_binary     = address_binary[:self.tag_size]
        set_binary     = address_binary[self.tag_size:self.tag_size + self.set_size]
        offset_binary  = address_binary[-self.offset_size:]

        tag_decimal    = int(tag_binary, 2)
        set_decimal    = int(set_binary, 2)
        offset_decimal = int(offset_binary, 2)

        return (tag_decimal, set_decimal, offset_decimal)


    def find_way(self, address):
        """ Find the way which has the given address' data. """

        tag_decimal, set_decimal, _ = self.parse_address(address)

        for way in range(self.num_ways):
            if self.valid_array[set_decimal][way] and self.tag_array[set_decimal][way] == tag_decimal:
                return way

        # Return None if not found
        return None


    def is_dirty(self, address):
        """ Return the dirty bit of the given address. """

        _, set_decimal, _ = self.parse_address(address)
        way = self.find_way(address)

        if way is not None:
            return self.dirty_array[set_decimal][way]

        # Return None if not found
        return None


    def way_to_evict(self, set_decimal):
        """ Return the way to evict according to the replacement policy. """

        if OPTS.replacement_policy == RP.NONE:
            return 0

        if OPTS.replacement_policy == RP.FIFO:
            return self.fifo_array[set_decimal]

        if OPTS.replacement_policy == RP.LRU:
            way = None
            for i in range(self.num_ways):
                if not self.lru_array[set_decimal][i]:
                    way = i
            return way

        if OPTS.replacement_policy == RP.RANDOM:
            way = None
            for i in range(self.num_ways):
                if not self.valid_array[set_decimal][i]:
                    way = i
            if way is None:
                way = self.random
            return way


    def request(self, address):
        """ Prepare arrays for a request of address. """

        tag_decimal, set_decimal, _ = self.parse_address(address)
        way = self.find_way(address)
        way_evict = None

        # Increment the random counter if cache enters WAIT_HAZARD
        self.update_random(int(self.is_data_hazard(address)))

        if way is not None: # Hit
            self.update_lru(set_decimal, way)
            self.update_random(1)
        else: # Miss
            way_evict = self.way_to_evict(set_decimal)

            # Write-back
            if self.dirty_array[set_decimal][way_evict]:
                old_tag  = self.tag_array[set_decimal][way_evict]
                old_data = self.data_array[set_decimal][way_evict].copy()
                self.dram[(old_tag << self.set_size) + set_decimal] = old_data
                self.update_random(DRAM_DELAY + 1)

            # Bring data line from DRAM
            self.valid_array[set_decimal][way_evict] = 1
            self.dirty_array[set_decimal][way_evict] = 0
            self.tag_array[set_decimal][way_evict]   = tag_decimal
            self.data_array[set_decimal][way_evict]  = self.dram[(tag_decimal << self.set_size) + set_decimal].copy()

            self.update_fifo(set_decimal)
            self.update_lru(set_decimal, way_evict)
            self.update_random(1 + DRAM_DELAY + 1)

        # Update previous request variables
        self.prev_hit = way is not None
        self.prev_web = 1
        self.prev_set = set_decimal

        way = way if way_evict is None else way_evict

        # Return the valid way
        return way


    def read(self, address):
        """ Read data from an address. """

        _, set_decimal, offset_decimal = self.parse_address(address)
        way = self.request(address)
        return self.data_array[set_decimal][way][offset_decimal]


    def write(self, address, mask, data_input):
        """ Write data to an address. """

        _, set_decimal, offset_decimal = self.parse_address(address)
        way = self.request(address)
        self.dirty_array[set_decimal][way] = 1

        # Write input data over the write mask
        orig_data = self.data_array[set_decimal][way][offset_decimal]
        wr_data = 0 if self.num_masks else data_input

        for i in range(self.num_masks):
            part = data_input if mask[-(i + 1)] == "1" else orig_data
            part = (part >> (i * self.write_size)) % (1 << self.write_size)
            wr_data += part << (i * self.write_size)

        self.data_array[set_decimal][way][offset_decimal] = wr_data

        # Update previous write enable
        self.prev_web = 0


    def stall_cycles(self, address):
        """ Return the number of stall cycles for a request of address. """

        stall_cycles = int(self.is_data_hazard(address))

        # In order to calculate the stall cycles correctly, random counter
        # needs to be updated temporarily here.
        # If there is a data hazard, cache stalls in WAIT_HAZARD state, which
        # results in incrementing the random counter. Therefore, we will
        # increment it here.
        if self.is_data_hazard(address):
            self.update_random(1)

        if self.find_way(address) is None:
            # Stalls 1 cycle in the COMPARE state since the request is a miss
            stall_cycles += 1

            # If DRAM is not yet ready and the request is miss, cache needs to
            # wait until DRAM is ready
            stall_cycles += self.dram_stalls
            self.dram_stalls = 0

            # Find the evicted address
            _, set_decimal, _ = self.parse_address(address)
            evicted_way = self.way_to_evict(set_decimal)
            is_dirty    = self.dirty_array[set_decimal][evicted_way]

            # If a way is written back before being replaced, cache stalls for
            # 2n+1 cycles in total:
            # - n while writing
            # - 1 for sending the read request to DRAM
            # - n while reading
            stall_cycles += (DRAM_DELAY * 2 + 1 if is_dirty else DRAM_DELAY)

        # After the calculation is done, the random counter should be decremented
        if self.is_data_hazard(address):
            self.update_random(-1)

        return stall_cycles


    def is_data_hazard(self, address):
        """ Return whether a data hazard is detected. """

        # Return false if data_hazard is disabled
        if not OPTS.data_hazard:
            return False

        _, set_decimal, _ = self.parse_address(address)

        # No data hazard if this is the first request or current request is not
        # in the same set with the previous request
        if self.prev_set is None or set_decimal != self.prev_set:
            return False

        if OPTS.replacement_policy == RP.LRU:
            # In LRU cache, use bits are updated in each access.
            # Therefore, when there are two requests to the same set, data
            # hazard on LRU SRAM might occur.
            return True
        else:
            # If previous request was hit and write If previous request was miss
            return (self.prev_hit and not self.prev_web) or (not self.prev_hit)

        return False


    def update_fifo(self, set_decimal):
        """ Update the FIFO number of the latest replaced set. """

        # Check if replacement policy matches
        if OPTS.replacement_policy == RP.FIFO:
            # Starting from 0, increase the FIFO number every time a new data
            # is brought from DRAM.
            # When it reaches the max value, go back to 0 and proceed.
            self.fifo_array[set_decimal] += 1
            self.fifo_array[set_decimal] %= self.num_ways


    def update_lru(self, set_decimal, way):
        """ Update the LRU numbers of the latest used way. """

        # Check if replacement policy matches
        if OPTS.replacement_policy == RP.LRU:
            # There is a number for each way in a set. They are ordered by their
            # access time relative to each other.
            # When a way is accessed (read or write), it is brought to the top
            # of the order (highest possible number) and numbers which are more
            # than its previous value are decreased by one.
            for i in range(self.num_ways):
                if self.lru_array[set_decimal][i] > self.lru_array[set_decimal][way]:
                    self.lru_array[set_decimal][i] -= 1
            self.lru_array[set_decimal][way] = self.num_ways - 1


    def update_random(self, cycles):
        """ Update the random counter for a number of cycles. """

        # Check if replacement policy matches
        if OPTS.replacement_policy == RP.RANDOM:
            # In the real hardware, random caches have a register acting like a
            # counter. This register is incremented at every posedge of the clock.
            # Since we cannot guarantee how many cycles a miss will take, this
            # register essentially has random values.
            self.random += cycles
            self.random %= self.num_ways