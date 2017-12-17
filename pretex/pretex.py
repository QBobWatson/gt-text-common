#!env python3

# Manages a pool of processtex jobs
# Don't do this in processtex, to avoid crashes...

import argparse
import os

from multiprocessing import Pool, cpu_count
from random import shuffle
from subprocess import Popen


PROCESSTEX = os.path.join(os.path.dirname(__file__), 'processtex.py')


def chunks(l, n):
    "Yield successive n-sized chunks from l."
    for i in range(0, len(l), n):
        yield l[i:i+n]

def job(arg):
    args, htmls = arg
    cmdline = [
        'python3', PROCESSTEX,
        '--preamble', args.preamble,
        '--style-path', args.style_path,
        '--cache-dir', args.cache_dir,
        '--img-dir', args.img_dir,
    ]
    if args.no_cache:
        cmdline.append('--no-cache')
    proc = Popen(cmdline + htmls)
    proc.wait()
    if proc.returncode != 0:
        raise Exception("Call failed")

def main():
    parser = argparse.ArgumentParser(
        description='Process LaTeX in html files: job dispatcher.')
    parser.add_argument('--preamble', default='preamble.tex', type=str,
                        help='LaTeX preamble')
    parser.add_argument('--style-path', default='', type=str,
                        help='Location of LaTeX style files')
    parser.add_argument('--cache-dir', default='pretex-cache', type=str,
                        help='Cache directory')
    parser.add_argument('--img-dir', default='figure-images', type=str,
                        help='LaTeX image include directory')
    parser.add_argument('--no-cache', action='store_true',
                        help='Ignore cache and regenerate')
    parser.add_argument('--chunk-size', type=int, default=50,
                        help='Run processtex on chunks of this size')
    parser.add_argument('htmls', type=str, nargs='+',
                        help='HTML files to process')
    args = parser.parse_args()

    # Process in a random order.  Otherwise one process gets all the section files.
    shuffle(args.htmls)

    with Pool(processes=cpu_count()-1) as pool:
        job_args = []
        for chunk in chunks(args.htmls, args.chunk_size):
            job_args.append((args, chunk))
        result = pool.map_async(
            job, job_args, error_callback=lambda x: pool.close())
        result.wait()

if __name__ == "__main__":
    main()
