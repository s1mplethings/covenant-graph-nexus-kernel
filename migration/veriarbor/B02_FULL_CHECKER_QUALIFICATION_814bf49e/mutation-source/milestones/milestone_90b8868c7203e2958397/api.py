"""Campaign CRUD module (M4).



Provides persistent, isolated campaign management with validation and history tracking.

Reuses M1 project isolation and persistence patterns.

"""



import json

import os

import uuid



MILESTONE_ID = "M4"



_PROJECTS_FILENAME = "projects.json"

_CAMPAIGNS_FILENAME = "campaigns.json"





def _path(data_dir, filename):

    return os.path.join(data_dir, filename)





def _load_list(data_dir, filename):

    path = _path(data_dir, filename)

    if not os.path.exists(path):

        return []

    with open(path, "r", encoding="utf-8") as f:

        content = f.read()

    if not content.strip():

        return []

    data = json.loads(content)

    if not isinstance(data, list):

        return []

    return data





def _save_list(data_dir, filename, items):

    os.makedirs(data_dir, exist_ok=True)

    path = _path(data_dir, filename)

    tmp_path = path + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:

        json.dump(items, f, ensure_ascii=False)

    os.replace(tmp_path, path)





def _load_projects(data_dir):

    return _load_list(data_dir, _PROJECTS_FILENAME)





def _require_project(data_dir, project_id):

    if not isinstance(project_id, str) or not project_id:

        raise ValueError("project_id must be a non-empty string")

    for record in _load_projects(data_dir):

        if record.get("id") == project_id:

            return record

    raise ValueError("project not found: %s" % project_id)





def _validate_channels(channels):

    if not isinstance(channels, list):

        raise ValueError("channels must be a list")

    if len(channels) == 0:

        raise ValueError("channels must not be empty")

    seen = set()

    for c in channels:

        if not isinstance(c, str):

            raise ValueError("channels must contain only strings")

        if not c.strip():

            raise ValueError("channels must not contain empty strings")

        if c in seen:

            raise ValueError("channels must be unique")

        seen.add(c)





def _find_campaign(campaigns, project_id, campaign_id):

    if not isinstance(campaign_id, str) or not campaign_id:

        raise ValueError("campaign_id must be a non-empty string")

    for record in campaigns:

        if record.get("id") == campaign_id:

            if record.get("project_id") != project_id:

                raise ValueError("campaign not found: %s" % campaign_id)

            return record

    raise ValueError("campaign not found: %s" % campaign_id)





def _public_campaign(record):

    return {

        "id": record["id"],

        "project_id": record["project_id"],

        "name": record["name"],

        "audience": record["audience"],

        "channels": record["channels"],

        "status": record["status"],

        "history": record["history"]

    }





def handle(data_dir, request):

    if not isinstance(data_dir, str) or not data_dir:

        raise ValueError("data_dir must be a non-empty string")

    if not isinstance(request, dict):

        raise ValueError("request must be a dict")



    op = request.get("op")

    if not isinstance(op, str) or not op:

        raise ValueError("request must contain a non-empty 'op' string")



    if op == "campaign.create":

        project_id = request.get("project_id")

        _require_project(data_dir, project_id)



        name = request.get("name")

        if not isinstance(name, str) or not name.strip():

            raise ValueError("name must be a non-empty string")



        audience = request.get("audience")

        if not isinstance(audience, str) or not audience.strip():

            raise ValueError("audience must be a non-empty string")



        channels = request.get("channels")

        _validate_channels(channels)



        campaigns = _load_list(data_dir, _CAMPAIGNS_FILENAME)

        record = {

            "id": uuid.uuid4().hex,

            "project_id": project_id,

            "name": name,

            "audience": audience,

            "channels": channels,

            "status": "ACTIVE",

            "history": []

        }

        campaigns.append(record)

        _save_list(data_dir, _CAMPAIGNS_FILENAME, campaigns)

        return _public_campaign(record)



    if op == "campaign.get":

        project_id = request.get("project_id")

        _require_project(data_dir, project_id)

        campaign_id = request.get("campaign_id")

        

        campaigns = _load_list(data_dir, _CAMPAIGNS_FILENAME)

        target_campaign = _find_campaign(campaigns, project_id, campaign_id)

        

        return _public_campaign(target_campaign)



    if op == "campaign.update":

        project_id = request.get("project_id")

        _require_project(data_dir, project_id)

        campaign_id = request.get("campaign_id")

        

        campaigns = _load_list(data_dir, _CAMPAIGNS_FILENAME)

        target_campaign = _find_campaign(campaigns, project_id, campaign_id)

        

        if target_campaign["status"] == "ARCHIVED":

            raise ValueError("cannot update archived campaign")

            

        # Validate new inputs

        name = request.get("name")

        if not isinstance(name, str) or not name.strip():

            raise ValueError("name must be a non-empty string")

            

        audience = request.get("audience")

        if not isinstance(audience, str) or not audience.strip():

            raise ValueError("audience must be a non-empty string")

            

        channels = request.get("channels")

        _validate_channels(channels)

        

        # Append previous state to history

        prev_state = {

            "id": target_campaign["id"],

            "project_id": target_campaign["project_id"],

            "name": target_campaign["name"],

            "audience": target_campaign["audience"],

            "channels": list(target_campaign["channels"]),

            "status": target_campaign["status"]

        }

        if not isinstance(target_campaign.get("history"), list):

            target_campaign["history"] = []

        target_campaign["history"].append(prev_state)

        

        # Update fields (preserving id and project_id)

        target_campaign["name"] = name

        target_campaign["audience"] = audience

        target_campaign["channels"] = channels

        

        _save_list(data_dir, _CAMPAIGNS_FILENAME, campaigns)

        return _public_campaign(target_campaign)



    if op == "campaign.archive":

        project_id = request.get("project_id")

        _require_project(data_dir, project_id)

        campaign_id = request.get("campaign_id")

        

        campaigns = _load_list(data_dir, _CAMPAIGNS_FILENAME)

        target_campaign = _find_campaign(campaigns, project_id, campaign_id)

        

        target_campaign["status"] = "ARCHIVED"

        

        _save_list(data_dir, _CAMPAIGNS_FILENAME, campaigns)

        return _public_campaign(target_campaign)



    if op == "campaign.list":

        project_id = request.get("project_id")

        _require_project(data_dir, project_id)

        

        campaigns = _load_list(data_dir, _CAMPAIGNS_FILENAME)

        items = [_public_campaign(r) for r in campaigns if r.get("project_id") == project_id]

        return {"items": items}



    raise ValueError("unknown operation: %s" % op)

