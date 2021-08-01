# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
from random import randrange, choice
from sim_cache import sim_cache


class test_data:
    """
    Class to generate the test data file for simulation.
    """

    def __init__(self, cache_config, name):

        cache_config.set_local_config(self)
        self.name = name
        self.sc = sim_cache(cache_config)


    def generate_data(self, test_size=16):
        """  Generate random test data and expected outputs. """

        self.web   = [] # Write enable
        # TODO: Write test data for write mask
        self.wmask = [] # Write mask
        self.addr  = [] # Address
        self.data  = [] # Data input/output
        self.stall = [] # Number of stall cycles after the request

        # TODO: How to create random data in a smart way?
        # Write random data to random addresses initially
        for i in range(test_size):
            random_tag = randrange(2 ** self.tag_size)
            # Write to first two sets only so that
            # we can test replacement
            random_set = randrange(2)
            random_offset = randrange(2 ** self.offset_size)
            random_address = self.sc.merge_address(random_tag, random_set, random_offset)

            self.web.append(0)
            self.wmask.append("1" * self.num_bytes)
            self.addr.append(random_address)
            # Data written should not be 0 since cache output is
            # 0 by default
            self.data.append(randrange(1, 2 ** self.word_size))
            self.stall.append(0)

        indices = list(range(test_size))

        # Read from random addresses which are written to in the first half
        while len(indices) > 0:
            index = choice(indices)

            self.web.append(1)
            self.wmask.append("0" * self.num_bytes)
            self.addr.append(self.addr[index])
            # If the same address is written twice, this data may be old.
            # Therefore, data values for read operations are going to be
            # overwritten in the next for loop.
            self.data.append(self.data[index])
            self.stall.append(0)

            indices.remove(index)

        # Update stall values
        for i in range(len(self.web)):
            # Get the number of stall cycles
            self.stall[i] = self.sc.stall_cycles(self.addr[i])
            if self.web[i]:
                # Overwrite data for read to prevent bugs
                # NOTE: If the same address is written twice,
                # this data could be old.
                self.data[i] = self.sc.read(self.addr[i])
            else:
                self.sc.write(self.addr[i], self.data[i])


    def write(self, data_path):
        """ Write the test data file. """

        test_count = 0

        self.tdf = open(data_path, "w")

        self.tdf.write("// Initial delay to align with the cache and SRAMs.\n")
        self.tdf.write("// SRAMs return data at the negedge of the clock.\n")
        self.tdf.write("// Therefore, cache's output will be valid after the negedge.\n")
        self.tdf.write("#(CLOCK_DELAY + DELAY + 1);\n\n")

        # Check stall during reset
        self.tdf.write("// No operation while reset (Test #{})\n".format(test_count))
        # Check for num_rows-1 stall cycles since
        # stall will be low at the last cycle
        # (which is the cycle #num_rows)
        self.tdf.write("check_stall({0}, {1});\n\n".format(self.num_rows, test_count))

        test_count += 1

        # Check requests
        for i in range(len(self.web)):
            self.tdf.write("// {0} operation on address {1} (Test #{2})\n".format("Read" if self.web[i] else "Write",
                                                                                  self.addr[i],
                                                                                  test_count))

            self.tdf.write("cache_csb   = 0;\n")
            self.tdf.write("cache_web   = {};\n".format(self.web[i]))
            self.tdf.write("cache_wmask = {0}'b{1};\n".format(self.num_bytes, self.wmask[i]))
            self.tdf.write("cache_addr  = {};\n".format(self.addr[i]))

            if not self.web[i]:
                self.tdf.write("cache_din   = {};\n".format(self.data[i]))

            self.tdf.write("\n#(CLOCK_DELAY * 2);\n\n")

            if self.stall[i]:
                self.tdf.write("check_stall({0}, {1});\n\n".format(self.stall[i], test_count))

            # Check read request after stalls
            if self.web[i]:
                self.tdf.write("check_dout({0}, {1});\n\n".format(self.data[i], test_count))

            test_count += 1

        self.tdf.write("end_simulation();\n")
        self.tdf.write("$finish;\n")

        self.tdf.close()