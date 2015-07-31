__author__ = 'm3adow'

"""
(Planned) functionality:
1. Run in an infinite Loop
2. If there's a new file in the configured watch dir matching a criteria, act accordingly. Possible methods:
    - Do a normal "jekyll build" with specified configuration
    - Commit changes to github either with the text within the control file or with an default message
    - Exit
"""

import os.path
import time
import logging
import argparse
import configparser
import sys

from subprocess import call

from logging import handlers

def parse_args():
    parser = argparse.ArgumentParser(description="Control jekyll by control files")
    parser.add_argument('conf_path', metavar='config_path', help="Path to the configuration file")
    args = parser.parse_args()
    return args


def read_conf(path, logger):
    try:
        conf = configparser.ConfigParser()
        conf.read_file(open(path))
    except FileNotFoundError as e:
        logger.critical("Couldn't read config file %s: %s" % (path, e))
        exit(1)
    else:
        return conf


def configure_logger(conf, logger):
    if not conf.has_section('LOGGING'):
        logger.info('No custom logging configured.')
        logger.setLevel(logging.WARNING)
        return
    if conf.has_option('LOGGING', 'logfile'):
        max_size = conf.getint('LOGGING', 'logfile_maxsize', fallback=10485760)
        logger.addHandler(logging.handlers.RotatingFileHandler(conf['LOGGING']['logfile'], maxBytes=max_size))
    if conf.has_option('LOGGING', 'loglevel'):
        logger.setLevel(conf['LOGGING']['loglevel'])
    else:
        logger.setLevel(logging.WARNING)
    for handler in logger.handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s: %(message)s"))


def supervise(conf, control_files, logger):
    try:
        # Normalize path
        watchdir = conf['CONFIG']['watchdir'].rstrip('\\/') + '/'
    except KeyError as e:
        logger.critical("Couldn't find watchdir: %s" % e)
        exit(2)
    shoopdaloop = True
    interval = conf.getint('CONFIG', 'watch_interval', fallback=60)
    # -1 should always be less than the epoch time we'll get for mtime
    mtime_last = -1
    while shoopdaloop:
        logger.debug("New loop.")
        try:
            mtime = os.path.getmtime(watchdir)
        except os.error as e:
            logger.error("Couldn't get mtime of watchdir %s (%s). Skipping." % (watchdir, e))
            mtime = -1
        if (mtime - mtime_last) == 0:
            time.sleep(interval)
            continue

        for key, value in control_files.items():
            # We'll process exit files after the loop
            if key == 'exit':
                continue
            ctrl_file = watchdir + value
            if os.path.exists(ctrl_file):
                try:
                    kwargs = dict(conf.items(key))
                    kwargs['task_name'] = key
                except configparser.NoSectionError:
                    kwargs = {'task_name': key}
                t1 = time.time()
                globals()[key](logger, **kwargs)
                t2 = time.time()
                logger.debug("Running %s task took %s." % (key, t2 - t1))

                try:
                    os.remove(ctrl_file)
                except OSError as e:
                    logger.error("Couldn't remove file %s: %s" % (ctrl_file, e))

        if os.path.exists(watchdir + control_files['exit']):
            logger.info("Found exit file '%s'. Exiting." % control_files['exit'])
            os.remove(watchdir + control_files['exit'])
            exit()
        mtime_last = mtime
        time.sleep(interval)


def jekyll_build(logger, **kwargs):
    if 'cmd' in kwargs:
        cmd = kwargs['cmd']
    else:
        cmd = 'jekyll build'
    try:
        ret = call(cmd, shell=True)
        if ret != 0:
            logger.error("Task %s was terminated by signal %s" % (kwargs['task_name'], -ret))
        else:
            logger.error("Task %s returned" % (kwargs['task_name'], ret))
    except OSError as e:
        logger.warning("Execution of task %s failed:" % (kwargs['task_name'], e))


def deploy_to_gh_pages(conf, logger, **kwargs):
    pass


def main():
    control_files = {
        "jekyll_build": ".BUILD",
        "deploy_to_gh_pages": ".DEPLOY",
        "exit": ".EXIT"
    }
    # Prepend a 'd' as filename for Windows because Windows doesn't like .filenames
    if sys.platform == 'win32':
        control_files = {key: 'd' + value for (key, value) in control_files.items()}
    args = vars(parse_args())
    # default logger before config
    logger = logging.getLogger('jekyll_dropbox_remote')
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    conf = read_conf(args['conf_path'], logger)
    configure_logger(conf, logger)
    supervise(conf, control_files, logger)


if __name__ == "__main__":
    main()
