"""Read participant 2's public tool envelopes; retain legacy dry-run fixtures."""


def page(observation):
    if "result" in observation:
        result = observation["result"]
        return [item["record"] for item in result["items"]], result.get("next_cursor")
    return observation["records"], observation.get("next_cursor")


def record(observation):
    return observation["result"]["record"] if "result" in observation else observation["record"]
