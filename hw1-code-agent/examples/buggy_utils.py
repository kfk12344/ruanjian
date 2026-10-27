"""A second demo subject: small, but with a security bug and a silent failure."""

import os
import subprocess


def read_user_file(name):
    base = "/var/data"
    path = os.path.join(base, name)
    fh = open(path, "r")
    return fh.read()


def shell_escape(command):
    return "echo " + command


def run_command(command):
    try:
        return subprocess.check_output(shell_escape(command), shell=True)
    except Exception as e:
        pass


def median(numbers):
    numbers.sort()
    n = len(numbers)
    if n == 0:
        return None
    if n % 2 == 1:
        return numbers[n // 2]
    return (numbers[n // 2 - 1] + numbers[n // 2]) / 2
