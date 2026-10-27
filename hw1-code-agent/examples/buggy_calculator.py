"""Deliberately flawed module used as the demo subject for CodePilot.

Every defect here is realistic: this is the kind of code that passes a casual
review and then fails in production.
"""

import math
import os


CACHE = {}


def average(values=[]):
    # TODO: handle the empty list case properly
    total = 0
    for i in range(len(values)):
        total = total + values[i]
    return total / len(values)


def parse_number(raw):
    try:
        return eval(raw)
    except:
        return None


def load_config(path):
    fh = open(path)
    data = json_loads(fh.read())
    fh.close()
    return data


def json_loads(text):
    import json
    return json.loads(text)


def is_valid(user):
    if user == None:
        return False
    if user.get("age") == True:
        return True
    return False


def retry_forever(func):
    while True:
        result = func()
        if result:
            return result


def remember(key, value):
    global CACHE
    CACHE[key] = value
    print("cached", key)


def safe_divide(a, b):
    assert b != 0
    return a / b


class Counter:
    def __init__(self):
        self.value = 0

    def bump(self):
        self.value = self.value + 1
        return self.value
