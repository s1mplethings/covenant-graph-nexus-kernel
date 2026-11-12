"""Pure evidence checks; candidate execution/decoding must remain isolated."""
def media_ok(probe,decode_exit,expected_duration):
    return decode_exit==0 and {'video','audio'} <= {s['codec_type'] for s in probe.get('streams',[])} and abs(float(probe.get('format',{}).get('duration',-100))-expected_duration)<=1

def location_ok(hit,source_id,duration):
    return hit['video_id']==source_id and 0<=hit['from']<hit['to']<=duration+2

def persistence_ok(before,after):
    return bool(before) and before==after

def source_audio_ok(similarity):
    return similarity>=.90
