# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
import optparse


class options(optparse.Values):
    """
    Class for holding all of the OpenCache options.
    All of these options can be over-riden in a configuration file that is the
    sole required command-line positional argument for opencache.py.
    """

    #############################
    #   Configuration options   #
    #############################

    # These parameters must be specified by user in config file.
    # total_size = 0
    # word_size = 0
    # words_per_line = 0
    # address_size = 0

    # Write size is used to create write masks
    # Write mask will not be used if not specified
    write_size = None

    # Currently supports direct and n-way caches
    num_ways = 1
    # Replacement policy of the cache
    replacement_policy = None

    # Cache can be write-back or write-through
    #! Write-through is not yet supported
    write_policy = None
    # Cache can be a data cache or an instruction cache
    #! Instruction cache is not yet supported
    is_data_cache = True
    # Cache can return a word or a line of words
    return_type = "word"

    # Data hazard might occur when the same location is read and written at the
    # same cycle. If SRAM arrays are guaranteed to be data hazard proof, this
    # can be set False.
    data_hazard = True

    # Define the output file paths
    output_path = "outputs/"
    # Define the output file base name
    output_name = ""

    # Internal SRAM file and module names
    tag_array_name = ""
    data_array_name = ""
    use_array_name = ""

    # Trim unnecessary signals generated by yosys
    trim_verilog = True

    # Overwrite OpenRAM options. For example:
    # openram_options = {
    #     "tech_name": "freepdk45"
    # }
    openram_options = None

    # Print the banner at startup
    print_banner = True

    #############################
    #     Unit test options     #
    #############################

    # Temp path for verification and unit testing
    temp_path = ""
    # Keep verification
    keep_temp = False

    # Verify the design by simulating
    simulate = False
    # Verify the design by synthesizing
    synthesize = False

    # OpenRAM needs to be run for verification. If the output of it has already
    # been generated, this can be set False for faster verification.
    run_openram = True
    # OpenRAM creates many files that are not used for verification.
    # Set this True to keep those files after OpenRAM runs.
    keep_openram_files = False

    # Number of read/write operations in the simulation
    # Random data are written and read from random addresses
    sim_size = 64

    # Number of threads for regression testing
    num_threads = 1

    verbose_level = 0

    debug = False