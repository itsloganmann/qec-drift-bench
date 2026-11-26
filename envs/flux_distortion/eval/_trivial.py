"""No-effort baseline: keep the nominal predistortion and report no change. Licence: Apache-2.0."""


def solve(data):
    return {"filters": data["nominal_stages"], "diagnosis": {"changed": False, "kinds": {}}}
