# See LICENSE for licensing information.
#
# Copyright (c) 2021 Regents of the University of California and The Board
# of Regents for the Oklahoma Agricultural and Mechanical College
# (acting for and on behalf of Oklahoma State University)
# All rights reserved.
#
import os
from shutil import copyfile
from subprocess import call, DEVNULL, STDOUT
from re import findall
from core import core
from test_bench import test_bench
from test_data import test_data
from dram import dram
import debug
from globals import OPTS


class verify:
    """
    Class to generate files for verification and verify the design
    by running EDA tools.
    """

    def __init__(self, cache_config, name):

        cache_config.set_local_config(self)
        self.name = name

        self.core = core(cache_config, name)

        if OPTS.simulate:
            self.tb   = test_bench(cache_config, name)
            self.data = test_data(cache_config, name)
            self.dram = dram(cache_config, name)

        self.openram_run = False

        # Print subprocess outputs on the terminal
        # if verbose debug is enabled
        self.stdout = None if OPTS.verbose_level >= 2 else DEVNULL
        self.stderr = None if OPTS.verbose_level >= 2 else STDOUT


    def verify(self):
        """ Run the verifier. """

        debug.print_raw("Initializing verification...")

        # Write the CORE file
        core_path = OPTS.temp_path + "verify.core"
        debug.print_raw("  CORE: Writing to {}".format(core_path))
        self.core.write(core_path)

        if OPTS.simulate:
            self.simulate()

        if OPTS.synthesize:
            self.synthesize()

        debug.print_raw("  Verification completed.")


    def simulate(self):
        """
        Save required files and simulate the design
        by running an EDA tool's simulator.
        """

        openram_command = "python3 $OPENRAM_HOME/openram.py"

        debug.print_raw("  Initializing simulation...")
        debug.print_raw("    Writing simulation files...")

        # Write the test bench file
        tb_path = OPTS.temp_path + "test_bench.v"
        debug.print_raw("      Verilog (Test bench): Writing to {}".format(tb_path))
        self.tb.write(tb_path)

        # Write the test data file
        data_path = OPTS.temp_path + "test_data.v"
        debug.print_raw("      Verilog (Test data): Writing to {}".format(data_path))
        self.data.generate_data()
        self.data.write(data_path)

        # Write the DRAM file
        dram_path = OPTS.temp_path + "dram.v"
        debug.print_raw("      Verilog (DRAM): Writing to {}".format(dram_path))
        self.dram.write(dram_path)

        # Copy the generated cache Verilog file
        cache_path = OPTS.temp_path + self.name + ".v"
        debug.print_raw("    Copying the cache design file to the simulation subfolder")
        copyfile(OPTS.output_path + self.name + ".v", cache_path)

        # Copy the configuration files
        debug.print_raw("    Copying the config files to the simulation subfolder")
        self.copy_config_file(self.name + "_data_array_config.py", OPTS.temp_path)
        self.copy_config_file(self.name + "_tag_array_config.py", OPTS.temp_path)

        # Random replacement policy doesn't need a separate SRAM array
        if self.replacement_policy not in [None, "random"]:
            self.copy_config_file("{0}_{1}_array_config.py".format(self.name, self.replacement_policy), OPTS.temp_path)

        # Run OpenRAM to generate Verilog files of SRAMs
        debug.print_raw("    Running OpenRAM for the data array...")
        if call("{0} {1}_data_array_config.py".format(openram_command, OPTS.temp_path + self.name),
                cwd=OPTS.temp_path,
                shell=True,
                stdout=self.stdout,
                stderr=self.stderr) < 0:
            debug.error("    OpenRAM failed!", 1)

        debug.print_raw("    Running OpenRAM for the tag array...")
        if call("{0} {1}_tag_array_config.py".format(openram_command, OPTS.temp_path + self.name),
                cwd=OPTS.temp_path,
                shell=True,
                stdout=self.stdout,
                stderr=self.stderr) < 0:
            debug.error("    OpenRAM failed!", 1)

        # Random replacement policy doesn't need a separate SRAM array
        if self.replacement_policy not in [None, "random"]:
            debug.print_raw("    Running OpenRAM for the {} array".format(self.replacement_policy.upper()))
            if call("{0} {1}_{2}_array_config.py".format(openram_command, OPTS.temp_path + self.name, self.replacement_policy),
                    cwd=OPTS.temp_path,
                    shell=True,
                    stdout=self.stdout,
                    stderr=self.stderr) < 0:
                debug.error("    OpenRAM failed!", 1)

        self.openram_run = True

        # Run FuseSoc for simulation
        debug.print_raw("    Running FuseSoC for simulation...")

        debug.print_raw("      Adding simulation as library...")
        if call("fusesoc library add {0} {1}".format(self.name, OPTS.temp_path),
                cwd=OPTS.temp_path,
                shell=True,
                stdout=self.stdout,
                stderr=self.stderr) < 0:
            debug.error("    FuseSoC failed to add simulation core!", 1)

        debug.print_raw("      Running the simulation...")
        if call("fusesoc run --target=sim --no-export {}".format(self.core.core_name),
                cwd=OPTS.temp_path,
                shell=True,
                stdout=self.stdout,
                stderr=self.stderr) < 0:
            debug.error("    FuseSoC failed to run the simulation!", 1)

        # Delete the temporary CONF file
        # If this file is not deleted, it can cause simulations
        # to fail in the future.
        os.remove(OPTS.temp_path + "fusesoc.conf")

        # Check the result of the simulation
        if self.check_sim_result(OPTS.temp_path, "icarus.log"):
            debug.print_raw("    Simulation successful")
        else:
            debug.error("    Simulation failed!", 1)


    def check_sim_result(self, path, file_name):
        """ Read the log file of the simulation. """

        # Result of the simulation is supposed to be
        # at the end of the log file
        with open("{0}build/{1}/sim-icarus/{2}".format(path,
                                                       self.core.core_name.replace(":", "_"),
                                                       file_name)) as f:
            for line in f:
                pass
            return line.rstrip() == self.tb.success_message


    def synthesize(self):
        """
        Save required files and synthesize the design
        by running an EDA tool's synthesizer.
        """

        openram_command = "python3 $OPENRAM_HOME/openram.py"

        debug.print_raw("  Initializing synthesis...")
        debug.print_raw("    Writing synthesis files...")

        # Copy the generated cache Verilog file
        cache_path = OPTS.temp_path + self.name + ".v"
        debug.print_raw("    Copying the cache design file to the synthesis subfolder")
        copyfile(OPTS.output_path + self.name + ".v", cache_path)

        # If OpenRAM is run for simulation, no need to run it again
        if not self.openram_run:
            # Copy the configuration files
            debug.print_raw("    Copying the config files to the simulation subfolder")
            self.copy_config_file(self.name + "_data_array_config.py", OPTS.temp_path)
            self.copy_config_file(self.name + "_tag_array_config.py", OPTS.temp_path)

            # Random replacement policy doesn't need a separate SRAM array
            if self.replacement_policy not in [None, "random"]:
                self.copy_config_file("{0}_{1}_array_config.py".format(self.name, self.replacement_policy), OPTS.temp_path)

            # Run OpenRAM to generate Verilog files of SRAMs
            debug.print_raw("    Running OpenRAM for the data array...")
            if call("{0} {1}_data_array_config.py".format(openram_command, OPTS.temp_path + self.name),
                    cwd=OPTS.temp_path,
                    shell=True,
                    stdout=self.stdout,
                    stderr=self.stderr) < 0:
                debug.error("    OpenRAM failed!", 1)

            debug.print_raw("    Running OpenRAM for the tag array...")
            if call("{0} {1}_tag_array_config.py".format(openram_command, OPTS.temp_path + self.name),
                    cwd=OPTS.temp_path,
                    shell=True,
                    stdout=self.stdout,
                    stderr=self.stderr) < 0:
                debug.error("    OpenRAM failed!", 1)

            # Random replacement policy doesn't need a separate SRAM array
            if self.replacement_policy not in [None, "random"]:
                debug.print_raw("    Running OpenRAM for the {} array".format(self.replacement_policy.upper()))
                if call("{0} {1}_{2}_array_config.py".format(openram_command, OPTS.temp_path + self.name, self.replacement_policy),
                        cwd=OPTS.temp_path,
                        shell=True,
                        stdout=self.stdout,
                        stderr=self.stderr) < 0:
                    debug.error("    OpenRAM failed!", 1)
        else:
            debug.print_raw("    Skipping to run OpenRAM since already run")

        # Convert SRAM modules to blackbox
        debug.print_raw("    Converting OpenRAM modules to blackbox...")
        self.convert_to_blacbox(OPTS.temp_path + self.name + "_tag_array.v")
        self.convert_to_blacbox(OPTS.temp_path + self.name + "_data_array.v")

        if self.replacement_policy not in [None, "random"]:
            self.convert_to_blacbox(OPTS.temp_path + self.name + "_" + self.replacement_policy + "_array.v")

        # Run FuseSoc for synthesis
        debug.print_raw("    Running FuseSoC for synthesis...")

        debug.print_raw("      Adding synthesis as library...")
        if call("fusesoc library add {0} {1}".format(self.name, OPTS.temp_path),
                cwd=OPTS.temp_path,
                shell=True,
                stdout=self.stdout,
                stderr=self.stderr) < 0:
            debug.error("    FuseSoC failed to add synthesis core!", 1)

        debug.print_raw("      Running the synthesis...")
        if call("fusesoc run --target=synth --no-export {}".format(self.core.core_name),
                cwd=OPTS.temp_path,
                shell=True,
                stdout=self.stdout,
                stderr=self.stderr) < 0:
            debug.error("    FuseSoC failed to run the synthesis!", 1)

        # Delete the temporary CONF file
        # If this file is not deleted, it can cause syntheses
        # to fail in the future.
        os.remove(OPTS.temp_path + "fusesoc.conf")

        # Check the result of the synthesis
        if self.check_synth_result(OPTS.temp_path, "yosys.log"):
            debug.print_raw("    Synthesis successful")
        else:
            debug.error("    Synthesis failed!", 1)


    def convert_to_blacbox(self, file_path):
        """ Convert the given Verilog module file to blackbox. """

        keep = []

        with open(file_path, "r") as f:
            delete = False

            for line in f:
                if line.lstrip().startswith("reg"):
                    delete = True

                if not delete:
                    keep.append(line)

        keep.append("endmodule\n")

        f = open(file_path, "w")

        f.writelines(keep)

        f.close()


    def check_synth_result(self, path, file_name):
        """ Read the log file of the simulation. """

        error_prefix = "found and reported"

        # Check the error count lines
        with open("{0}build/{1}/synth-yosys/{2}".format(path,
                                                        self.core.core_name.replace(":", "_"),
                                                        file_name)) as f:
            for line in f:
                # TODO: How to check whether the synthesis was successful?
                # Check if error count is nonzero
                if line.find(error_prefix) != -1 and int(findall(r"\d+", line)[0]) != 0:
                    return False

        return True


    def copy_config_file(self, file_name, dest):
        """ Copy and modify the config file for simulation and synthesis. """

        new_file = open(dest + file_name, "w")

        with open(OPTS.output_path + file_name) as f:
            for line in f:
                if line.startswith("output_path"):
                    new_file.write("output_path = \"{}\"\n".format(dest))
                else:
                    new_file.write(line)

        # Verification needs only the Verilog files
        # This option will decrease OpenRAM's runtime (hopefully)
        new_file.write("netlist_only = True\n")

        new_file.close()