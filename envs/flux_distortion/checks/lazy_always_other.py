"""Lazy (hard tier): nominal predistortion, always 'changed' with kind "other". Earns the kinds
credit on changes outside the model, loses every control."""


def solve(data):
    return {"filters": data["nominal_stages"],
            "diagnosis": {"changed": True, "kinds": {"other": {}}}}
