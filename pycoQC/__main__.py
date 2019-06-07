#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~#
# Standard library imports
import argparse
import sys
import os
import json
import textwrap

# Third party imports
import plotly.offline as py
from jinja2 import Environment, PackageLoader, Template

# Local imports
from pycoQC.pycoQC import pycoQC
from pycoQC.Fast5_to_seq_summary import Fast5_to_seq_summary
from pycoQC.common import *
from pycoQC import __version__ as package_version
from pycoQC import __name__ as package_name

#~~~~~~~~~~~~~~Fast5_to_seq_summary CLI ENTRY POINT~~~~~~~~~~~~~~#
def main_Fast5_to_seq_summary (args=None):
    if args is None:
        args = sys.argv[1:]

    # Define parser object
    parser = argparse.ArgumentParser(
        description ="Fast5_to_seq_summary generate a sequencing summary like file from a directory containing Fast5 files")
    parser.add_argument('--version', '-v', action='version', version="{} v{}".format(package_name, package_version))

    # Define arguments
    parser.add_argument("--fast5_dir", "-f", required=True, type=str,
        help="""Directory containing fast5 files. Can contain multiple subdirectories""")
    parser.add_argument("--seq_summary_fn", "-s", required=True, type=str,
        help="""path of the summary sequencing file where to write the data extracted from the fast5 files""")
    parser.add_argument("--max_fast5", type=int, default=0,
        help="Maximum number of file to try to parse. 0 to deactivate (default: %(default)s)")
    parser.add_argument("--threads", "-t", type=int, default=4,
        help="Total number of threads to use. 1 thread is used for the reader and 1 for the writer. Minimum 3 (default: %(default)s)")
    parser.add_argument("--basecall_id", type=int, default=0,
        help="id of the basecalling group. By default leave to 0, but if you perfome multiple basecalling on the same fast5 files, this can be used to indicate the corresponding group (1, 2 ...) (default: %(default)s)")
    parser.add_argument("--fields", type=str, nargs="+", default=["read_id", "run_id", "channel", "start_time", "sequence_length_template", "mean_qscore_template", "calibration_strand_genome_template", "barcode_arrangement"],
        help="list of field names corresponding to attributes to try to fetch from the fast5 files (default: %(default)s)")
    parser.add_argument("--include_path", action='store_true', default=False,
        help="If given, the absolute path to the corresponding file is added in an extra column (default: %(default)s)")
    parser.add_argument("--verbose_level", type=int, default=0,
        help="Level of verbosity, from 2 (Chatty) to 0 (Nothing) (default: %(default)s)")

    # Try to parse arguments
    args = parser.parse_args()

    # Run main function
    Fast5_to_seq_summary (
        fast5_dir = args.fast5_dir,
        seq_summary_fn = args.seq_summary_fn,
        max_fast5 = args.max_fast5,
        threads = args.threads,
        basecall_id = args.basecall_id,
        fields = args.fields,
        include_path = args.include_path,
        verbose_level = args.verbose_level)

#~~~~~~~~~~~~~~pycoQC CLI ENTRY POINT~~~~~~~~~~~~~~#
def main_pycoQC (args=None):
    if args is None:
        args = sys.argv[1:]

    # Define parser object
    parser = argparse.ArgumentParser(
        formatter_class = argparse.RawDescriptionHelpFormatter,
        description = textwrap.dedent("""
            pycoQC computes metrics and generates interactive QC plots from the sequencing summary report generated by Oxford Nanopore technologies basecallers\n
            * Minimal usage
                pycoQC -f sequencing_summary.txt -o pycoQC_output.html
            * Including Guppy barcoding file + html output + json output + log output
                pycoQC -f sequencing_summary.txt -b barcoding_sequencing.txt -o pycoQC_output.html -j pycoQC_output.json -g pycoQC.log"""))
    parser.add_argument('--version', action='version', version="{} v{}".format(package_name, package_version))

    # Define arguments
    parser_io = parser.add_argument_group('Input/output options')
    parser_io.add_argument("--summary_file", "-f", default="", type=str, nargs='+',
        help=textwrap.dedent("""Path to a sequencing_summary generated by Albacore 1.0.0 + (read_fast5_basecaller.py) / Guppy 2.1.3+ (guppy_basecaller).
            One can also pass multiple space separated file paths or a UNIX style regex matching multiple files (Required)"""))
    parser_io.add_argument("--barcode_file", "-b", default="", type=str, nargs='+',
        help=textwrap.dedent("""Path to a barcode_summary_file generated by Guppy 2.1.3+ (guppy_barcoder).
            One can also pass multiple space separated file paths or a UNIX style regex matching multiple files (optional)"""))
    parser_io.add_argument("--bam_file", "-a", default="", type=str, nargs='+',
        help=textwrap.dedent("""Path to a Bam file corresponding to reads in the summary_file. Preferably aligned with Minimap2
          One can also pass multiple space separated file paths or a UNIX style regex matching multiple files (optional)"""))
    parser_io.add_argument("--html_outfile", "-o", default="", type=str,
        help="Path to an output html file report (required if json_outfile not given)")
    parser_io.add_argument("--json_outfile", "-j", default="", type=str,
        help="Path to an output json file report (required if html_outfile not given)")
    parser_filt = parser.add_argument_group('Filtering options')
    parser_filt.add_argument("--min_pass_qual", "-q", default=7, type=int,
        help="Minimum quality to consider a read as 'pass' (default: %(default)s)")
    parser_filt.add_argument("--filter_calibration", default=False, action='store_true',
        help="If given reads flagged as calibration strand by the basecaller are removed (default: %(default)s)")
    parser_filt.add_argument("--min_barcode_percent", default=0.1, type=float,
        help="Minimal percent of total reads to retain barcode label. If below the barcode value is set as `unclassified` (default: %(default)s)")
    parser_html = parser.add_argument_group('HTML report options')
    parser_html.add_argument("--report_title", "-t", default="pycoQC report", type=str,
        help="Title to use in the html report (default: %(default)s)")
    parser_html.add_argument("--template_file", type=str, default="",
        help="Jinja2 html template for the html report (default: %(default)s)")
    parser_html.add_argument("--config_file", "-c", type=str, default="",
        help=textwrap.dedent("""Path to a JSON configuration file for the html report.
            If not provided, looks for it in ~/.pycoQC and ~/.config/pycoQC/config. If it's still not found, falls back to default parameters.
            The first level keys are the names of the plots to be included.
            The second level keys are the parameters to pass to each plotting function (default: %(default)s)")"""))
    parser_other = parser.add_argument_group('Other options')
    parser_other.add_argument("--sample", default=100000, type=int,
        help="If not None a n number of reads will be randomly selected instead of the entire dataset for ploting function (deterministic sampling) (default: %(default)s)")
    parser_other.add_argument("--default_config", "-d", action='store_true',
        help="Print default configuration file. Can be used to generate a template JSON file (default: %(default)s)")
    parser_verbosity = parser.add_mutually_exclusive_group()
    parser_verbosity.add_argument("-v", "--verbose", action="store_true", default=False,
        help="Increase verbosity (default: %(default)s)")
    parser_verbosity.add_argument("-q", "--quiet", action="store_true", default=False,
        help="Reduce verbosity (default: %(default)s)")

    # Try to parse arguments
    args = parser.parse_args()

    # Set logging level
    logger = get_logger (name=__name__, verbose=args.verbose, quiet=args.quiet)

    # Print the default config parameters and exit
    if args.default_config:
        config_file = resource_filename("pycoQC", "templates/pycoQC_config.json")
        with open (config_file) as fp:
            sys.stdout.write(fp.read())
        sys.exit()

    elif not args.summary_file:
        logger.warning ("ERROR: `--summary_file` is a required argument")
        parser.print_help()
        sys.exit()

    elif not args.html_outfile and not args.json_outfile:
        logger.warning ("ERROR: At least one output file required `--html_outfile` or `--json_outfile`")
        parser.print_help()
        sys.exit()

    # Run pycoQC
    pycoQC (
        summary_file = args.summary_file,
        barcode_file = args.barcode_file,
        bam_file = args.bam_file,
        filter_calibration = args.filter_calibration,
        min_barcode_percent = args.min_barcode_percent,
        min_pass_qual = args.min_pass_qual,
        sample = args.sample,
        html_outfile = args.html_outfile
        report_title = args.report_title
        config_file = args.config_file
        template_file = args.template_file
        json_outfile = args.json_outfile
        verbose = args.verbose,
        quiet = args.quiet)
