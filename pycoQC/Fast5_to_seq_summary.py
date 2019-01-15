# Disable multithreading for MKL and openBlas
import os
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["MKL_THREADING_LAYER"] = "sequential"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ['OPENBLAS_NUM_THREADS'] = '1'

#~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~#
# Standard library imports
import multiprocessing as mp
from time import time
from collections import *
import traceback
import logging

# Third party imports
import numpy as np
import pandas as pd
import h5py
from tqdm import tqdm

# Local imports
from pycoQC.common import *

# Logger setup
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
logLevel_dict = logLevel_dict = {2:logging.DEBUG, 1:logging.INFO, 0:logging.WARNING}

#~~~~~~~~~~~~~~CLASS~~~~~~~~~~~~~~#
class Fast5_to_seq_summary ():
    """
    Create a summary file akin the one generated by Albacore or Guppy from a directory containing
    multiple fast5 files. The script will attempt to extract all the required fields but will not
    raise an error if not found.
    """
    # Map attrs location in hdf5
    attrs_grp_dict = {
        "mean_qscore_template": {"grp":"summary_basecall", "attrs": "mean_qscore"},
        "sequence_length_template": {"grp":"summary_basecall", "attrs": "sequence_length"},
        "called_events": {"grp":"summary_basecall", "attrs": "called_events"},
        "skip_prob": {"grp":"summary_basecall", "attrs": "skip_prob"},
        "stay_prob": {"grp":"summary_basecall", "attrs": "stay_prob"},
        "step_prob": {"grp":"summary_basecall", "attrs": "step_prob"},
        "strand_score": {"grp":"summary_basecall", "attrs": "strand_score"},
        "read_id": {"grp":"raw_read", "attrs": "read_id"},
        "start_time": {"grp":"raw_read", "attrs": "start_time"},
        "duration": {"grp":"raw_read", "attrs": "duration"},
        "start_mux": {"grp":"raw_read", "attrs": "start_mux"},
        "read_number": {"grp":"raw_read", "attrs": "read_number"},
        "channel": {"grp":"channel_id", "attrs": "channel_number"},
        "channel_digitisation": {"grp":"channel_id", "attrs": "digitisation"},
        "channel_offset": {"grp":"channel_id", "attrs": "offset"},
        "channel_range": {"grp":"channel_id", "attrs": "range"},
        "channel_sampling_rate": {"grp":"channel_id", "attrs": "sampling_rate"},
        "run_id": {"grp":"tracking_id", "attrs": "run_id"},
        "sample_id": {"grp":"tracking_id", "attrs": "sample_id"},
        "device_id": {"grp":"tracking_id", "attrs": "device_id"},
        "protocol_run_id": {"grp":"tracking_id", "attrs": "protocol_run_id"},
        "flow_cell_id": {"grp":"tracking_id", "attrs": "flow_cell_id"},
        "calibration_strand_genome_template": {"grp":"summary_calibration", "attrs": "genome"},
        "calibration_strand_end": {"grp":"summary_calibration", "attrs": "genome_end"},
        "calibration_strand_start": {"grp":"summary_calibration", "attrs": "genome_start"},
        "calibration_strand_identity": {"grp":"summary_calibration", "attrs": "identity"},
        "barcode_arrangement": {"grp":"summary_barcoding", "attrs": "barcode_arrangement"},
        "barcode_full_arrangement": {"grp":"summary_barcoding", "attrs": "barcode_full_arrangement"},
        "barcode_score": {"grp":"summary_barcoding", "attrs": "barcode_score"},
    }

    def __init__ (self,
        fast5_dir,
        seq_summary_fn,
        max_fast5 = 0,
        threads = 4,
        basecall_id = 0,
        verbose_level = 0,
        include_path = False,
        fields = [
            "read_id", "run_id", "channel", "start_time",
            "sequence_length_template", "mean_qscore_template",
            "calibration_strand_genome_template", "barcode_arrangement"]):
        """
        * fast5_dir
            Directory containing fast5 files. Can contain multiple subdirectories
        * seq_summary_fn
            path of the summary sequencing file where to write the data extracted from the fast5 files
        * max_fast5 (default = 0)
            Maximum number of file to try to parse. 0 to deactivate
        * threads
            Total number of threads to use. 1 thread is used for the reader and 1 for the writer. Minimum 3 (default = 4)
        * fields
            list of field names corresponding to attributes to try to fetch from the fast5 files. List a valid field names:
            mean_qscore_template, sequence_length_template, called_events, skip_prob, stay_prob, step_prob, strand_score, read_id, start_time,
            duration, start_mux, read_number, channel, channel_digitisation, channel_offset, channel_range, channel_sampling,
            run_id, sample_id, device_id, protocol_run, flow_cell, calibration_strand, calibration_strand, calibration_strand,
            calibration_strand, barcode_arrangement, barcode_full, barcode_score
        * basecall_id
            id of the basecalling group. By default leave to 0, but if you perfome multiple basecalling on the same fast5 files,
            this can be used to indicate the corresponding group (1, 2 ...)
        * include_path
            If True the absolute path to the corresponding file is added in an extra column
        * verbose_level INT [Default 0]
            Level of verbosity, from 2 (Chatty) to 0 (Nothing)
        """
        # Set logging level
        logger.setLevel(logLevel_dict.get(verbose_level, logging.WARNING))

        # Perform checks
        logger.info ("Check input data and options")
        if not os.access(fast5_dir, os.R_OK):
            raise pycoQCError ("Cannot read the indicated fast5 directory")
        if not os.access(os.path.dirname(seq_summary_fn), os.W_OK):
            raise pycoQCError ("Cannot write the indicated seq_summary_fn")
        if threads < 3:
            raise pycoQCError ("At least 3 threads required")
        for field in fields:
            if not field in self.attrs_grp_dict:
                raise pycoQCError ("Field {} is not valid, please choose among the following valid fields: {}".format(field, ",".join(self.attrs_grp_dict.keys())))

        # Save self args
        self.fast5_dir = fast5_dir
        self.seq_summary_fn = seq_summary_fn
        self.threads = threads-2
        self.max_fast5 = max_fast5
        self.fields = fields
        self.basecall_id = basecall_id
        self.include_path = include_path
        self.verbose_level = verbose_level

        # Init Multiprocessing variables
        in_q = mp.Queue (maxsize=1000)
        out_q = mp.Queue (maxsize=1000)
        error_q = mp.Queue ()
        counter_q = mp.Queue ()

        # Define processes
        ps_list = []
        ps_list.append (mp.Process (target=self._list_fast5, args=(in_q, error_q)))
        for i in range (self.threads):
            ps_list.append (mp.Process (target=self._read_fast5, args=(in_q, out_q, error_q, counter_q, i)))
        ps_list.append (mp.Process (target=self._write_seq_summary, args=(out_q, error_q, counter_q)))


        logger.info ("Start processing fast5 files")
        try:
            # Start all processes
            for ps in ps_list:
                ps.start ()
            # Monitor error queue
            for tb in iter (error_q.get, None):
                raise pycoQCError(tb)
            # Join processes
            for ps in ps_list:
                ps.join ()

        # Kill processes if any error
        except (BrokenPipeError, KeyboardInterrupt, pycoQCError) as E:
            for ps in ps_list:
                ps.terminate ()
            logger.info ("\nAn error occured. All processes were killed\n")
            raise E

    def _list_fast5 (self, in_q, error_q):
        """
        Mono-threaded worker adding fast5 files found in a directory tree recursively
        to a feeder queue for the multiprocessing workers
        """
        logger.debug ("[READER] Start listing fast5 files")
        try:
            # Load an input queue with fast5 file path
            for i, fast5_fn in enumerate(recursive_file_gen (dir=self.fast5_dir, ext="fast5")):
                if self.max_fast5 and i == self.max_fast5:
                    break
                in_q.put(fast5_fn)

            # Raise error is no file found
            if i == 0:
                raise pycoQCError ("No valid fast5 files found in indicated folder")

            logger.debug ("[READER] Add a total of {} files to input queue".format(i+1))

        # Manage exceptions and deal poison pills
        except Exception:
            error_q.put (traceback.format_exc())
        finally:
            for i in range (self.threads):
                in_q.put(None)

    def _read_fast5 (self, in_q, out_q, error_q, counter_q, worker_id):
        """
        Multi-threaded workers in charge of parsing fast5 file.
        """
        logger.debug ("[WORKER_{:02}] Start processing fast5 files".format(worker_id))
        try:
            c = {"overall":Counter (), "fields_found":Counter(), "fields_not_found":Counter()}

            for fast5_fn in iter(in_q.get, None):

                # Try to extract data from the fast5 file
                d = OrderedDict()
                with h5py.File(fast5_fn, "r") as h5_fp:

                    # Define group names for current read
                    grp_dict = {
                        "raw_read" : "/Raw/Reads/{}/".format(list(h5_fp["/Raw/Reads"].keys())[0]),
                        "summary_basecall" : "/Analyses/Basecall_1D_{:03}/Summary/basecall_1d_template/".format(self.basecall_id),
                        "summary_calibration" : "/Analyses/Calibration_Strand_Detection_{:03}/Summary/calibration_strand_template/".format(self.basecall_id),
                        "summary_barcoding" : "/Analyses/Barcoding_{:03}/Summary/barcoding/".format(self.basecall_id),
                        "tracking_id" : "UniqueGlobalKey/tracking_id",
                        "channel_id" : "UniqueGlobalKey/channel_id"}

                    # Fetch required fields is available
                    for field in self.fields:

                        # Special case for start time
                        if field == "start_time":
                            start_time = self._get_h5_attrs (fp=h5_fp,
                                grp=grp_dict[self.attrs_grp_dict["start_time"]["grp"]],
                                attrs=self.attrs_grp_dict["start_time"]["attrs"])
                            sampling_rate = self._get_h5_attrs (fp=h5_fp,
                                grp=grp_dict[self.attrs_grp_dict["channel_sampling_rate"]["grp"]],
                                attrs=self.attrs_grp_dict["channel_sampling_rate"]["attrs"])
                            if start_time and sampling_rate:
                                d[field] = int(start_time/sampling_rate)
                                c["fields_found"][field] +=1
                            else:
                                c["fields_not_found"][field] +=1
                        # Everything else
                        else:
                            v = self._get_h5_attrs (
                                fp=h5_fp, grp=grp_dict[self.attrs_grp_dict[field]["grp"]], attrs=self.attrs_grp_dict[field]["attrs"])
                            if v:
                                d[field] = v
                                c["fields_found"][field] +=1
                            else:
                                c["fields_not_found"][field] +=1

                if self.include_path:
                    d["path"] = os.path.abspath(fast5_fn)

                # Put read data in queue
                if d:
                    out_q.put(d)
                    c["overall"]["valid files"] += 1
                else:
                    c["overall"]["invalid files"]

            # Put counter in counter queue
            counter_q.put(c)

        # Manage exceptions and deal poison pills
        except Exception:
            error_q.put (traceback.format_exc())
        finally:
            out_q.put(None)

    def _write_seq_summary (self, out_q, error_q, counter_q):
        """
        Mono-threaded Worker writing the sequencing summary file
        """
        logger.debug ("[WRITER] Start collecting summary data")

        t = time()
        try:
            l = []
            with tqdm (unit=" reads", mininterval=0.1, smoothing=0.1, disable=self.verbose_level==2) as pbar:
                # Collect line data
                for _ in range (self.threads):
                    for d in iter (out_q.get, None):
                        l.append(d)
                        pbar.update(1)

            # Transform collected data to dataframe and write to file
            logger.debug ("[WRITER] Write data to file")
            df = pd.DataFrame(l)
            df.to_csv(self.seq_summary_fn, sep="\t", index=False)

            # Collapse data from counters comming from workers
            logger.debug ("[WRITER] Summarize counters")
            c = {"overall":Counter (), "fields_found":Counter(), "fields_not_found":Counter()}
            for _ in range (self.threads):
                worker_c = counter_q.get()
                for k, v in worker_c.items():
                    for k2, v2 in v.items():
                        c[k][k2] += v2

            logger.info ("Overall counts {}".format(counter_to_str(c["overall"])))
            logger.info ("fields found {}".format(counter_to_str(c["fields_found"])))
            logger.info ("fields not found {}".format(counter_to_str(c["fields_not_found"])))

            # Print final
            logger.warning ("Total reads: {} / Average speed: {} reads/s\n".format(len(df), round (len(df)/(time()-t), 2)))

        # Manage exceptions and deal poison pills
        except Exception:
            error_q.put (traceback.format_exc())
        finally:
            error_q.put(None)

    @staticmethod
    def _get_h5_attrs (fp, grp, attrs):
        try:
            v = fp[grp].attrs[attrs]
            if type(v) == np.bytes_:
                v = v.decode("utf8")
            return v
        except KeyError :
            return None
