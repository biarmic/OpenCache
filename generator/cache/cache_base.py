# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
from design import design
from logic import logic
from configuration import configuration
from cache_signal import CacheSignal


class cache_base(design, logic, configuration):
    """
    This is the abstract parent class of cache modules.
    Some common methods among different cache modules are implemented here.
    """

    def __init__(self, cache_config, name):
        design.__init__(self)
        logic.__init__(self)
        configuration.__init__(self)

        cache_config.set_local_config(self)
        self.name = name

        # Copy configs to CacheSignal class for calculations
        cache_config.set_local_config(CacheSignal)


    def check_dirty_miss(self, m, way=0):
        """ Return nMigen context manager instance to check dirty miss. """

        # Assume dirty miss if valid and dirty bits of the way are set
        return m.If(self.tag_read_dout.valid(way) & self.tag_read_dout.dirty(way))


    def check_clean_miss(self, m):
        """ Return nMigen context manager instance to check clean miss. """

        # Assume clean miss if not dirty miss
        return m.Else()


    def check_hit(self, m, way=0):
        """ Return nMigen context manager instance to check hit. """

        # Request is hit if valid bit is set and address' tag matches the way's tag
        return m.If(self.tag_read_dout.valid(way) & (self.tag_read_dout.tag(way) == self.tag))