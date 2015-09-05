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
        watchdir = conf['CONFIG']['watch_dir'].rstrip('\\/') + '/'
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
                    kwargs = dict(conf.items('DEFAULT'))
                    kwargs['task_name'] = key

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
        cmd = 'cd %s && ' % kwargs['jekyll_base_dir'] + kwargs['cmd']
    else:
        try:
            cmd = 'cd %s && jekyll build --drafts' % kwargs['jekyll_base_dir']
        except KeyError as e:
            logger.error("Encountered problem in taks %s. Skipping." % kwargs['task_name'])
            return

    try:
        ret = call(cmd, shell=True)
    except OSError as e:
        logger.error("Execution of task %s failed:" % (kwargs['task_name'], e))
    check_ret(ret, kwargs['task_name'], logger)


def deploy_to_gh_pages(logger, **kwargs):
    if 'jekyll_base_dir' not in kwargs:
        logger.error("Couldn't find jekyll_base_dir in config (%s). Skipping taks %s" % (
            kwargs, kwargs['task_name'])
            )
        return
    commit_msg = ["Auto commit done by jekyll_file_remote"]
    editmsg_path = kwargs['jekyll_base_dir'] + '/.git/COMMIT_EDITMSG'
    # First try to 'git add -A'
    try:
        ret = call("cd %s && git add -A" % kwargs['jekyll_base_dir'], shell=True)
    except OSError as e:
        logger.error("Error while 'git add'ing, aborting (%s)." % e)
        return

    # Then see, if the COMMIT_EDITMSG was changed due to our 'git add'
    # If so, add the modified, added and deleted files to the commit_msg
    try:
        editmsg_mtime = os.path.getmtime(editmsg_path)
        # Has the COMMIT_EDITMSG file been touched recently? Then we use some parts of it.
        if time.time() - editmsg_mtime < 30:
            with open(kwargs['jekyll_base_dir'] + '/.git/COMMIT_EDITMSG') as f:
                modified_files = [line.strip('#\n ') for line in f][6:]
            commit_msg += modified_files
    except FileNotFoundError as e:
        logger.debug("Encountered problem reading COMMIT_EDITMSG. Skipping it (%s)." % e)

    # Finally commit && push
    try:
        ret += call("cd %s && git commit -m '%s' && git push" % (
            kwargs['jekyll_base_dir'], "\n".join(commit_msg)),
            shell=True)
    except (OSError, FileNotFoundError) as e:
        logger.error("Task %s failed: %s" % (kwargs['task_name'], e))
    check_ret(ret, kwargs['task_name'], logger)


def check_ret(retcode, task_name, logger):
    if retcode == 0:
        logger.debug("Task %s was executed successfully." % task_name)
    elif retcode < 0:
        logger.error("Task %s was terminated by signal %s" % (task_name, -retcode))
    else:
        logger.error("Task %s returned %s." % (task_name, retcode))

def main():
    control_files = {
        "jekyll_build": "d.BUILD",
        "deploy_to_gh_pages": "d.DEPLOY",
        "exit": ".EXIT"
    }
    '''
    # Prepend a 'd' as filename for Windows because Windows doesn't like .filenames
    if sys.platform == 'win32':
        control_files = {key: 'd' + value for (key, value) in control_files.items()}
    '''
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
