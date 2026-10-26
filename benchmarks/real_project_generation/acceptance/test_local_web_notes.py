from __future__ import annotations

from _helpers import assert_project_hygiene, request, server


def test_notes_runtime_and_persistence(tmp_path):
    assert_project_hygiene()
    with server("notes_app", tmp_path) as port:
        status, html, _ = request(port, "GET", "/"); assert status == 200 and "note" in str(html).lower()
        status, notes, _ = request(port, "GET", "/api/notes"); assert status == 200 and isinstance(notes, list)
        status, created, _ = request(port, "POST", "/api/notes", {"text": "persist me"}); assert status in {200, 201}
        note_id = str(created["id"])
        status, _, _ = request(port, "POST", "/api/notes", {}); assert status in {400, 422}
    with server("notes_app", tmp_path) as port:
        status, notes, _ = request(port, "GET", "/api/notes"); assert status == 200 and any(str(row["id"]) == note_id for row in notes)
        status, _, _ = request(port, "DELETE", f"/api/notes/{note_id}"); assert status in {200, 204}
        status, notes, _ = request(port, "GET", "/api/notes"); assert all(str(row["id"]) != note_id for row in notes)
