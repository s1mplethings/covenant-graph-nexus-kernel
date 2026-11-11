"""Convert generic events for existing host event appenders."""


def event_payload(event):
    return event.as_dict()
