# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#

class sim_cache:
    """
    This is a high level cache design used for simulation.
    """

    def __init__(self, cache_config):

        cache_config.set_local_config(self)

        self.reset()
        self.reset_dram()


    def reset(self):
        """ Reset the cache. """

        # These arrays are multi-dimensional.
        # First dimension is for sets.
        # Second dimension is for ways.
        # Third dimension is for words (for data array).
        self.valid_array = [[0] * self.num_ways for _ in range(self.num_rows)]
        self.dirty_array = [[0] * self.num_ways for _ in range(self.num_rows)]
        self.tag_array   = [[0] * self.num_ways for _ in range(self.num_rows)]
        self.data_array  = [[[None] * self.words_per_line for _ in range(self.num_ways)] for _ in range(self.num_rows)]

        if self.replacement_policy == "fifo":
            self.fifo_array = [0] * self.num_rows

        if self.replacement_policy == "lru":
            self.lru_array = [[0] * self.num_ways for _ in range(self.num_rows)]

        if self.replacement_policy == "random":
            # Random register is reset when rst is high.
            # During the RESET state, it keeps getting incremented.
            # Therefore, random is num_rows + 2 when the first
            # request is in the COMPARE state.
            self.random = 0
            self.update_random(self.num_rows + 2)


    def reset_dram(self):
        """ Reset the DRAM. """

        # DRAM list has a line in each row.
        self.dram = [[None] * self.words_per_line for _ in range((2 ** (self.tag_size + self.set_size)))]


    def flush(self):
        """ Write dirty data lines back to DRAM. """

        for row_i in range(self.num_rows):
            for way_i in range(self.num_ways):
                if self.valid_array[row_i][way_i] and self.dirty_array[row_i][way_i]:
                    old_tag  = self.tag_array[row_i][way_i]
                    old_data = self.data_array[row_i][way_i].copy()
                    self.dram[(old_tag << self.set_size) + row_i] = old_data

        # TODO: Update random counter after flush.


    def merge_address(self, tag_decimal, set_decimal, offset_decimal):
        """
        Create the address consists of given
        tag, set, and offset values.
        """

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

        if self.replacement_policy is None:
            return 0

        if self.replacement_policy == "fifo":
            return self.fifo_array[set_decimal]

        if self.replacement_policy == "lru":
            way = None
            for i in range(self.num_ways):
                if not self.lru_array[set_decimal][i]:
                    way = i
            return way

        if self.replacement_policy == "random":
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

        if way is not None: # Hit
            self.update_lru(set_decimal, way)
            self.update_random(1)
        else: # Miss
            way = self.way_to_evict(set_decimal)

            # Write-back
            if self.dirty_array[set_decimal][way]:
                old_tag  = self.tag_array[set_decimal][way]
                old_data = self.data_array[set_decimal][way].copy()
                self.dram[(old_tag << self.set_size) + set_decimal] = old_data
                self.update_random(4 + 1)

            # Bring data line from DRAM
            self.valid_array[set_decimal][way] = 1
            self.dirty_array[set_decimal][way] = 0
            self.tag_array[set_decimal][way]   = tag_decimal
            self.data_array[set_decimal][way]  = self.dram[(tag_decimal << self.set_size) + set_decimal].copy()

            self.update_fifo(set_decimal)
            self.update_lru(set_decimal, way)
            self.update_random(1 + 4 + 1)

        # Return the valid way
        return way


    def read(self, address):
        """ Read data from an address. """

        _, set_decimal, offset_decimal = self.parse_address(address)
        way = self.request(address)
        return self.data_array[set_decimal][way][offset_decimal]


    def write(self, address, data_input):
        """ Write data to an address. """

        _, set_decimal, offset_decimal = self.parse_address(address)
        way = self.request(address)
        self.dirty_array[set_decimal][way] = 1
        self.data_array[set_decimal][way][offset_decimal] = data_input


    def update_fifo(self, set_decimal):
        """ Update the FIFO number of the latest replaced set. """

        # Check if replacement policy matches
        if self.replacement_policy == "fifo":
            # Starting from 0, increase the FIFO number every time a
            # new data is brought from DRAM.
            #
            # When it reaches the max value, go back to 0 and proceed.
            self.fifo_array[set_decimal] += 1
            self.fifo_array[set_decimal] %= self.num_ways


    def update_lru(self, set_decimal, way):
        """ Update the LRU numbers of the latest used way. """

        # Check if replacement policy matches
        if self.replacement_policy == "lru":
            # There is a number for each way in a set. They are ordered
            # by their access time relative to each other.
            #
            # When a way is accessed (read or write), it is brought to
            # the top of the order (highest possible number) and numbers
            # which are more than its previous value are decreased by one.
            for i in range(self.num_ways):
                if self.lru_array[set_decimal][i] > self.lru_array[set_decimal][way]:
                    self.lru_array[set_decimal][i] -= 1
            self.lru_array[set_decimal][way] = self.num_ways - 1


    def update_random(self, cycles):
        """ Update the random counter for a number of cycles. """

        # Check if replacement policy matches
        if self.replacement_policy == "random":
            # In the real hardware, random caches have a register acting 
            # like a counter. This register is incremented at every posedge
            # of the clock.
            #
            # Since we cannot guarantee how many cycles a miss will take,
            # this register essentially has random values.
            self.random += cycles
            self.random %= self.num_ways