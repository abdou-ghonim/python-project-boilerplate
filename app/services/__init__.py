"""Business logic.

    item_service.py   the demo domain, API → service → model
    jobs.py           the RQ queue and the tasks that run on it

Services hold the behaviour; API modules translate HTTP to a service call and
back. Keeping the rule means logic stays reachable from a CLI command or a
background job, neither of which has a request to read.
"""
