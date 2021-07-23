# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
"""
This is called globals.py, but it actually parses all the arguments
and performs the global OpenCache setup as well.
"""
import os
import debug
import shutil
import optparse
import options
import sys
import re
import copy
import importlib
import getpass

VERSION = "0.0.1"
NAME = "OpenCache v{}".format(VERSION)
USAGE = "opencache.py [options] <config file>\nUse -h for help.\n"

OPTS = options.options()
CHECKPOINT_OPTS = None


def parse_args():
    """ Parse the optional arguments for OpenCache """

    global OPTS

    option_list = {
        optparse.make_option("-o",
                             "--output",
                             dest="output_name",
                             help="Base output file name(s) prefix",
                             metavar="FILE"),
        optparse.make_option("-p", "--outpath",
                             dest="output_path",
                             help="Output file(s) location"),
        optparse.make_option("-v", "--verbose",
                             action="count",
                             dest="verbose_level",
                             help="Increase the verbosity level"),
        optparse.make_option("-k", "--keeptemp",
                             action="store_true",
                             dest="keep_temp",
                             help="Keep the contents of the temp directory after a successful run"),
        optparse.make_option("--sim",
                             action="store_true",
                             dest="simulate",
                             help="Enable verification via simulation"),
        optparse.make_option("--synth",
                             action="store_true",
                             dest="synthesize",
                             help="Enable verification via synthesis")
        # -h --help is implicit.
    }

    parser = optparse.OptionParser(option_list=option_list,
                                   description=NAME,
                                   usage=USAGE,
                                   version=VERSION)

    (options, args) = parser.parse_args(values=OPTS)

    return (options, args)


def print_banner():
    """ Conditionally print the banner to stdout """
    global OPTS

    if OPTS.is_unit_test:
        return

    debug.print_raw("|==============================================================================|")
    debug.print_raw("|=========" + NAME.center(60) + "=========|")
    debug.print_raw("|=========" + " ".center(60) + "=========|")
    debug.print_raw("|=========" + "VLSI Design and Automation Lab".center(60) + "=========|")
    debug.print_raw("|=========" + "Computer Science and Engineering Department".center(60) + "=========|")
    debug.print_raw("|=========" + "University of California Santa Cruz".center(60) + "=========|")
    debug.print_raw("|=========" + " ".center(60) + "=========|")
    user_info = "Usage help: openram-user-group@ucsc.edu"
    debug.print_raw("|=========" + user_info.center(60) + "=========|")
    dev_info = "Development help: openram-dev-group@ucsc.edu"
    debug.print_raw("|=========" + dev_info.center(60) + "=========|")
    debug.print_raw("|=========" + "See LICENSE for license info".center(60) + "=========|")
    debug.print_raw("|==============================================================================|")


def check_versions():
    """ Run some checks of required software versions. """

    # FIXME: Which version is required?
    major_python_version = sys.version_info.major
    minor_python_version = sys.version_info.minor
    major_required = 3
    minor_required = 5
    if not (major_python_version == major_required and minor_python_version >= minor_required):
        debug.error("Python {0}.{1} or greater is required.".format(major_required, minor_required), -1)


def init_opencache(config_file, is_unit_test=True):
    """ Initialize the paths, variables, etc. """

    check_versions()

    setup_paths()

    read_config(config_file, is_unit_test)

    fix_config()

    init_paths()

    global OPTS
    global CHECKPOINT_OPTS

    # This is a hack. If we are running a unit test and have checkpointed
    # the options, load them rather than reading the config file.
    # This way, the configuration is reloaded at the start of every unit test.
    # If a unit test fails,
    # we don't have to worry about restoring the old config values
    # that may have been tested.
    if is_unit_test and CHECKPOINT_OPTS:
        OPTS.__dict__ = CHECKPOINT_OPTS.__dict__.copy()
        return

    # Make a checkpoint of the options so we can restore
    # after each unit test
    if not CHECKPOINT_OPTS:
        CHECKPOINT_OPTS = copy.copy(OPTS)


def read_config(config_file, is_unit_test=True):
    """
    Read the configuration file that defines a few parameters. The
    config file is just a Python file that defines some config
    options. This will only actually get read the first time. Subsequent
    reads will just restore the previous copy (ask mrg)
    """
    global OPTS

    # it is already not an abs path, make it one
    if not os.path.isabs(config_file):
        config_file = os.getcwd() + "/" +  config_file

    # Make it a python file if the base name was only given
    config_file = re.sub(r'\.py$', "", config_file)

    # Expand the user if it is used
    config_file = os.path.expanduser(config_file)

    OPTS.config_file = config_file + ".py"
    # Add the path to the system path
    # so we can import things in the other directory
    dir_name = os.path.dirname(config_file)
    module_name = os.path.basename(config_file)

    # Check that the module name adheres to Python's module naming conventions.
    # This will assist the user in interpreting subsequent errors in loading
    # the module. Valid Python module naming is described here:
    #   https://docs.python.org/3/reference/simple_stmts.html#the-import-statement
    if not module_name.isidentifier():
        debug.error("Configuration file name is not a valid Python module name: "
                    "{0}. It should be a valid identifier.".format(module_name))

    # Prepend the path to avoid if we are using the example config
    sys.path.insert(0, dir_name)
    # Import the configuration file of which modules to use
    debug.info(1, "Configuration file is " + config_file + ".py")
    try:
        config = importlib.import_module(module_name)
    except:
        debug.error("Unable to read configuration file: {0}".format(config_file), 2)

    OPTS.overridden = {}
    for k, v in config.__dict__.items():
        # The command line will over-ride the config file
        # Note that if we re-read a config file, nothing will get read again!
        if k not in OPTS.__dict__:
            OPTS.__dict__[k] = v
            OPTS.overridden[k] = True

    OPTS.is_unit_test = is_unit_test


def fix_config():
    """ Fix and update options from the config file. """

    # Get default policies if not specified in the config file
    if OPTS.replacement_policy is None:
        from policy import ReplacementPolicy as RP
        OPTS.replacement_policy = RP.get_default()
    if OPTS.write_policy is None:
        from policy import WritePolicy as WP
        OPTS.write_policy = WP.get_default()

    # If config didn't set output name, make a reasonable default
    if OPTS.output_name == "":
        OPTS.output_name = "cache_{0}b_{1}b_{2}_{3!s}".format(OPTS.total_size,
                                                              OPTS.word_size,
                                                              OPTS.num_ways,
                                                              OPTS.replacement_policy)
        if OPTS.is_unit_test:
            OPTS.output_name = "uut"

    # If config didn't set SRAM array names, make reasonable defaults
    if OPTS.tag_array_name == "":
        OPTS.tag_array_name = "{}_tag_array".format(OPTS.output_name)
    if OPTS.data_array_name == "":
        OPTS.data_array_name = "{}_data_array".format(OPTS.output_name)
    if OPTS.use_array_name == "":
        OPTS.use_array_name = "{0}_{1!s}_array".format(OPTS.output_name,
                                                       OPTS.replacement_policy)

    # Massage the output path to be an absolute one
    if not OPTS.output_path.endswith('/'):
        OPTS.output_path += "/"
    if not OPTS.output_path.startswith('/'):
        OPTS.output_path = os.getcwd() + "/" + OPTS.output_path

    # Create a new folder for each process of unit tests
    if OPTS.is_unit_test:
        OPTS.output_path += "opencache_{0}_{1}/".format(getpass.getuser(),
                                                             os.getpid())

    # Create a new folder for this run
    OPTS.output_path += OPTS.output_name + "/"
    debug.info(1, "Output saved in " + OPTS.output_path)

    # Make a temp folder if not given
    # This folder is used for verification files
    if OPTS.temp_path == "":
        OPTS.temp_path = OPTS.output_path + "tmp/"


def end_opencache():
    """ Clean up OpenCache for a proper exit. """

    cleanup_paths()


def cleanup_paths():
    """
    We should clean up the temp directory after execution.
    """
    global OPTS

    if OPTS.keep_temp:
        debug.info(1, "Preserving temp directory: {}".format(OPTS.temp_path))
        return
    elif os.path.exists(OPTS.temp_path):
        purge_temp()


def purge_temp():
    """ Remove the temp folder. """

    debug.info(1, "Purging temp directory: {}".format(OPTS.temp_path))

    # Remove all files and subdirectories under the temp directory
    shutil.rmtree(OPTS.temp_path, ignore_errors=True)


def setup_paths():
    """ Include script directories to the sys path. """

    # TODO: Don't assume that OpenCache is run from generator/ dir
    home_path = os.getcwd()

    # # Add all of the subdirs to the python path
    subdir_list = [item for item in os.listdir(home_path) if os.path.isdir(os.path.join(home_path, item))]
    for subdir in subdir_list:
        full_path = "{0}/{1}".format(home_path, subdir)
        # Use sys.path.insert instead of sys.path.append
        # Python searches in sequential order and common
        # folders (such as verify) with OpenRAM can result
        # in importing wrong source codes.
        if "__pycache__" not in full_path:
            sys.path.insert(1, "{}".format(full_path))


def init_paths():
    """ Create the output directory if it doesn't exist """

    # Don't delete the output dir, it may have other files!
    # make the directory if it doesn't exist
    try:
        os.makedirs(OPTS.output_path, 0o750)
    except OSError as e:
        if e.errno == 17:  # errno.EEXIST
            os.chmod(OPTS.output_path, 0o750)
    except:
        debug.error("Unable to make output directory.", -1)

    # Make the temp folder if only needed
    if OPTS.simulate or OPTS.synthesize or OPTS.is_unit_test:
        try:
            os.makedirs(OPTS.temp_path, 0o750)
        except OSError as e:
            if e.errno == 17:  # errno.EEXIST
                os.chmod(OPTS.temp_path, 0o750)
        except:
            debug.error("Unable to make temp directory.", -1)


def report_status():
    """
    Check for valid arguments and report the info about the cache being generated.
    """
    global OPTS

    # Check if argument types are correct
    if type(OPTS.total_size) is not int:
        debug.error("{} is not an integer in config file.".format(OPTS.total_size))
    if type(OPTS.word_size) is not int:
        debug.error("{} is not an integer in config file.".format(OPTS.word_size))
    if type(OPTS.words_per_line) is not int:
        debug.error("{} is not an integer in config file.".format(OPTS.words_per_line))
    if type(OPTS.address_size) is not int:
        debug.error("{} is not an integer in config file.".format(OPTS.address_size))
    if type(OPTS.num_ways) is not int:
        debug.error("{} is not an integer in config file.".format(OPTS.num_ways))

    # Data array's total size should match the word size
    if OPTS.total_size % OPTS.word_size:
        debug.error("Total size is not divisible by word size.", -1)

    # Options below are not implemented yet
    if not OPTS.is_data_cache:
        debug.error("Instruction cache is not yet supported.", -1)
    if OPTS.write_policy != "write-back":
        debug.error("Only write-back policy is supported at the moment.", -1)
    if OPTS.return_type != "word":
        debug.error("Only returning word is supported at the moment.", -1)

    # Print cache info
    debug.print_raw("\nCache type: {}".format("Data" if OPTS.is_data_cache else "Instruction"))
    debug.print_raw("Word size: {}".format(OPTS.word_size))
    debug.print_raw("Words per line: {}".format(OPTS.words_per_line))
    debug.print_raw("Number of ways: {}".format(OPTS.num_ways))
    debug.print_raw("Replacement policy: {}".format(OPTS.replacement_policy.long_name()))
    debug.print_raw("Write policy: {}".format(OPTS.write_policy.long_name()))
    debug.print_raw("Return type: {}".format(OPTS.return_type.capitalize()))
    debug.print_raw("Data hazard: {}\n".format(OPTS.data_hazard))