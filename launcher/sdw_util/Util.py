"""
Utility functions used by both the launcher and notifier scripts
"""

import fcntl
import os
import logging
import re
import subprocess

from logging.handlers import TimedRotatingFileHandler

# The directory where status files and logs are stored
BASE_DIRECTORY = os.path.join(os.path.expanduser("~"), ".securedrop_launcher")

# Directory for lock files to avoid contention or multiple instantiation.
LOCK_DIRECTORY = os.path.join("/run/user", str(os.getuid()))

# Folder where logs are stored
LOG_DIRECTORY = os.path.join(BASE_DIRECTORY, "logs")

# File that contains Qubes version information (overridden by tests)
OS_RELEASE_FILE = "/etc/os-release"

# Shared error string
LOCK_ERROR = "Error obtaining lock on '{}'. Process may already be running."

# Format for those logs
LOG_FORMAT = "%(asctime)s - %(name)s:%(lineno)d(%(funcName)s) " "%(levelname)s: %(message)s"

# Namespace for primary logger, additional namespaces should be defined by module user
SD_LOGGER_PREFIX = "sd"

sdlog = logging.getLogger(SD_LOGGER_PREFIX + "." + __name__)


def configure_logging(log_file, logger_namespace=SD_LOGGER_PREFIX, backup_count=0):
    """
    All logging related settings are set up by this function.

    `log_file` - the filename
    `logger_namespace - the prefix used for all log events by this logger
    `backup_count` - if nonzero, at most backup_count files will be kept
    """

    if not os.path.exists(LOG_DIRECTORY):
        os.makedirs(LOG_DIRECTORY)

    formatter = logging.Formatter((LOG_FORMAT))

    handler = TimedRotatingFileHandler(
        os.path.join(LOG_DIRECTORY, log_file), backupCount=backup_count
    )
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)

    log = logging.getLogger(logger_namespace)
    log.setLevel(logging.INFO)
    log.addHandler(handler)


def obtain_lock(basename):
    """
    Obtain an exclusive lock during the execution of this process.
    """
    lock_file = os.path.join(LOCK_DIRECTORY, basename)
    try:
        lh = open(lock_file, "w")
    except PermissionError:  # noqa: F821
        sdlog.error(
            "Error writing to lock file '{}'. User may lack the "
            "required permissions.".format(lock_file)
        )
        return None

    try:
        # Obtain an exclusive, nonblocking lock
        fcntl.lockf(lh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        sdlog.error(LOCK_ERROR.format(lock_file))
        return None

    return lh


def can_obtain_lock(basename):
    """
    We temporarily obtain a shared, nonblocking lock to a lockfile to determine
    whether the associated process is currently running. Returns True if it is
    safe to continue execution (no lock conflict), False if not.

    `basename` is the basename of a lockfile situated in the LOCK_DIRECTORY.
    """
    lock_file = os.path.join(LOCK_DIRECTORY, basename)
    try:
        lh = open(lock_file, "r")
    except FileNotFoundError:  # noqa: F821
        # Process may not have run during this session, safe to continue
        return True

    try:
        # Obtain a nonblocking, shared lock
        fcntl.lockf(lh, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except IOError:
        sdlog.error(LOCK_ERROR.format(lock_file))
        return False

    return True


def is_conflicting_process_running(list):
    """
    Check if any process of the given name is currently running. Aborts on the
    first match.
    """
    for name in list:
        result = subprocess.run(
            args=["pgrep", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            sdlog.error("Conflicting process '{}' is currently running.".format(name))
            return True
    return False


def get_qubes_version():
    """
    Helper function for checking the Qubes version. Returns None if not on Qubes.
    """
    is_qubes = False
    version = None
    try:
        with open(OS_RELEASE_FILE) as f:
            for line in f:
                try:
                    key, value = line.rstrip().split("=")
                except ValueError:
                    continue

                if key == "NAME" and "qubes" in value.lower():
                    is_qubes = True
                if key == "VERSION":
                    version = value
    except FileNotFoundError:
        return None

    if not is_qubes:
        return None

    return version


def get_qt_version():
    """
    Determine the version of Qt appropriate for the environment we're in.
    """
    qubes_version = get_qubes_version()

    # For now we must support both Qt4 and Qt5. We default to Qt4, because
    # that's used in Qubes 4.0, the current stable version.
    if qubes_version is not None and "4.1" in qubes_version:
        default_version = 5
    else:
        default_version = 4

    version_str = os.getenv("SDW_UPDATER_QT", default_version)
    try:
        version = int(version_str)
    except ValueError:
        version = None

    if version in [4, 5]:
        return version
    else:
        raise ValueError("Qt version not supported: {}".format(version_str))


def get_logger(prefix=SD_LOGGER_PREFIX, module=None):
    if module is None:
        return logging.getLogger(prefix)
    else:
        return logging.getLogger(prefix + "." + module)


def strip_ansi_colors(str):
    """
    Strip ANSI colors from command output
    """
    return re.sub(r"\u001b\[.*?[@-~]", "", str)
